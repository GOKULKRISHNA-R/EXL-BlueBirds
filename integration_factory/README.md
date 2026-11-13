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

## Agent pipeline
`POST /api/agentic-runs` (or the dashboard button) runs four agents behind one orchestrator and records every step in a trace:

1. **Discovery Agent** (`discovery.py`) inspects each system: live endpoint when it answers (EHR `/metadata`, LIS `information_schema`, Orthanc `/system`, HIS MLLP port), otherwise the artefacts the system ships with (seed JSON, SQL DDL, HL7 samples, JSONL telemetry). Each profile says which was used.
2. **Design Agent** picks an integration pattern per system and proposes field mappings with a confidence and rationale. Every mapping is grounded: a source field that discovery did not find is rejected before code generation.
3. **Code Generation Agent** writes one adapter per source (LIS → Observation, HIS → Patient, RPM → Observation).
4. **Validation Agent** scans the code statically, runs it in an isolated subprocess on real, malformed and empty records, and reconciles every output field against an independently computed expected value. Failures go back to the Code Generation Agent (up to 3 attempts).
5. The run then **stops for human approval** (mappings, then release).

`inject_fault=true` plants a labelled defect in the first HIS adapter so the catch-and-repair loop can be demonstrated.

### LLM status (read before claiming anything in the deck)
Without `OPENAI_API_KEY`, design and code generation use deterministic rules and templates, and the trace labels them `deterministic`. With a key, the Design Agent and Code Generation Agent (including repair) call an OpenAI-compatible endpoint with schema-constrained output, labelled `llm`; the same grounding, sandbox and reconciliation guardrails apply, and any failed call falls back to the deterministic path. **The LLM path has not been exercised yet because no key was available during development — run it once with a key before the demo.**

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
- `POST /api/agentic-runs?patient_id=ehr-pat-001&inject_fault=false` — full agent pipeline
- `POST /api/runs?patient_id=ehr-pat-001` — original single-pass workflow
- `GET /api/runs`, `GET /api/runs/{run_id}`
- `POST /api/runs/{run_id}/approve-mapping`
- `POST /api/runs/{run_id}/approve-release`

## Safety and limitations
- Synthetic data only; not for clinical use.
- Default connectors are read-only.
- EHR↔LIS mapping uses the crosswalk explicitly documented in the supplied mock README. HIS is corroborated by DOB and given/family name; names are never used alone.
- RPM readings are not attached to any patient because no explicit crosswalk exists in the repository.
- PACS contributes data only if Orthanc has studies uploaded.
- Generated adapters are executed only inside the validation sandbox (separate isolated interpreter, static safety scan first, 10 s timeout). This is process isolation, not a hardened container.
- Mapping and release approvals are separate gates.
- This is not a certified FHIR server or production healthcare platform.

## Next milestones
Persist run/audit state; add live schema discovery; add optional LangGraph + LLM structured-output agents; sandbox generated-code tests; add patient crosswalk review; add security/PHI checks and retry/idempotency; benchmark manual vs assisted integration.
