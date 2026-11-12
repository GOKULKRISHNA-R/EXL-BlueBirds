import os
os.environ["EHR_API_TOKEN"] = "test-token"
os.environ["EHR_BASE_URL"] = "http://testserver"
import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token", "Accept": "application/fhir+json"}
