"""Discovery Agent tools: inspect each mock system and build its profile from real evidence.

Every profile is derived from a live endpoint when one answers, otherwise from the
artefacts the system ships with (seed JSON, SQL DDL, HL7 samples, JSONL telemetry).
Nothing here is a hand-written field list.
"""
from __future__ import annotations
import json, os, re, socket
from typing import Any
import httpx
from .config import MOCK_DIR

HL7_FIELD_NAMES = {
    "MSH-9": "Message type", "MSH-10": "Message control ID", "MSH-12": "HL7 version",
    "PID-3": "Patient identifier list (CX)", "PID-5": "Patient name (XPN)",
    "PID-7": "Date of birth (TS)", "PID-8": "Administrative sex",
    "PV1-2": "Patient class", "PV1-3": "Assigned location",
    "ORC-1": "Order control", "ORC-2": "Placer order number",
    "OBR-2": "Placer order number", "OBR-4": "Universal service ID",
    "OBX-2": "Value type", "OBX-3": "Observation identifier", "OBX-5": "Observation value",
    "OBX-6": "Units", "OBX-7": "Reference range", "OBX-8": "Abnormal flag",
}


def _flatten(obj: Any, prefix: str = ""):
    """Yield (path, type, sample) for every leaf of a JSON document."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _flatten(value, f"{prefix}.{key}" if prefix else key)
    elif isinstance(obj, list):
        if obj: yield from _flatten(obj[0], prefix + "[]")
    else:
        yield prefix, type(obj).__name__, obj


def hl7_flatten(text: str) -> dict[str, str]:
    """Flatten one HL7 v2 message into {"PID-3.1": "...", "PID-7": "..."} (first occurrence wins)."""
    out: dict[str, str] = {}
    for segment in [s for s in re.split(r"[\r\n]+", text) if s.strip()]:
        fields = segment.split("|"); seg = fields[0]
        offset = 1 if seg == "MSH" else 0  # MSH-1 is the field separator itself
        for index, value in enumerate(fields[1:], start=1):
            if not value: continue
            position = f"{seg}-{index + offset}"
            if seg == "MSH" and index == 1: continue  # encoding characters
            if "^" in value:
                for c, component in enumerate(value.split("^"), start=1):
                    if component: out.setdefault(f"{position}.{c}", component)
            else:
                out.setdefault(position, value)
    return out


def _discover_ehr() -> dict:
    base = os.getenv("EHR_BASE_URL", "http://localhost:8000")
    seed = json.loads((MOCK_DIR / "ehr_mock/app/data/seed.json").read_text())
    mode, evidence, capabilities, version = "offline_artefact", ["ehr_mock/app/data/seed.json"], list(seed), "R4-style"
    try:
        meta = httpx.get(f"{base}/metadata", timeout=1.5); meta.raise_for_status(); meta = meta.json()
        capabilities = [r["type"] for r in meta["rest"][0]["resource"]]
        version = meta.get("fhirVersion", version)
        mode, evidence = "live", [f"GET {base}/metadata (CapabilityStatement)"] + evidence
    except Exception:
        pass
    fields = []
    for resource, records in seed.items():
        if records:
            fields += [{"name": f"{resource}.{path}", "type": kind, "sample": sample} for path, kind, sample in _flatten(records[0])]
    return dict(system_id="ehr", name="Mock EHR", interface=f"FHIR {version} REST/JSON", connectivity=f"HTTP {base} /metadata and /fhir/*",
                capabilities=capabilities, discovered_fields=fields, evidence=evidence, discovery_mode=mode,
                limitations=["Limited FHIR subset; read-only; not certified"])


def _parse_ddl(sql: str) -> tuple[list[dict], list[str]]:
    fields, tables = [], []
    for table, body in re.findall(r"CREATE TABLE (\w+)\s*\((.*?)\n\);", sql, re.S | re.I):
        tables.append(table)
        for line in [x.strip().rstrip(",") for x in body.splitlines() if x.strip()]:
            if re.match(r"(CHECK|FOREIGN KEY|PRIMARY KEY|UNIQUE|CONSTRAINT)\b", line, re.I): continue
            match = re.match(r"(\w+)\s+([A-Z]+(?:\(\d+(?:,\d+)?\))?)", line)
            if not match: continue
            ref = re.search(r"REFERENCES (\w+)\((\w+)\)", line, re.I)
            fields.append({"name": f"{table}.{match.group(1)}", "type": match.group(2).lower(),
                           "required": bool(re.search(r"NOT NULL|PRIMARY KEY", line, re.I)),
                           "primary_key": "PRIMARY KEY" in line.upper(),
                           **({"references": f"{ref.group(1)}.{ref.group(2)}"} if ref else {})})
    return fields, tables + [f"view:{v}" for v in re.findall(r"CREATE VIEW (\w+)", sql, re.I)]


def _discover_lis() -> dict:
    dsn = os.getenv("LIS_DSN", "")
    mode, evidence = "offline_artefact", ["lis_mock_system/db/init/001_schema.sql"]
    fields, capabilities = _parse_ddl((MOCK_DIR / "lis_mock_system/db/init/001_schema.sql").read_text())
    if dsn:
        try:
            import psycopg
            with psycopg.connect(dsn, connect_timeout=2) as conn, conn.cursor() as cur:
                cur.execute("""SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns
                               WHERE table_schema='public' ORDER BY table_name, ordinal_position""")
                live = [{"name": f"{t}.{c}", "type": d, "required": n == "NO"} for t, c, d, n in cur.fetchall()]
            if live:
                fields, mode = live, "live"
                capabilities = sorted({f["name"].split(".")[0] for f in live})
                evidence = ["information_schema.columns (live PostgreSQL)"] + evidence
        except Exception:
            pass
    return dict(system_id="lis", name="Mock LIS", interface="PostgreSQL relational SQL", connectivity="PostgreSQL :5433; v_lab_results_detail",
                capabilities=capabilities, discovered_fields=fields, evidence=evidence, discovery_mode=mode,
                limitations=["Direct DB access is a mock-only adapter"])


def _discover_his() -> dict:
    host, port = os.getenv("HIS_HOST", "localhost"), int(os.getenv("HIS_PORT", "2575"))
    seen: dict[str, str] = {}; messages = []; evidence = []
    for path in sorted((MOCK_DIR / "his_mock_system/samples").glob("*.hl7")):
        flat = hl7_flatten(path.read_text()); evidence.append(f"his_mock_system/samples/{path.name}")
        if "MSH-9.1" in flat: messages.append(f"{flat['MSH-9.1']}^{flat.get('MSH-9.2', '')}")
        for key, value in flat.items(): seen.setdefault(key, value)
    fields = [{"name": key, "type": HL7_FIELD_NAMES.get(key.split(".")[0], "HL7 field"), "sample": value} for key, value in seen.items()]
    mode = "offline_artefact"
    try:
        socket.create_connection((host, port), timeout=1).close(); mode = "live"; evidence.insert(0, f"MLLP listener reachable at {host}:{port}")
    except Exception:
        pass
    return dict(system_id="his", name="Mock HIS", interface=f"HL7 v{seen.get('MSH-12', '2.x')} over MLLP/TCP", connectivity=f"TCP {host}:{port}",
                capabilities=sorted(set(messages)) + ["ACK"], discovered_fields=fields, evidence=evidence, discovery_mode=mode,
                limitations=["Limited message support; not a full HL7 engine"])


def _discover_pacs() -> dict:
    base = os.getenv("PACS_BASE_URL", "http://localhost:8042")
    auth = (os.getenv("PACS_USERNAME", "pacs_user"), os.getenv("PACS_PASSWORD", "pacs_dev_password_change_me"))
    readme = (MOCK_DIR / "pacs_mock_system/README.md").read_text()
    fields = [{"name": name, "tag": tag, "type": "DICOM tag"} for name, tag in re.findall(r"-\s+(\w+)\s+`\((\w{4},\w{4})\)`", readme)]
    mode, evidence, limitations = "offline_artefact", ["pacs_mock_system/README.md (documented DICOM tags)"], ["Synthetic image pixels; service may be empty"]
    try:
        with httpx.Client(timeout=1.5, auth=auth) as client:
            system = client.get(base + "/system"); system.raise_for_status()
            studies = client.get(base + "/studies").json()
            mode = "live"; evidence.insert(0, f"GET {base}/system (Orthanc {system.json().get('Version', '?')}); {len(studies)} study(ies)")
            if studies:
                detail = client.get(f"{base}/studies/{studies[0]}").json()
                tags = {**detail.get("MainDicomTags", {}), **detail.get("PatientMainDicomTags", {})}
                known = {f["name"] for f in fields}
                fields += [{"name": k, "type": "DICOM tag", "sample": v} for k, v in tags.items() if k not in known]
    except Exception:
        pass
    return dict(system_id="pacs", name="Mock PACS", interface="Orthanc REST + DICOM/DICOMweb", connectivity=f"HTTP {base}; DICOM :4242",
                capabilities=["studies", "series", "instances", "DICOM metadata"], discovered_fields=fields, evidence=evidence,
                discovery_mode=mode, limitations=limitations)


def _discover_rpm() -> dict:
    path = MOCK_DIR / "rpm_mock_system/samples/vitals.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    fields = []
    for key in rows[0] if rows else []:
        values = [r[key] for r in rows if key in r]
        field = {"name": key, "type": type(values[0]).__name__, "sample": values[0], "required": len(values) == len(rows)}
        if all(isinstance(v, (int, float)) for v in values): field["observed_range"] = [min(values), max(values)]
        fields.append(field)
    return dict(system_id="rpm", name="Mock RPM", interface="MQTT 3.1.1 + JSON", connectivity="Mosquitto :1883; exl/rpm/{device_id}/vitals",
                capabilities=[f["name"] for f in fields if "observed_range" in f], discovered_fields=fields,
                evidence=[f"rpm_mock_system/samples/vitals.jsonl ({len(rows)} readings)"], discovery_mode="offline_artefact",
                limitations=["No documented crosswalk for sample RPM patient IDs"])


def discover_profiles() -> list[dict]:
    return [_discover_ehr(), _discover_lis(), _discover_his(), _discover_pacs(), _discover_rpm()]
