def test_health_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"

def test_metadata_public(client):
    r = client.get("/metadata")
    assert r.status_code == 200 and r.json()["resourceType"] == "CapabilityStatement"
    types = {x["type"] for x in r.json()["rest"][0]["resource"]}
    assert {"Patient", "Encounter", "Condition", "MedicationRequest", "Observation"} <= types

def test_auth_required(client):
    assert client.get("/fhir/Patient").status_code == 401

def test_invalid_token(client):
    assert client.get("/fhir/Patient", headers={"Authorization": "Bearer wrong"}).status_code == 401

def test_list_patients(client, auth_headers):
    r = client.get("/fhir/Patient", headers=auth_headers)
    assert r.status_code == 200 and r.json()["total"] == 3
    assert r.json()["resourceType"] == "Bundle"

def test_search_family(client, auth_headers):
    r = client.get("/fhir/Patient?family=Smith", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["entry"][0]["resource"]["id"] == "ehr-pat-001"

def test_read_patient(client, auth_headers):
    r = client.get("/fhir/Patient/ehr-pat-001", headers=auth_headers)
    assert r.status_code == 200 and r.json()["birthDate"] == "1995-05-10"

def test_observations_for_patient(client, auth_headers):
    r = client.get("/fhir/Observation?patient=ehr-pat-001", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["entry"][0]["resource"]["id"] == "ehr-obs-001"

def test_pagination(client, auth_headers):
    r = client.get("/fhir/Patient?_count=2&_offset=1", headers=auth_headers)
    assert r.status_code == 200 and len(r.json()["entry"]) == 2
    assert any(x["relation"] == "previous" for x in r.json()["link"])

def test_unknown_search_parameter(client, auth_headers):
    assert client.get("/fhir/Patient?badparam=x", headers=auth_headers).status_code == 400

def test_unknown_resource_and_id(client, auth_headers):
    assert client.get("/fhir/Procedure", headers=auth_headers).status_code == 404
    assert client.get("/fhir/Patient/nope", headers=auth_headers).status_code == 404

def test_fhir_content_type(client, auth_headers):
    r = client.get("/fhir/Patient", headers=auth_headers)
    assert r.headers["content-type"].startswith("application/fhir+json")
