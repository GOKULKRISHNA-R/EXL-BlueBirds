from fastapi.testclient import TestClient
from integration_factory.agents import run_agentic, static_check, validation_agent, template_code, FALLBACK_MAPPINGS, sample_records
from integration_factory.api import app
from integration_factory.core import discover

def test_discovery_reads_real_sources():
    profiles = {p.system_id: p for p in discover()}
    names = lambda s: {f["name"] for f in profiles[s].discovered_fields}
    assert "lab_results.result_value" in names("lis") and "PID-7" in names("his")
    assert "heart_rate_bpm" in names("rpm") and "Patient.birthDate" in names("ehr")
    assert "ORU^R01" in profiles["his"].capabilities

def test_agentic_run_passes_and_stops_for_approval():
    result = run_agentic()
    assert result["status"] == "awaiting_human_approval"
    assert all(r["passed"] and r["attempts"] == 1 for r in result["agent_validation"])
    assert result["plan"]["rejected_mappings"] == []
    assert result["metrics"]["repair_attempts"] == 0
    assert {e["agent"] for e in result["trace"]} >= {"Discovery Agent", "Design Agent", "Code Generation Agent", "Validation Agent"}

def test_injected_fault_is_caught_then_repaired():
    result = run_agentic(inject_fault=True)
    his = next(r for r in result["agent_validation"] if r["system"] == "his")
    assert his["passed"] and his["attempts"] == 2
    assert any(e["agent"] == "Validation Agent" and not e["ok"] and "birthDate" in e["detail"] for e in result["trace"])
    assert result["metrics"]["repair_attempts"] == 1

def test_unsafe_generated_code_is_blocked():
    assert static_check("import os\ndef transform(r): return {}")
    assert static_check("def transform(r): return open('/etc/passwd').read()")
    spec = [m for m in FALLBACK_MAPPINGS if m["source_system"] == "his"]
    report = validation_agent("his", "import subprocess\ndef transform(r): return {}", spec, sample_records("ehr-pat-001")["his"])
    assert not report["passed"] and len(report["checks"]) == 1

def test_wrong_adapter_fails_reconciliation():
    spec = [m for m in FALLBACK_MAPPINGS if m["source_system"] == "lis"]
    code = template_code("lis", spec).replace("'valueQuantity.value', to_float", "'valueQuantity.value', copy")
    report = validation_agent("lis", code, spec, sample_records("ehr-pat-001")["lis"])
    assert not report["passed"]

def test_agentic_api_and_gates():
    client = TestClient(app)
    run = client.post("/api/agentic-runs").json()
    assert run["pipeline"] == "agentic" and set(run["adapters"]) == {"lis", "his", "rpm"}
    assert client.post(f"/api/runs/{run['run_id']}/approve-release").status_code == 409
    assert client.post(f"/api/runs/{run['run_id']}/approve-mapping").status_code == 200
