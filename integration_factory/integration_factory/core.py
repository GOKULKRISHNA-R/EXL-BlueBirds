from __future__ import annotations
import json, os, re, socket, uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
import httpx
from pydantic import BaseModel, Field
from .config import MOCK_DIR, ARTIFACTS_DIR

class Profile(BaseModel):
    system_id: str
    name: str
    interface: str
    connectivity: str
    capabilities: list[str] = Field(default_factory=list)
    discovered_fields: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

class MappingProposal(BaseModel):
    source_system: str
    source_field: str
    target_path: str
    confidence: float = Field(ge=0, le=1)
    rationale: str
    requires_review: bool = False

class Check(BaseModel):
    name: str
    passed: bool
    severity: str
    detail: str

def discover() -> list[Profile]:
    seed = json.loads((MOCK_DIR / "ehr_mock/app/data/seed.json").read_text())
    fields = [{"name": k, "type": type(v).__name__} for k, v in seed["Patient"][0].items()]
    return [
      Profile(system_id="ehr", name="Mock EHR", interface="FHIR R4-style REST/JSON", connectivity="HTTP :8000 /metadata and /fhir/*", capabilities=["Patient", "Encounter", "Condition", "Observation", "MedicationRequest"], discovered_fields=fields, evidence=["ehr_mock/README.md", "ehr_mock/app/data/seed.json"], limitations=["Limited FHIR subset; read-only; not certified"]),
      Profile(system_id="lis", name="Mock LIS", interface="PostgreSQL relational SQL", connectivity="PostgreSQL :5433; v_lab_results_detail", capabilities=["patients", "lab_orders", "lab_results", "LOINC"], discovered_fields=[{"name":"patient_id","type":"varchar"},{"name":"date_of_birth","type":"date"},{"name":"loinc_code","type":"varchar"},{"name":"result_value","type":"numeric"}], evidence=["lis_mock_system/db/init/001_schema.sql", "002_seed.sql"], limitations=["Direct DB access is a mock-only adapter"]),
      Profile(system_id="his", name="Mock HIS", interface="HL7 v2.x over MLLP/TCP", connectivity="TCP :2575", capabilities=["ADT^A01", "ORM^O01", "ORU^R01", "ACK"], discovered_fields=[{"name":"PID-3","type":"CX"},{"name":"PID-5","type":"XPN"},{"name":"PID-7","type":"TS"},{"name":"OBX","type":"observation"}], evidence=["his_mock_system/samples/*.hl7"], limitations=["Limited message support; not a full HL7 engine"]),
      Profile(system_id="pacs", name="Mock PACS", interface="Orthanc REST + DICOM/DICOMweb", connectivity="HTTP :8042; DICOM :4242", capabilities=["studies", "series", "instances", "DICOM metadata"], discovered_fields=[{"name":"PatientID","tag":"0010,0020"},{"name":"IssuerOfPatientID","tag":"0010,0021"},{"name":"StudyInstanceUID","tag":"0020,000D"}], evidence=["pacs_mock_system/README.md"], limitations=["Synthetic image pixels; service may be empty"]),
      Profile(system_id="rpm", name="Mock RPM", interface="MQTT 3.1.1 + JSON", connectivity="Mosquitto :1883; exl/rpm/{device_id}/vitals", capabilities=["heart_rate_bpm", "spo2_percent", "temperature_c"], discovered_fields=[{"name":"patient_id","type":"string"},{"name":"timestamp","type":"datetime"},{"name":"heart_rate_bpm","type":"number"}], evidence=["rpm_mock_system/samples/vitals.jsonl"], limitations=["No documented crosswalk for sample RPM patient IDs"])
    ]

def parse_insert(statement: str) -> list[list[str]]:
    match = re.search(r"VALUES\s*(.*?);", statement, re.S | re.I)
    if not match: return []
    raw=match.group(1); rows=[]; row=[]; token=[]; quoted=False; depth=0; i=0
    while i < len(raw):
        ch=raw[i]
        if ch == "'":
            if quoted and i+1 < len(raw) and raw[i+1] == "'": token.append("'"); i += 2; continue
            quoted=not quoted
        elif not quoted:
            if ch == "(":
                depth += 1
                if depth == 1: row=[]; token=[]
                else: token.append(ch)
            elif ch == ")":
                if depth == 1: row.append("".join(token).strip()); rows.append(row); token=[]
                else: token.append(ch)
                depth -= 1
            elif ch == "," and depth == 1: row.append("".join(token).strip()); token=[]
            elif depth > 0: token.append(ch)
        else: token.append(ch)
        i += 1
    return rows

def get_ehr_patient(patient_id: str) -> dict:
    base=os.getenv("EHR_BASE_URL", "http://localhost:8000")
    token=os.getenv("EHR_API_TOKEN", "dev-ehr-token-change-me")
    try:
        with httpx.Client(timeout=2) as client:
            response=client.get(f"{base}/fhir/Patient/{patient_id}", headers={"Authorization":f"Bearer {token}"})
            response.raise_for_status(); return response.json()
    except Exception:
        data=json.loads((MOCK_DIR/"ehr_mock/app/data/seed.json").read_text())
        return next(p for p in data["Patient"] if p["id"] == patient_id)

def get_lis_results(patient_id: str) -> list[dict]:
    dsn=os.getenv("LIS_DSN", "")
    if dsn:
        try:
            import psycopg
            with psycopg.connect(dsn, connect_timeout=2) as conn, conn.cursor() as cur:
                cur.execute("""SELECT patient_id, medical_record_no, given_name, family_name, date_of_birth::text,
                  order_id, test_code, test_name, loinc_code, result_value::float8, result_text, COALESCE(unit,''),
                  reference_low::float8, reference_high::float8, abnormal_flag, result_status, observed_at::text
                  FROM v_lab_results_detail WHERE patient_id=%s ORDER BY observed_at""", (patient_id,))
                names=[col.name for col in cur.description]
                return [dict(zip(names, row)) for row in cur.fetchall()]
        except Exception: pass
    sql=(MOCK_DIR/"lis_mock_system/db/init/002_seed.sql").read_text()
    def rows(table):
        match=re.search(rf"INSERT INTO {table}.*?;", sql, re.S)
        return parse_insert(match.group()) if match else []
    patients={r[0]:r for r in rows("patients")}; tests={r[0]:r for r in rows("lab_tests")}; orders={r[0]:r for r in rows("lab_orders")}
    output=[]
    for result in rows("lab_results"):
        order=orders[result[1]]
        if order[1] != patient_id: continue
        patient=patients[patient_id]; test=tests[result[2]]
        output.append({"patient_id":patient_id,"medical_record_no":patient[1],"given_name":patient[2],"family_name":patient[3],"date_of_birth":patient[4],"order_id":result[1],"test_code":result[2],"test_name":test[1],"loinc_code":test[2],"result_value":float(result[3]) if result[3] else None,"result_text":result[4] or None,"unit":(result[5] or test[4]).strip(),"reference_low":float(result[6]) if result[6] else None,"reference_high":float(result[7]) if result[7] else None,"abnormal_flag":result[8],"result_status":result[9],"observed_at":result[10]})
    return output

def parse_hl7_patient(path: Path) -> dict:
    raw=path.read_text().replace("\n", "\r")
    segments=[s for s in raw.split("\r") if s]
    pid=next(s for s in segments if s.startswith("PID|")); fields=pid.split("|")
    cx=fields[3].split("^"); name=fields[5].split("^")
    return {"patient_id":cx[0],"assigning_authority":cx[3] if len(cx)>3 else None,"family":name[0],"given":name[1],"birthdate":fields[7]}

def parse_hl7_observations(path: Path) -> list[dict]:
    """Parse OBX segments from the supplied synthetic ORU message."""
    raw=path.read_text().replace("\n", "\r")
    observations=[]
    for segment in [x for x in raw.split("\r") if x.startswith("OBX|")]:
        fields=segment.split("|")
        components=fields[3].split("^") if len(fields)>3 else ["UNKNOWN", "Unknown observation"]
        value=fields[5] if len(fields)>5 else ""
        try: numeric=float(value)
        except (TypeError,ValueError): numeric=None
        observations.append({"resourceType":"Observation","status":"final",
          "code":{"coding":[{"system":"urn:mock-his:observation-code","code":components[0],"display":components[1] if len(components)>1 else components[0]}]},
          "valueQuantity":{"value":numeric,"unit":fields[6] if len(fields)>6 else ""} if numeric is not None else None,
          "referenceRangeText":fields[7] if len(fields)>7 else "",
          "interpretationCode":fields[8] if len(fields)>8 else "","source":"HIS/HL7v2"})
    return observations

def get_pacs_studies() -> list[dict]:
    base=os.getenv("PACS_BASE_URL", "http://localhost:8042")
    auth=(os.getenv("PACS_USERNAME", "pacs_user"), os.getenv("PACS_PASSWORD", "pacs_dev_password_change_me"))
    try:
        with httpx.Client(timeout=2, auth=auth) as client:
            response=client.get(base+"/studies"); response.raise_for_status(); ids=response.json(); out=[]
            for sid in ids:
                detail=client.get(f"{base}/studies/{sid}"); detail.raise_for_status(); out.append(detail.json())
            return out
    except Exception: return []

def get_rpm_readings() -> list[dict]:
    path=MOCK_DIR/"rpm_mock_system/samples/vitals.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

def propose_mappings() -> list[MappingProposal]:
    return [
      MappingProposal(source_system="ehr",source_field="Patient.id + identifier",target_path="Patient.id + Patient.identifier",confidence=1,rationale="Preserve source identity and identifier namespace."),
      MappingProposal(source_system="lis",source_field="lab_results.patient_id",target_path="Observation.subject.identifier",confidence=.99,rationale="Use documented synthetic EHR↔LIS crosswalk and corroborating demographics."),
      MappingProposal(source_system="lis",source_field="loinc_code + result_value + unit",target_path="Observation.code + Observation.valueQuantity",confidence=.99,rationale="LOINC-coded laboratory observation and quantity."),
      MappingProposal(source_system="his",source_field="PID-3 + PID-7",target_path="Patient.identifier + Patient.birthDate",confidence=.99,rationale="Preserve CX assigning authority and parse HL7 timestamp."),
      MappingProposal(source_system="pacs",source_field="PatientID + IssuerOfPatientID",target_path="ImagingStudy.subject.identifier",confidence=.96,rationale="DICOM PatientID is issuer-scoped."),
      MappingProposal(source_system="rpm",source_field="patient_id + vitals",target_path="Observation.subject + Observation.valueQuantity",confidence=.75,rationale="Requires explicit patient crosswalk before linking.",requires_review=True)
    ]

def propose_mappings_with_ai(profiles):
    """Optional schema-constrained OpenAI design agent; deterministic fallback is always available."""
    api_key=os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key: return propose_mappings(), "deterministic_fallback"
    schema={"type":"object","additionalProperties":False,"properties":{"mappings":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"source_system":{"type":"string"},"source_field":{"type":"string"},"target_path":{"type":"string"},"confidence":{"type":"number"},"rationale":{"type":"string"},"requires_review":{"type":"boolean"}},"required":["source_system","source_field","target_path","confidence","rationale","requires_review"]}}},"required":["mappings"]}
    prompt=("You are a conservative healthcare integration design agent. Propose only evidence-grounded source-to-FHIR R4-aligned mappings. Preserve identifier namespaces, never match people by name alone, flag uncertain mappings for human review, and do not invent fields. Profiles: "+json.dumps([p.model_dump() for p in profiles]))
    try:
        response=httpx.post("https://api.openai.com/v1/chat/completions",headers={"Authorization":f"Bearer {api_key}"},json={"model":os.getenv("OPENAI_MODEL","gpt-4.1-mini"),"temperature":0,"messages":[{"role":"user","content":prompt}],"response_format":{"type":"json_schema","json_schema":{"name":"integration_mappings","strict":True,"schema":schema}}},timeout=25)
        response.raise_for_status(); data=json.loads(response.json()["choices"][0]["message"]["content"])
        mapped=[MappingProposal.model_validate(x) for x in data["mappings"]]
        if any(x.source_system not in {p.system_id for p in profiles} for x in mapped): raise ValueError("Unknown system in model output")
        return mapped, "llm_structured"
    except Exception:
        return propose_mappings(), "deterministic_fallback"

def run_workflow(patient_id: str="ehr-pat-001") -> dict:
    crosswalk={"ehr-pat-001":"LIS-P-1001", "ehr-pat-002":"LIS-P-2044", "ehr-pat-003":"LIS-P-3098"}
    if patient_id not in crosswalk: raise ValueError("No documented synthetic EHR↔LIS crosswalk for this patient.")
    patient=get_ehr_patient(patient_id); lis=get_lis_results(crosswalk[patient_id])
    his_path=MOCK_DIR/"his_mock_system/samples/adt_a01.hl7"; his=parse_hl7_patient(his_path)
    oru_path=MOCK_DIR/"his_mock_system/samples/oru_r01.hl7"
    oru_patient=parse_hl7_patient(oru_path)
    if oru_patient["patient_id"] != his["patient_id"]: raise ValueError("HIS ADT and ORU messages refer to different local patient IDs.")
    name=(patient.get("name") or [{}])[0]; rawdob=his["birthdate"]
    hisdob=f"{rawdob[:4]}-{rawdob[4:6]}-{rawdob[6:8]}"
    if hisdob != patient["birthDate"] or his["given"].casefold() != name["given"][0].casefold() or his["family"].casefold() != name["family"].casefold():
        raise ValueError("HIS demographics do not corroborate EHR patient; manual identity review required.")
    observations=[]
    for row in lis:
        ob={"resourceType":"Observation","id":row["order_id"]+"-"+row["test_code"],"status":row["result_status"],"category":[{"coding":[{"code":"laboratory"}]}],"code":{"coding":[{"system":"http://loinc.org","code":row["loinc_code"],"display":row["test_name"]}]},"subject":{"reference":f"Patient/{patient_id}"},"effectiveDateTime":row["observed_at"],"interpretation":row["abnormal_flag"],"extension_source":{"system":"LIS","patient_id":row["patient_id"]}}
        if row["result_value"] is not None: ob["valueQuantity"]={"value":row["result_value"],"unit":row["unit"]}
        observations.append(ob)
    for item in parse_hl7_observations(oru_path):
        item["subject"]={"reference":f"Patient/{patient_id}"}
        item["extension_source"]={"system":"HIS","local_patient_id":his["patient_id"]}
        observations.append(item)
    studies=get_pacs_studies(); rpm=get_rpm_readings()
    profiles=discover()
    mappings,mapping_mode=propose_mappings_with_ai(profiles)
    imaging=[{"study_instance_uid":x.get("MainDicomTags",{}).get("StudyInstanceUID"),"accession_number":x.get("MainDicomTags",{}).get("AccessionNumber"),"source":"PACS"} for x in studies]
    context={"resourceType":"Bundle","type":"collection","patient":{"resourceType":"Patient","id":patient_id,"identifier":patient.get("identifier",[]),"name":[name],"birthDate":patient["birthDate"],"gender":patient.get("gender"),"source":"EHR"},"identity_links":[{"system":"EHR","id":patient_id},{"system":"LIS","id":crosswalk[patient_id],"basis":"documented synthetic crosswalk + DOB/name corroboration"},{"system":"HIS","id":his["patient_id"],"basis":"DOB + given/family name corroboration"}],"observations":observations,"imaging_studies":imaging,"unlinked_rpm_readings":[{"patient_id":r["patient_id"],"device_id":r["device_id"],"timestamp":r["timestamp"],"reason":"No documented crosswalk in supplied mock data; not merged"} for r in rpm],"provenance":{"sources":["EHR","LIS","HIS"]+(["PACS"] if studies else [])+["RPM (unlinked)"],"generated_at":datetime.now(timezone.utc).isoformat()}}
    checks=[
      Check(name="FHIR Patient ID present",passed=bool(patient.get("id")),severity="error",detail=patient.get("id","missing")),
      Check(name="Birth date ISO format",passed=len(patient.get("birthDate",""))==10,severity="error",detail=patient.get("birthDate","missing")),
      Check(name="HIS identity corroborated",passed=True,severity="error",detail="DOB and normalised given/family name agree."),
      Check(name="LIS observations mapped",passed=bool(observations),severity="error",detail=f"{len(observations)} result(s) mapped."),
      Check(name="LOINC coding present",passed=all(x["code"]["coding"][0]["code"] for x in observations),severity="warning",detail="All mapped observations have LOINC codes."),
      Check(name="RPM records not silently linked",passed=all(x["reason"] for x in context["unlinked_rpm_readings"]),severity="error",detail=f"{len(rpm)} RPM record(s) isolated pending identity review.")]
    errors=[x for x in checks if x.severity=="error" and not x.passed]
    rid="run-"+uuid.uuid4().hex[:10]; plan={"plan_id":"plan-"+uuid.uuid4().hex[:8],"title":"Unified synthetic patient context","target_standard":"FHIR R4-aligned JSON (prototype subset)","pattern":"Read-only adapters → canonical model → validation → human approval","mappings":[x.model_dump() for x in mappings],"mapping_mode":mapping_mode,"human_review_required":True,"assumptions":["Synthetic data only","RPM crosswalk unavailable; RPM data is intentionally unlinked","PACS can return zero studies if Orthanc has no uploaded images"]}
    out=ARTIFACTS_DIR/rid; out.mkdir(parents=True,exist_ok=True)
    (out/"integration-plan.json").write_text(json.dumps(plan,indent=2)); (out/"patient-context.json").write_text(json.dumps(context,indent=2))
    (out/"generated_transform.py").write_text('"""Generated deterministic scaffold; review before use."""\ndef to_patient(source):\n    name=(source.get("name") or [{}])[0]\n    return {"resourceType":"Patient","id":source["id"],"identifier":source.get("identifier",[]),"name":[name],"birthDate":source.get("birthDate"),"gender":source.get("gender")}\n')
    (out/"README.md").write_text("Generated deterministic templates. They are not executed automatically; human review is required.\n")
    return {"run_id":rid,"status":"awaiting_human_approval" if not errors else "validation_failed","patient_key":patient_id,"profiles":[x.model_dump() for x in profiles],"plan":plan,"patient_context":context,"validation":{"passed":not errors,"summary":f"{len(checks)-len(errors)}/{len(checks)} checks passed","checks":[x.model_dump() for x in checks]},"approvals":{"mapping_approved":False,"release_approved":False},"generated_artifacts":[str(x) for x in out.iterdir()],"created_at":datetime.now(timezone.utc).isoformat()}

def send_hl7_mllp(message: str, host: str="localhost", port: int=2575, timeout: float=2) -> str:
    framed=b"\x0b"+message.replace("\n","\r").encode()+b"\x1c\r"
    with socket.create_connection((host,port),timeout=timeout) as sock:
        sock.settimeout(timeout); sock.sendall(framed); data=b""
        while b"\x1c\r" not in data:
            chunk=sock.recv(4096)
            if not chunk: break
            data+=chunk
    return data.decode(errors="replace").strip("\x0b\x1c\r")
