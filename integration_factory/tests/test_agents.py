from fastapi.testclient import TestClient
from integration_factory.agents import run_agentic, static_check, validation_agent, template_code, FALLBACK_MAPPINGS, sample_records, _CIRCUIT_BREAKER, llm_json
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

def test_circuit_breaker_trips_and_fails_fast():
    _CIRCUIT_BREAKER.reset()
    assert _CIRCUIT_BREAKER.state == "CLOSED"
    assert _CIRCUIT_BREAKER.allow_request() is True

    # Simulate 2 consecutive timeouts/failures
    _CIRCUIT_BREAKER.record_failure("test timeout 1")
    assert _CIRCUIT_BREAKER.state == "CLOSED"
    _CIRCUIT_BREAKER.record_failure("test timeout 2")
    assert _CIRCUIT_BREAKER.state == "OPEN"
    assert _CIRCUIT_BREAKER.allow_request() is False

    # When circuit is open, llm_json fails fast immediately
    res = llm_json("dummy prompt", {}, "dummy_schema")
    assert res is None

    # Reset restores normal operation
    _CIRCUIT_BREAKER.reset()
    assert _CIRCUIT_BREAKER.state == "CLOSED"


def test_failed_adapter_blocks_approval_then_reviewer_fix_unblocks():
    client = TestClient(app)
    run = client.post("/api/agentic-runs").json(); rid = run["run_id"]
    broken = run["adapters"]["his"].replace("hl7_date_to_iso(record", "copy(record")
    bad = client.put(f"/api/runs/{rid}/adapters/his/code", json={"code": broken}).json()
    assert bad["status"] == "needs_correction" and not bad["validation"]["passed"]
    blocked = client.post(f"/api/runs/{rid}/approve-mapping")
    assert blocked.status_code == 409 and "his" in blocked.json()["detail"]
    fixed = client.post(f"/api/runs/{rid}/adapters/his/retry?strategy=template").json()
    assert fixed["status"] == "awaiting_human_approval" and fixed["validation"]["passed"]
    assert client.post(f"/api/runs/{rid}/approve-mapping").status_code == 200
    assert [a["action"] for a in fixed["audit"]] == ["manual_edit", "retry_template"]

def test_run_survives_server_reload():
    from integration_factory import api
    client = TestClient(app)
    rid = client.post("/api/agentic-runs").json()["run_id"]
    api.RUNS.clear()
    assert client.post(f"/api/runs/{rid}/approve-mapping").status_code == 200
    assert client.get("/api/runs/run-does-not-exist").status_code == 404
