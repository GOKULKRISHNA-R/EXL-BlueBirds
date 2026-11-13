from fastapi.testclient import TestClient
from integration_factory.core import discover, run_workflow
from integration_factory.api import app

def test_discovery_finds_all_five_systems():
    assert {p.system_id for p in discover()} == {"ehr", "lis", "his", "pacs", "rpm"}

def test_offline_integration_run():
    result = run_workflow()
    assert result["validation"]["passed"]
    assert len(result["patient_context"]["observations"]) == 4
    assert len(result["patient_context"]["unlinked_rpm_readings"]) == 3
    assert result["status"] == "awaiting_human_approval"
    assert result["plan"]["mapping_mode"] == "deterministic_fallback"

def test_unknown_patient_rejected():
    import pytest
    with pytest.raises(ValueError): run_workflow("not-a-real-patient")

def test_api_and_human_approval_gates():
    client=TestClient(app)
    assert client.get("/health").status_code == 200
    assert len(client.get("/api/systems").json()) == 5
    result=client.post("/api/runs").json(); rid=result["run_id"]
    assert client.post(f"/api/runs/{rid}/approve-release").status_code == 409
    assert client.post(f"/api/runs/{rid}/approve-mapping").status_code == 200
    released=client.post(f"/api/runs/{rid}/approve-release")
    assert released.status_code == 200
    assert released.json()["status"] == "approved_for_release"
