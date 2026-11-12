import logging
from fastapi import FastAPI
from app.api.routes import router
from app.core.config import get_settings

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())
app = FastAPI(title="Mock EHR — FHIR R4-style API", version="0.1.0",
    description="Synthetic read-only EHR source. Limited FHIR R4-style subset; not a certified FHIR server.")
app.include_router(router)

@app.get("/health", tags=["Operations"])
def health():
    return {"status": "ok", "service": "mock-ehr"}
