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
import ast, json, os, re, subprocess, sys, tempfile, time
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
def llm_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())

def llm_json(prompt: str, schema: dict, name: str) -> dict | None:
    """One schema-constrained call to an OpenAI-compatible endpoint. Returns None on any failure."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key: return None
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    try:
        response = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"}, timeout=40, json={
            "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}})
        response.raise_for_status()
        return json.loads(response.json()["choices"][0]["message"]["content"])
    except Exception:
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
        trace.llm_calls += 1; answer = llm_json(prompt, schema, "integration_design")
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

def llm_code(system: str, mappings: list[dict], sample: dict, previous: str | None = None, failures: list[str] | None = None) -> str | None:
    prompt = (f"Write a standalone Python 3 module defining transform(record: dict) -> dict that converts one {system} record into a FHIR "
              f"{TARGETS[system]['resource']}. Start from this skeleton and keep its fixed values: {json.dumps(TARGETS[system]['base'])}.\n"
              f"Apply exactly these mappings (target_path is dotted, numbers are list indexes): {json.dumps(mappings)}.\n"
              "Transform semantics: copy=as is; to_float=float; title_case=str.title(); hl7_date_to_iso=YYYYMMDD->YYYY-MM-DD; "
              "hl7_sex_to_fhir=M/F/O->male/female/other.\n"
              "Constraints: import only json, re or datetime; no file, network, eval or exec; read fields with record.get(); if a source "
              "value is missing or malformed, omit that target field entirely instead of raising or passing the bad value through.\n"
              f"Sample record: {json.dumps(sample, default=str)}\n")
    if previous: prompt += f"\nYour previous attempt failed validation. Fix it.\nFailures: {json.dumps(failures)}\nPrevious code:\n{previous}\n"
    answer = llm_json(prompt, CODE_SCHEMA, "adapter_code")
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
    if not result["validation"]["passed"]: result["status"] = "validation_failed"
    trace.add("Orchestrator", "Stop at human approval gate", "policy", "Adapters validated; nothing is released until a reviewer approves the mappings and then the release." if agents_ok else "Validation failed; approval is blocked.", ok=agents_ok)

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
                 "llm_model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini") if llm_available() else None,
                 "mode": "llm-assisted" if llm_available() else "deterministic (no LLM key configured)"})
    return result
