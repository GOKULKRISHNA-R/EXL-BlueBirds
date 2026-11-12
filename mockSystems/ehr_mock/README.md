# Mock EHR — FHIR R4-style REST API

Standalone synthetic EHR source for the EXL × UCD hackathon. Independent of AI agents.

> **Scope:** This is a limited hackathon mock using FHIR R4-style resource shapes and REST conventions. It is not a complete/certified FHIR server and must never be used with real patient data or in clinical care.

## Features
- FastAPI REST service and Swagger/OpenAPI docs.
- Patient, Encounter, Condition, MedicationRequest and Observation resources.
- FHIR Bundle-style search results, read-by-ID, pagination and filters.
- Bearer-token authentication on `/fhir/*`.
- Public `/health` and `/metadata`.
- Synthetic seed records, Docker Compose and tests.

## Run with Docker
```bash
cp .env.example .env
# Change EHR_API_TOKEN before exposing beyond localhost.
docker compose up --build
```
Open `http://localhost:8000/docs`, `/metadata` or `/health`.

Example:
```bash
curl -H "Authorization: Bearer dev-ehr-token-change-me" \
  "http://localhost:8000/fhir/Patient?_count=2"
```

## Run locally (Python 3.11+)
```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
```
Run tests with `pytest -q`.

## API contract
All `/fhir/*` endpoints require `Authorization: Bearer <EHR_API_TOKEN>` and return `application/fhir+json`.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Public liveness check |
| GET | `/metadata` | Public CapabilityStatement-style description |
| GET | `/fhir/{resourceType}` | Search |
| GET | `/fhir/{resourceType}/{id}` | Read |

Supported types: `Patient`, `Encounter`, `Condition`, `MedicationRequest`, `Observation`.

| Resource | Search parameters |
|---|---|
| Patient | `_id`, `identifier`, `family`, `given`, `birthdate`, `gender` |
| Encounter | `_id`, `patient`, `status`, `class` |
| Condition | `_id`, `patient`, `clinical-status` |
| MedicationRequest | `_id`, `patient`, `status` |
| Observation | `_id`, `patient`, `category`, `code`, `date` |

`_count` defaults to 20 (max 100); `_offset` defaults to 0. Unknown parameters return 400. Advanced FHIR search modifiers/chaining/date prefixes are not implemented.

## Synthetic patients
All records are fictional. IDs intentionally differ from the other mock systems to support later patient identity resolution.

| EHR ID | MRN | Synthetic name |
|---|---|---|
| `ehr-pat-001` | `MRN-00123` | John Smith |
| `ehr-pat-002` | `MRN-00456` | Aisha Khan |
| `ehr-pat-003` | `MRN-00789` | Sofia Murphy |

Never infer patient identity from name alone.

## Configuration
| Variable | Default | Purpose |
|---|---|---|
| `EHR_API_TOKEN` | `dev-ehr-token-change-me` | Bearer token |
| `EHR_BASE_URL` | `http://localhost:8000` | Bundle link base |
| `LOG_LEVEL` | `INFO` | Logging |
| `EHR_DATA_FILE` | unset | Optional alternate seed JSON |

Do not commit `.env` or real credentials.

## Design choices
- Read-only initial iteration; no create/update/delete endpoints.
- JSON seed data keeps the source deterministic; repository layer can later be replaced by PostgreSQL.
- This is a limited FHIR-style subset, not full FHIR conformance.
- Synthetic data only; no real PHI.
- The service is a mock source, not a production clinical system.

## Next milestone
Verify the service and tests, then build the LIS independently. Keep all mock systems working without AI before implementing discovery agents.
