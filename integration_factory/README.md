# EXL Agentic Healthcare Integration Factory — Python prototype

Adds a Python integration platform beside the five existing mock systems. It does not replace or rewrite them.

## Implemented
- Discovery profiles for EHR, LIS, HIS, PACS and RPM.
- EHR read-only connector: live FHIR-style REST API with synthetic JSON fallback.
- LIS connector: PostgreSQL view when `LIS_DSN` is configured; otherwise parses the checked-in SQL seed.
- HIS connector: parses the supplied HL7 v2 PID and ORU/OBX segments; includes an optional MLLP sender helper.
- PACS connector: queries Orthanc REST when available; empty/offline PACS is reported as empty, never fabricated.
- RPM connector: reads the supplied JSONL telemetry. No undocumented patient crosswalk is invented; RPM records remain unlinked.
- Deterministic mapping/design stage with optional schema-constrained OpenAI structured-output mapping proposals, FHIR-aligned patient context, validation, generated artefacts and human approval gates.
- FastAPI API and dashboard.

## Important agent status
The workflow is deterministic by default. If `OPENAI_API_KEY` is configured, the Design Agent can request schema-constrained mapping proposals from an OpenAI-compatible Chat Completions endpoint. Responses are Pydantic-validated and fall back safely to deterministic mappings on failure. This is limited LLM-assisted design, not yet a fully autonomous multi-agent LangGraph system. Generated code is never executed automatically.

## Run locally
From this folder:
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest
cp .env.example .env  # optional; configure OPENAI_API_KEY to enable LLM mapping suggestions
python run_demo.py
uvicorn integration_factory.api:app --reload --port 8080
```
Open http://localhost:8080 or http://localhost:8080/docs. Run `pytest -q` to execute the test suite.

Offline demo uses only bundled synthetic data; it does not require Docker, a database, an LLM key or network access. For container deployment, run the existing mock services from their individual directories first, then run `docker compose up --build` from this folder. Docker runtime was not available in the build environment, so container startup still needs to be verified on your machine.

## API
- `GET /health`
- `GET /api/systems`
- `POST /api/runs?patient_id=ehr-pat-001`
- `GET /api/runs`, `GET /api/runs/{run_id}`
- `POST /api/runs/{run_id}/approve-mapping`
- `POST /api/runs/{run_id}/approve-release`

## Safety and limitations
- Synthetic data only; not for clinical use.
- Default connectors are read-only.
- EHR↔LIS mapping uses the crosswalk explicitly documented in the supplied mock README. HIS is corroborated by DOB and given/family name; names are never used alone.
- RPM readings are not attached to any patient because no explicit crosswalk exists in the repository.
- PACS contributes data only if Orthanc has studies uploaded.
- Generated Python is a reviewable template and is not executed by this service.
- Mapping and release approvals are separate gates.
- This is not a certified FHIR server or production healthcare platform.

## Next milestones
Persist run/audit state; add live schema discovery; add optional LangGraph + LLM structured-output agents; sandbox generated-code tests; add patient crosswalk review; add security/PHI checks and retry/idempotency; benchmark manual vs assisted integration.
