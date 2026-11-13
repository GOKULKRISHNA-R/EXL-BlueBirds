"""Agentic integration pipeline.

    Discovery Agent -> Design Agent -> Code Generation Agent -> Validation Agent
                                             ^                        |
                                             +----- Repair loop ------+
    ... -> human approval gates (mapping, then release)

Each agent records what it did, on what evidence, and whether the step was performed by
the LLM or by the deterministic fallback. LLM output is never trusted directly:
mappings are grounded against discovered fields, and generated code is statically
checked, executed only inside an isolated subprocess, and reconciled field by field
against an independent reference before a human is asked to approve anything.
"""
from __future__ import annotations
import ast, hashlib, json, os, re, subprocess, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
import httpx
from . import core
from .config import MOCK_DIR, ARTIFACTS_DIR
from .discovery import hl7_flatten

MAX_ATTEMPTS = 3
TRANSFORMS = ["copy", "to_float", "title_case", "hl7_date_to_iso", "hl7_sex_to_fhir"]

# Target FHIR-aligned resource skeleton each generated adapter must fill.
TARGETS = {
    "lis": {"resource": "Observation", "base": {"resourceType": "Observation", "category": [{"coding": [{"code": "laboratory"}]}],
            "code": {"coding": [{"system": "http://loinc.org"}]}, "subject": {"identifier": {"system": "urn:mock-lis:patient"}}}},
    "his": {"resource": "Patient", "base": {"resourceType": "Patient"}},
    "rpm": {"resource": "Observation", "base": {"resourceType": "Observation", "status": "preliminary", "category": [{"coding": [{"code": "vital-signs"}]}],
            "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}]},
            "valueQuantity": {"unit": "beats/minute"}, "subject": {"identifier": {"system": "urn:mock-rpm:patient"}}}},
}

def _m(system, source, target, transform="copy", confidence=0.95, rationale="", review=False):
    return {"source_system": system, "source_field": source, "target_path": target, "transform": transform,
            "confidence": confidence, "rationale": rationale, "requires_review": review}

FALLBACK_MAPPINGS = [
    _m("lis", "result_status", "status", rationale="LIS status vocabulary matches FHIR Observation.status."),
    _m("lis", "loinc_code", "code.coding.0.code", confidence=0.99, rationale="Column is LOINC-coded."),
    _m("lis", "test_name", "code.coding.0.display", rationale="Human-readable test name."),
    _m("lis", "result_value", "valueQuantity.value", "to_float", 0.99, "Numeric result."),
    _m("lis", "unit", "valueQuantity.unit", rationale="Result unit."),
    _m("lis", "observed_at", "effectiveDateTime", rationale="Observation timestamp."),
    _m("lis", "patient_id", "subject.identifier.value", confidence=0.9, rationale="LIS-local patient key; linked via documented crosswalk."),
    _m("his", "PID-3.1", "identifier.0.value", confidence=0.99, rationale="CX identifier value."),
    _m("his", "PID-3.4", "identifier.0.system", rationale="CX assigning authority preserves the identifier namespace."),
    _m("his", "PID-5.1", "name.0.family", "title_case", rationale="XPN family name; HL7 sample is upper case."),
    _m("his", "PID-5.2", "name.0.given.0", "title_case", rationale="XPN given name."),
    _m("his", "PID-7", "birthDate", "hl7_date_to_iso", 0.99, "HL7 TS (YYYYMMDD) to FHIR date."),
    _m("his", "PID-8", "gender", "hl7_sex_to_fhir", rationale="HL7 table 0001 to FHIR administrative gender."),
    _m("rpm", "heart_rate_bpm", "valueQuantity.value", "to_float", rationale="Heart rate in beats per minute."),
    _m("rpm", "timestamp", "effectiveDateTime", rationale="Reading timestamp."),
    _m("rpm", "device_id", "device.identifier.value", rationale="Originating device."),
    _m("rpm", "patient_id", "subject.identifier.value", confidence=0.6, review=True,
       rationale="RPM-local ID only; no documented crosswalk, so it must not be linked to an EHR patient without review."),
]

PATTERN_RULES = [
    ("FHIR", "API-led request/response adapter", "System exposes a usable REST API; call it directly and reuse its FHIR resources."),
    ("SQL", "Read-only database view adapter (candidate for CDC)", "No API; a relational schema with a reporting view is the least invasive read path."),
    ("HL7", "Message listener + transformation (MLLP to FHIR)", "System pushes HL7 v2 events; subscribe and translate segments rather than poll."),
    ("DICOM", "Metadata query adapter (DICOMweb/REST), pixels by reference", "Imaging is large; integrate study metadata and reference images in place."),
    ("MQTT", "Event-stream subscriber with windowed aggregation", "High-frequency device telemetry; subscribe to topics and summarise before storing."),
]


# ---------------------------------------------------------------- LLM helper
def _llm_base() -> str:
    """OpenAI-compatible base URL. Ollama's native '/api/chat' is mapped to its compatible '/v1' endpoint."""
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/").removesuffix("/chat/completions")
    return base.removesuffix("/api/chat").removesuffix("/api") + "/v1" if re.search(r"/api(/chat)?$", base) else base

def _llm_is_local() -> bool:
    return bool(re.match(r"https?://(localhost|127\.0\.0\.1|\[::1\])(:|/|$)", _llm_base()))

def _llm_key() -> str:
    """API key; local servers (Ollama, LM Studio, llama.cpp) don't need one, so a placeholder is used."""
    return os.getenv("OPENAI_API_KEY", "").strip() or ("local" if _llm_is_local() else "")

def llm_available() -> bool:
    return bool(_llm_key())

_LLM_LAST_CALL_AT: float = 0.0
_LLM_MIN_INTERVAL: float = float(os.getenv("LLM_MIN_INTERVAL_S", "2"))  # default fast gap; adjust for free tiers


class CircuitBreaker:
    """Circuit Breaker for LLM integration.

    Prevents cascading hangs and timeouts from freezing the integration pipeline.
    - CLOSED: Normal operation. Requests are forwarded to the LLM.
    - OPEN: Tripped after consecutive timeouts/errors. Fails fast (0ms) to
      deterministic fallback without waiting or blocking.
    - HALF-OPEN: After a cooldown period, allows a single probe request to check
      if the LLM service has recovered.
    """
    def __init__(self, failure_threshold: int = 2, recovery_timeout_s: float = 45.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.last_failure_reason = ""
        self.state = "CLOSED"

    def allow_request(self) -> bool:
        if self.state == "OPEN":
            if time.perf_counter() - self.last_failure_time > self.recovery_timeout_s:
                self.state = "HALF-OPEN"
                print(f"[CircuitBreaker HALF-OPEN] Cooldown ({self.recovery_timeout_s}s) elapsed. Probing endpoint health.")
                return True
            return False
        return True

    def record_success(self):
        if self.state != "CLOSED":
            print(f"[CircuitBreaker CLOSED] Probe succeeded. Circuit reset to normal.")
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_failure_reason = ""

    def record_failure(self, reason: str = ""):
        self.failure_count += 1
        self.last_failure_time = time.perf_counter()
        self.last_failure_reason = reason
        if self.failure_count >= self.failure_threshold or self.state == "HALF-OPEN":
            self.state = "OPEN"
            print(f"[CircuitBreaker TRIPPED -> OPEN] {self.failure_count} consecutive failure(s): {reason}. Failing fast to deterministic fallback.")

    def reset(self):
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_failure_reason = ""


_CIRCUIT_BREAKER = CircuitBreaker(
    failure_threshold=int(os.getenv("CIRCUIT_BREAKER_FAILURES", "2")),
    recovery_timeout_s=float(os.getenv("CIRCUIT_BREAKER_COOLDOWN_S", "45"))
)


def _retry_secs(resp: httpx.Response) -> float:
    """Read retryDelay from Gemini error body, or Retry-After header."""
    ra = resp.headers.get("Retry-After", "")
    if ra.isdigit():
        return float(ra) + 1
    try:
        body = resp.json()
        items = body if isinstance(body, list) else [body]
        for item in items:
            for detail in item.get("error", {}).get("details", []):
                delay = detail.get("retryDelay", "")
                if delay:
                    return float(delay.rstrip("s")) + 2
    except Exception:
        pass
    return 15.0


def llm_json(prompt: str, schema: dict, name: str, model: str | None = None, fresh: bool = False) -> dict | None:
    """Circuit-broken, rate-aware call to any OpenAI-compatible endpoint.

    - Supports model tiering: passes a lightweight model for simpler tasks.
    - Protects against hangs with an aggressive timeout (default 25s via LLM_TIMEOUT_S).
    - Fails fast in 0ms when the Circuit Breaker is OPEN.
    - Trips the Circuit Breaker after 2 consecutive failures to prevent cascading delays.
    - Transparently falls back to deterministic code generation.
    """
    global _LLM_LAST_CALL_AT
    key = _llm_key()
    if not key: return None

    # Circuit Breaker check: fail fast if upstream model is broken or timing out
    if not _CIRCUIT_BREAKER.allow_request():
        print(f"[CircuitBreaker OPEN] Fast-failing LLM call '{name}' ({_CIRCUIT_BREAKER.last_failure_reason}). Using deterministic fallback.")
        return None

    base = _llm_base()
    target_model = model or os.getenv("OPENAI_MODEL", "qwen/qwen3.8-27b")
    timeout_s = float(os.getenv("LLM_TIMEOUT_S", "180" if _llm_is_local() else "25"))
    min_interval = float(os.getenv("LLM_MIN_INTERVAL_S", "0" if _llm_is_local() else "2"))

    # Response cache: temperature is 0, so an identical (model, prompt, schema) is an exact repeat.
    # Skips the network call, rate-limit sleep and tokens entirely. Off in tests or with LLM_CACHE=0.
    cache_file = None
    if os.getenv("LLM_CACHE", "1") != "0" and not os.getenv("PYTEST_CURRENT_TEST"):
        digest = hashlib.sha256(json.dumps([target_model, name, prompt, schema], sort_keys=True).encode()).hexdigest()
        cache_file = ARTIFACTS_DIR / ".llm_cache" / f"{digest}.json"
        try:
            if not fresh:  # reviewer-requested retries must not replay a cached (failing) answer
                hit = json.loads(cache_file.read_text())
                print(f"[LLM cache hit] '{name}'")
                return hit
        except Exception:
            pass

    # Enforce rate-limit gap (skipped during tests)
    in_test = bool(os.getenv("PYTEST_CURRENT_TEST"))
    if not in_test and min_interval > 0:
        gap = time.perf_counter() - _LLM_LAST_CALL_AT
        if gap < min_interval:
            wait = min_interval - gap
            time.sleep(wait)

    payload = {
        "model": target_model, "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
    }

    # Effort parameter: cap hidden reasoning tokens so structured JSON isn't starved of output budget
    # (Groq returns json_validate_failed with an empty generation otherwise). Override: LLM_REASONING_EFFORT.
    effort = os.getenv("LLM_REASONING_EFFORT", "").strip()
    if not effort and "groq.com" in base:
        effort = "low" if "gpt-oss" in target_model else "none" if "qwen" in target_model else ""
    if effort:
        payload["reasoning_effort"] = effort

    # Explicit output cap: providers estimate OTPM from max_tokens (or the model default), so an
    # unset value can exceed a low tier limit (Groq on_demand: 1000 OTPM) and be rejected with 429.
    max_tokens = os.getenv("LLM_MAX_TOKENS", "").strip() or ("900" if "groq.com" in base else "")
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)

    _LLM_LAST_CALL_AT = time.perf_counter()
    try:
        resp = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"}, timeout=timeout_s, json=payload)

        # Handle rate limits (429) or server overload (503)
        if resp.status_code in (429, 503):
            wait = _retry_secs(resp)
            if wait > 10:
                # If provider demands a long wait (>10s), trip breaker and fail fast rather than stalling
                _CIRCUIT_BREAKER.record_failure(f"HTTP {resp.status_code} quota exceeded (retryDelay={wait:.0f}s)")
                return None
            print(f"[LLM {resp.status_code}] Quick retry in {wait:.0f}s…")
            time.sleep(wait)
            _LLM_LAST_CALL_AT = time.perf_counter()
            resp = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"}, timeout=timeout_s, json=payload)

        # Fallback if provider doesn't support strict json_schema
        if resp.status_code != 200:
            payload["response_format"] = {"type": "json_object"}
            payload["messages"] = [{"role": "user", "content": f"{prompt}\nRespond ONLY with a JSON object matching this schema:\n{json.dumps(schema)}"}]
            resp = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"}, timeout=timeout_s, json=payload)

        if resp.status_code != 200:
            err_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
            print(f"[LLM Error] {err_msg}")
            _CIRCUIT_BREAKER.record_failure(err_msg)
            return None

        content = resp.json()["choices"][0]["message"]["content"]
        content = re.sub(r"^```(?:json)?\s*", "", content.strip())
        content = re.sub(r"\s*```$", "", content)
        parsed = json.loads(content)
        _CIRCUIT_BREAKER.record_success()
        if cache_file is not None:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(parsed))
            except OSError:
                pass
        return parsed

    except (httpx.TimeoutException, TimeoutError) as e:
        print(f"[LLM Timeout] Call timed out after {timeout_s}s: {e}")
        _CIRCUIT_BREAKER.record_failure(f"Timeout after {timeout_s}s")
        return None
    except Exception as e:
        print(f"[LLM Exception]: {e}")
        _CIRCUIT_BREAKER.record_failure(str(e))
        return None


class Trace:
    def __init__(self): self.events = []; self.llm_calls = 0
    def add(self, agent, action, mode, detail, started=None, ok=True, **extra):
        self.events.append({"step": len(self.events) + 1, "agent": agent, "action": action, "mode": mode, "ok": ok, "detail": detail,
                            "ms": round((time.perf_counter() - started) * 1000) if started else 0, **extra})


# ---------------------------------------------------------------- Design Agent
def sample_records(patient_id: str) -> dict[str, list[dict]]:
    """Real records pulled through the connectors; used to design and to test adapters."""
    return {"lis": core.get_lis_results(core.CROSSWALK[patient_id]),
            "his": [hl7_flatten((MOCK_DIR / "his_mock_system/samples/adt_a01.hl7").read_text())],
            "rpm": core.get_rpm_readings()}

def _grounded(system: str, field: str, profiles: dict, records: dict) -> bool:
    """A source field is usable only if discovery saw it and the connector actually returns it."""
    discovered = {f["name"] for f in profiles[system]["discovered_fields"]}
    discovered |= {n.split(".", 1)[1] for n in discovered if system == "lis" and "." in n}
    return field in discovered and any(field in r for r in records[system])

def select_patterns(profiles: dict) -> list[dict]:
    out = []
    for sid, p in profiles.items():
        pattern, why = next(((pt, w) for key, pt, w in PATTERN_RULES if key in p["interface"]), ("Manual review", "Unrecognised interface."))
        out.append({"system": sid, "interface": p["interface"], "pattern": pattern, "rationale": why})
    return out

def design_agent(profiles: dict, records: dict, trace: Trace) -> tuple[list[dict], list[dict], list[dict]]:
    started = time.perf_counter(); patterns = select_patterns(profiles); mode = "deterministic"; proposed = None
    if llm_available():
        item = {"type": "object", "additionalProperties": False, "required": ["source_system", "source_field", "target_path", "transform", "confidence", "rationale", "requires_review"],
                "properties": {"source_system": {"type": "string", "enum": list(TARGETS)}, "source_field": {"type": "string"}, "target_path": {"type": "string"},
                               "transform": {"type": "string", "enum": TRANSFORMS}, "confidence": {"type": "number"}, "rationale": {"type": "string"}, "requires_review": {"type": "boolean"}}}
        pat = {"type": "object", "additionalProperties": False, "required": ["system", "pattern", "rationale"],
               "properties": {"system": {"type": "string", "enum": list(profiles)}, "pattern": {"type": "string"}, "rationale": {"type": "string"}}}
        schema = {"type": "object", "additionalProperties": False, "required": ["patterns", "mappings"],
                  "properties": {"patterns": {"type": "array", "items": pat}, "mappings": {"type": "array", "items": item}}}
        prompt = ("You are a conservative healthcare integration design agent. All data is synthetic.\n"
                  "1) For EVERY system, choose an integration pattern and justify it from the interface.\n"
                  "2) For systems lis, his and rpm, map source fields into the given FHIR-aligned target skeleton.\n"
                  "Rules: source_field must be an exact key of that system's sample record; target_path is a dotted path into the target "
                  "(list indexes as numbers, e.g. name.0.given.0); do not map into values the skeleton already fixes; never invent fields; "
                  "preserve identifier namespaces; set requires_review=true and lower confidence where patient identity cannot be proven "
                  "(RPM has no documented patient crosswalk). Transforms: copy, to_float, title_case, hl7_date_to_iso (YYYYMMDD->YYYY-MM-DD), "
                  "hl7_sex_to_fhir (M/F/O->male/female/other).\n"
                  "Systems: " + json.dumps([{k: p[k] for k in ("system_id", "interface", "capabilities", "limitations")} for p in profiles.values()]) +
                  "\nTargets: " + json.dumps({s: t["base"] for s, t in TARGETS.items()}) +
                  "\nSample records: " + json.dumps({s: r[0] for s, r in records.items() if r}, default=str))
        design_model = os.getenv("OPENAI_MODEL", "qwen/qwen3.8-27b")
        trace.llm_calls += 1; answer = llm_json(prompt, schema, "integration_design", model=design_model)
        if answer:
            proposed, mode = answer["mappings"], "llm"
            by_system = {p["system"]: p for p in answer["patterns"]}
            for p in patterns:
                if p["system"] in by_system: p.update(pattern=by_system[p["system"]]["pattern"], rationale=by_system[p["system"]]["rationale"])
    if proposed is None: proposed = [dict(m) for m in FALLBACK_MAPPINGS]
    trace.add("Design Agent", "Select integration pattern per system", mode, "; ".join(f"{p['system']}: {p['pattern']}" for p in patterns), started)

    # Guardrail: ground every proposal against discovery evidence before it can reach code generation.
    started = time.perf_counter(); accepted, rejected = [], []
    for m in proposed:
        m["confidence"] = max(0.0, min(1.0, float(m["confidence"])))
        reason = None
        if not _grounded(m["source_system"], m["source_field"], profiles, records): reason = "source field not found by discovery"
        elif not re.fullmatch(r"[A-Za-z0-9]+(\.[A-Za-z0-9]+)*", m["target_path"]): reason = "invalid target path"
        elif m["transform"] not in TRANSFORMS: reason = "unknown transform"
        if reason: rejected.append({**m, "rejected_reason": reason})
        else: accepted.append(m)
    for system in TARGETS:  # never leave a system without an executable plan
        if not any(m["source_system"] == system for m in accepted):
            accepted += [dict(m) for m in FALLBACK_MAPPINGS if m["source_system"] == system]
    trace.add("Design Agent", "Propose and ground field mappings", mode,
              f"{len(accepted)} mapping(s) grounded in discovered fields, {len(rejected)} rejected, {sum(m['requires_review'] for m in accepted)} flagged for human review", started)
    return patterns, accepted, rejected


# ---------------------------------------------------------------- Code Generation Agent
HELPERS = '''import json

def _set(out, path, value):
    """Write value at a dotted path; missing or invalid values are omitted, never guessed."""
    if value is None or value == "": return
    keys = path.split("."); cur = out
    for i, key in enumerate(keys[:-1]):
        make = list if keys[i + 1].isdigit() else dict
        if key.isdigit():
            while len(cur) <= int(key): cur.append(make())
            cur = cur[int(key)]
        else:
            cur = cur.setdefault(key, make())
    if keys[-1].isdigit():
        while len(cur) <= int(keys[-1]): cur.append(None)
        cur[int(keys[-1])] = value
    else:
        cur[keys[-1]] = value

def copy(v): return v
def to_float(v):
    try: return float(v)
    except (TypeError, ValueError): return None
def title_case(v): return v.title() if isinstance(v, str) else None
def hl7_date_to_iso(v):
    v = str(v or "")[:8]
    return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if len(v) == 8 and v.isdigit() else None
def hl7_sex_to_fhir(v): return {"M": "male", "F": "female", "O": "other"}.get(str(v or "").upper(), "unknown") if v else None
'''

def template_code(system: str, mappings: list[dict], fault: bool = False) -> str:
    """Deterministic generator: emits an adapter from the approved mapping spec."""
    lines = [f'"""Generated adapter: {system} -> FHIR {TARGETS[system]["resource"]}. Review before use."""', HELPERS,
             f"BASE = {json.dumps(TARGETS[system]['base'])!r}", "", "def transform(record):", "    out = json.loads(BASE)"]
    for m in mappings:
        fn = "copy" if fault and m["transform"] == "hl7_date_to_iso" else m["transform"]
        lines.append(f"    _set(out, {m['target_path']!r}, {fn}(record.get({m['source_field']!r})))")
    return "\n".join(lines + ["    return out", ""])

CODE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["code"], "properties": {"code": {"type": "string"}}}

def llm_code(system: str, mappings: list[dict], sample: dict, previous: str | None = None, failures: list[str] | None = None,
             hint: str = "", fresh: bool = False) -> str | None:
    code_model = os.getenv("OPENAI_MODEL_LIGHT", os.getenv("OPENAI_MODEL", "openai/gpt-oss-20b"))
    # Token optimization: strip verbose descriptions and unmapped fields
    slim_mappings = [{"source": m["source_field"], "target": m["target_path"], "transform": m["transform"]} for m in mappings]
    needed = {m["source_field"] for m in mappings}
    slim_sample = {k: v for k, v in sample.items() if k in needed}
    prompt = (f"Write a standalone Python 3 module defining transform(record: dict) -> dict that converts one {system} record into a FHIR "
              f"{TARGETS[system]['resource']}. Start from this skeleton: {json.dumps(TARGETS[system]['base'])}.\n"
              f"Apply mappings: {json.dumps(slim_mappings)}.\n"
              "Transforms: copy=as is; to_float=float; title_case=str.title(); hl7_date_to_iso=YYYYMMDD->YYYY-MM-DD; hl7_sex_to_fhir=M/F/O->male/female/other.\n"
              "Constraints: import only json, re or datetime; no file/network/eval; use record.get(); omit missing target fields.\n"
              f"Sample input: {json.dumps(slim_sample, default=str)}\n")
    if previous: prompt += f"\nPrevious attempt failed. Fix these errors: {json.dumps(failures)}\nPrevious code:\n{previous}\n"
    if hint: prompt += f"\nReviewer guidance (follow it): {hint[:500]}\n"
    answer = llm_json(prompt, CODE_SCHEMA, "adapter_code", model=code_model, fresh=fresh)
    return answer["code"] if answer and "def transform" in answer.get("code", "") else None


# ---------------------------------------------------------------- Validation Agent
RUNNER = ("import importlib.util, json, sys\n"
          "spec = importlib.util.spec_from_file_location('generated_adapter', sys.argv[1])\n"
          "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n"
          "print(json.dumps([module.transform(r) for r in json.load(sys.stdin)], default=str))\n")
BANNED_NAMES = {"eval", "exec", "open", "compile", "__import__", "globals", "locals", "getattr", "setattr", "delattr", "input", "breakpoint", "vars"}
ALLOWED_IMPORTS = {"json", "re", "datetime"}

def static_check(code: str) -> str | None:
    """Reject generated code that reaches outside pure data transformation. Returns the problem, or None."""
    try: tree = ast.parse(code)
    except SyntaxError as exc: return f"syntax error: {exc.msg} (line {exc.lineno})"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] not in ALLOWED_IMPORTS for a in node.names): return "disallowed import"
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] not in ALLOWED_IMPORTS: return "disallowed import"
        if isinstance(node, ast.Name) and node.id in BANNED_NAMES: return f"disallowed call: {node.id}"
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"): return f"disallowed attribute: {node.attr}"
    return None

def run_sandboxed(code: str, records: list[dict]) -> tuple[list[dict] | None, str]:
    """Execute generated code in a separate isolated interpreter (no site, no env, temp cwd, timeout)."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "adapter.py").write_text(code); (Path(tmp) / "runner.py").write_text(RUNNER)
        try:
            done = subprocess.run([sys.executable, "-I", "runner.py", "adapter.py"], input=json.dumps(records, default=str), capture_output=True,
                                  text=True, timeout=10, cwd=tmp, env={})
        except subprocess.TimeoutExpired:
            return None, "timed out after 10s"
        if done.returncode != 0: return None, (done.stderr.strip().splitlines() or ["non-zero exit"])[-1]
        try: return json.loads(done.stdout), ""
        except ValueError: return None, "adapter did not return JSON"

def _reference(transform: str, value):
    """Independent expected value, computed outside the generated code."""
    if value is None or value == "": return None
    try:
        if transform == "to_float": return float(value)
        if transform == "title_case": return str(value).title()
        if transform == "hl7_date_to_iso":
            v = str(value)[:8]; return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if len(v) == 8 and v.isdigit() else None
        if transform == "hl7_sex_to_fhir": return {"M": "male", "F": "female", "O": "other"}.get(str(value).upper(), "unknown")
    except (TypeError, ValueError): return None
    return value

def _get(obj, path: str):
    for key in path.split("."):
        try: obj = obj[int(key)] if key.isdigit() else obj[key]
        except (KeyError, IndexError, TypeError): return None
    return obj

def validation_agent(system: str, code: str, mappings: list[dict], records: list[dict]) -> dict:
    checks = []
    def check(name, passed, detail): checks.append({"name": name, "passed": bool(passed), "detail": detail})
    problem = static_check(code)
    check("Static safety scan", problem is None, problem or "Only whitelisted imports; no file, network or dynamic-execution access.")
    if problem: return _report(system, checks)
    bad = {m["source_field"]: "??" for m in mappings if m["transform"] in ("to_float", "hl7_date_to_iso")}
    outputs, error = run_sandboxed(code, records + [bad, {}])
    check("Runs in isolated sandbox", outputs is not None, error or f"Transformed {len(records)} real record(s) plus malformed and empty records without error.")
    if outputs is None: return _report(system, checks)
    good, malformed = outputs[:len(records)], outputs[len(records)]
    wanted = TARGETS[system]["resource"]
    check("Contract: resourceType", all(isinstance(o, dict) and o.get("resourceType") == wanted for o in outputs), f"Every output is a FHIR {wanted}.")
    matched = total = 0; wrong = []
    for record, out in zip(records, good):
        for m in mappings:
            expected = _reference(m["transform"], record.get(m["source_field"])); total += 1
            if _get(out, m["target_path"]) == expected: matched += 1
            elif f"{m['source_field']} -> {m['target_path']}" not in wrong:
                wrong.append(f"{m['source_field']} -> {m['target_path']} (expected {expected!r}, got {_get(out, m['target_path'])!r})")
    check("Field reconciliation against source", matched == total, f"{matched}/{total} field values match the source." + (" Mismatch: " + "; ".join(wrong) if wrong else ""))
    leaked = [m["target_path"] for m in mappings if m["source_field"] in bad and _get(malformed, m["target_path"]) is not None]
    check("Malformed input is rejected, not passed through", not leaked, "Invalid numbers/dates are omitted from the output." if not leaked else "Bad value reached: " + ", ".join(leaked))
    report = _report(system, checks); report.update(records_tested=len(records), field_values_matched=matched, field_values_total=total)
    return report

def _report(system, checks):
    return {"system": system, "passed": all(c["passed"] for c in checks), "checks": checks,
            "summary": f"{sum(c['passed'] for c in checks)}/{len(checks)} checks passed"}


# ---------------------------------------------------------------- Orchestrator
def run_agentic(patient_id: str = "ehr-pat-001", inject_fault: bool = False) -> dict:
    _CIRCUIT_BREAKER.reset()  # Start each run with a fresh circuit state
    began = time.perf_counter(); trace = Trace()
    if patient_id not in core.CROSSWALK: raise ValueError("No documented synthetic EHR↔LIS crosswalk for this patient.")

    started = time.perf_counter(); profile_models = core.discover(); profiles = {p.system_id: p.model_dump() for p in profile_models}
    for p in profiles.values():
        trace.add("Discovery Agent", f"Inspect {p['name']}", p["discovery_mode"], f"{p['interface']}: {len(p['discovered_fields'])} field(s) from {p['evidence'][0]}")
    trace.events[len(profiles) - 1]["ms"] = round((time.perf_counter() - started) * 1000)

    records = sample_records(patient_id)
    patterns, mappings, rejected = design_agent(profiles, records, trace)

    adapters = {}; reports = []; repairs = 0
    for system in TARGETS:
        spec = [m for m in mappings if m["source_system"] == system]; code = None; report = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.perf_counter()
            if attempt == 1:
                if inject_fault and system == "his": code, mode = template_code(system, spec, fault=True), "fault_injected"
                else:
                    code = llm_code(system, spec, records[system][0]) if llm_available() else None
                    trace.llm_calls += llm_available(); mode = "llm" if code else "deterministic"
                    code = code or template_code(system, spec)
                trace.add("Code Generation Agent", f"Generate {system} → {TARGETS[system]['resource']} adapter", mode,
                          f"{len(code.splitlines())} lines from {len(spec)} mapping(s)" + (" — deliberate defect injected for the demo (date left in HL7 format)" if mode == "fault_injected" else ""), started)
            else:
                repairs += 1; failures = [f"{c['name']}: {c['detail']}" for c in report["checks"] if not c["passed"]]
                fixed = llm_code(system, spec, records[system][0], code, failures) if llm_available() and attempt < MAX_ATTEMPTS else None
                trace.llm_calls += bool(llm_available() and attempt < MAX_ATTEMPTS); mode = "llm" if fixed else "deterministic"
                code = fixed or template_code(system, spec)
                trace.add("Code Generation Agent", f"Repair {system} adapter (attempt {attempt})", mode, "Regenerated using the validation failures as feedback: " + " | ".join(failures)[:300], started)
            started = time.perf_counter(); report = validation_agent(system, code, spec, records[system]); report["attempts"] = attempt
            trace.add("Validation Agent", f"Test {system} adapter in sandbox", "sandbox", report["summary"] + ("" if report["passed"] else " — " + next(c["detail"] for c in report["checks"] if not c["passed"])[:220]), started, ok=report["passed"])
            if report["passed"]: break
        adapters[system] = code; reports.append(report)

    # Assemble the unified patient context with the existing connectors and identity checks.
    result = core.run_workflow(patient_id, use_llm=False)
    design_mode = next(e["mode"] for e in trace.events if e["action"].startswith("Propose"))
    result["plan"].update(mappings=mappings, rejected_mappings=rejected, patterns=patterns, mapping_mode="llm_structured" if design_mode == "llm" else "deterministic_fallback")
    agents_ok = all(r["passed"] for r in reports)
    result["agent_validation"] = reports
    result["validation"]["passed"] = result["validation"]["passed"] and agents_ok
    if not result["validation"]["passed"]: result["status"] = "needs_correction" if not agents_ok else "validation_failed"
    result["audit"] = []
    trace.add("Orchestrator", "Stop at human approval gate", "policy", "Adapters validated; nothing is released until a reviewer approves the mappings and then the release." if agents_ok else "Validation failed; approval is blocked until a reviewer retries, edits or replaces the failing adapter.", ok=agents_ok)

    out = ARTIFACTS_DIR / result["run_id"]; (out / "adapters").mkdir(parents=True, exist_ok=True)
    for system, code in adapters.items(): (out / "adapters" / f"{system}_adapter.py").write_text(code)
    (out / "integration-plan.json").write_text(json.dumps(result["plan"], indent=2))
    (out / "agent-trace.json").write_text(json.dumps(trace.events, indent=2))
    (out / "validation-report.json").write_text(json.dumps(reports, indent=2))
    tests = [c for r in reports for c in r["checks"]]
    result.update(
        pipeline="agentic", profiles=list(profiles.values()), trace=trace.events, adapters=adapters,
        generated_artifacts=sorted(str(x) for x in out.rglob("*") if x.is_file()),
        metrics={"elapsed_seconds": round(time.perf_counter() - began, 2), "systems_discovered": len(profiles),
                 "fields_discovered": sum(len(p["discovered_fields"]) for p in profiles.values()),
                 "mappings_grounded": len(mappings), "mappings_rejected": len(rejected),
                 "mappings_flagged_for_review": sum(m["requires_review"] for m in mappings),
                 "adapters_generated": len(adapters), "checks_passed": sum(c["passed"] for c in tests), "checks_total": len(tests),
                 "field_values_reconciled": f"{sum(r.get('field_values_matched', 0) for r in reports)}/{sum(r.get('field_values_total', 0) for r in reports)}",
                 "repair_attempts": repairs, "llm_calls": trace.llm_calls,
                 "circuit_breaker": _CIRCUIT_BREAKER.state,
                 "circuit_breaker_tripped": _CIRCUIT_BREAKER.state == "OPEN",
                 "llm_model": f"{os.getenv('OPENAI_MODEL', 'qwen/qwen3.8-27b')} + {os.getenv('OPENAI_MODEL_LIGHT', 'openai/gpt-oss-20b')}" if llm_available() else None,
                 "mode": "llm-assisted" if (llm_available() and _CIRCUIT_BREAKER.state != "OPEN") else "deterministic"})
    return result


# ---------------------------------------------------------------- Reviewer-driven correction
def audit(run: dict, actor: str, action: str, detail: str = ""):
    run.setdefault("audit", []).append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "actor": actor, "action": action, "detail": detail})

def refresh_run(run: dict, trace: Trace) -> dict:
    """Recompute validation state, status, metrics and artefacts after any adapter change. Approvals are reset."""
    reports = run["agent_validation"]; agents_ok = all(r["passed"] for r in reports)
    identity_ok = all(c["passed"] for c in run["validation"]["checks"])
    run["validation"]["passed"] = agents_ok and identity_ok
    run["approvals"] = {"mapping_approved": False, "release_approved": False}
    run["status"] = "awaiting_human_approval" if run["validation"]["passed"] else ("needs_correction" if not agents_ok else "validation_failed")
    tests = [c for r in reports for c in r["checks"]]
    run["trace"] = trace.events
    run["metrics"].update(checks_passed=sum(c["passed"] for c in tests), checks_total=len(tests), llm_calls=trace.llm_calls,
        field_values_reconciled=f"{sum(r.get('field_values_matched', 0) for r in reports)}/{sum(r.get('field_values_total', 0) for r in reports)}")
    out = ARTIFACTS_DIR / run["run_id"]; (out / "adapters").mkdir(parents=True, exist_ok=True)
    for system, code in run["adapters"].items(): (out / "adapters" / f"{system}_adapter.py").write_text(code)
    (out / "agent-trace.json").write_text(json.dumps(trace.events, indent=2))
    (out / "validation-report.json").write_text(json.dumps(reports, indent=2))
    return run

def _revalidate(run: dict, system: str, code: str, trace: Trace, started: float) -> dict:
    spec = [m for m in run["plan"]["mappings"] if m["source_system"] == system]
    records = sample_records(run["patient_key"])[system]
    old = next(r for r in run["agent_validation"] if r["system"] == system)
    report = validation_agent(system, code, spec, records); report["attempts"] = old.get("attempts", 1) + 1
    trace.add("Validation Agent", f"Re-test {system} adapter in sandbox", "sandbox", report["summary"] + ("" if report["passed"] else " — " + next(c["detail"] for c in report["checks"] if not c["passed"])[:220]), started, ok=report["passed"])
    run["adapters"][system] = code
    run["agent_validation"] = [report if r["system"] == system else r for r in run["agent_validation"]]
    return report

def _trace_of(run: dict) -> Trace:
    t = Trace(); t.events = list(run["trace"]); t.llm_calls = run["metrics"].get("llm_calls", 0); return t

def retry_adapter(run: dict, system: str, strategy: str = "template", hint: str = "") -> dict:
    """Reviewer asks for another attempt: 'ai' re-prompts the model with the failures (and optional guidance, bypassing the cache);
    'template' regenerates from the approved mappings deterministically. Tests re-run and approvals reset either way."""
    if system not in run["adapters"]: raise KeyError(system)
    trace = _trace_of(run); spec = [m for m in run["plan"]["mappings"] if m["source_system"] == system]
    old = next(r for r in run["agent_validation"] if r["system"] == system)
    failures = [f"{c['name']}: {c['detail']}" for c in old["checks"] if not c["passed"]]
    started = time.perf_counter(); fixed = None
    if strategy == "ai" and llm_available():
        _CIRCUIT_BREAKER.reset()  # an explicit reviewer request overrides a previously tripped breaker
        fixed = llm_code(system, spec, sample_records(run["patient_key"])[system][0], run["adapters"][system], failures, hint=hint, fresh=True)
        trace.llm_calls += 1
    code = fixed or template_code(system, spec); mode = "llm" if fixed else "deterministic"
    note = "" if (fixed or strategy != "ai") else " (AI unavailable or returned nothing; used the deterministic template)"
    trace.add("Code Generation Agent", f"Reviewer-requested retry of {system} adapter", mode, ("Guidance: " + hint[:120] + " | " if hint else "") + "Regenerated from failures: " + " | ".join(failures)[:200] + note, started)
    started = time.perf_counter(); report = _revalidate(run, system, code, trace, started)
    audit(run, "reviewer", f"retry_{strategy}", f"{system}: {'passed' if report['passed'] else 'still failing'}" + (f" — {hint[:120]}" if hint else ""))
    return refresh_run(run, trace)

def submit_adapter_code(run: dict, system: str, code: str) -> dict:
    """Reviewer supplies hand-edited adapter code. It goes through the same static scan, sandbox and reconciliation as generated code."""
    if system not in run["adapters"]: raise KeyError(system)
    trace = _trace_of(run); started = time.perf_counter()
    trace.add("Reviewer", f"Submitted manual edit of {system} adapter", "human", f"{len(code.splitlines())} lines", started)
    started = time.perf_counter(); report = _revalidate(run, system, code, trace, started)
    audit(run, "reviewer", "manual_edit", f"{system}: {'passed' if report['passed'] else 'still failing'}")
    return refresh_run(run, trace)
