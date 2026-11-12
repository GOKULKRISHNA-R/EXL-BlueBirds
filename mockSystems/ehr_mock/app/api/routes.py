from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from app.core.config import get_settings
from app.services.repository import RESOURCE_TYPES, repository, search_resources

router = APIRouter()

def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().ehr_api_token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise HTTPException(401, "Invalid bearer token", headers={"WWW-Authenticate": "Bearer"})

def fhir_json(payload: dict) -> JSONResponse:
    return JSONResponse(payload, media_type="application/fhir+json")

@router.get("/metadata", tags=["FHIR metadata"])
def metadata():
    base = get_settings().ehr_base_url.rstrip("/")
    params = {
        "Patient": ["_id", "identifier", "family", "given", "birthdate", "gender"],
        "Encounter": ["_id", "patient", "status", "class"],
        "Condition": ["_id", "patient", "clinical-status"],
        "MedicationRequest": ["_id", "patient", "status"],
        "Observation": ["_id", "patient", "category", "code", "date"]
    }
    resources = [{"type": name, "interaction": [{"code": "read"}, {"code": "search-type"}],
                  "searchParam": [{"name": p, "type": "string"} for p in supported]}
                 for name, supported in params.items()]
    return fhir_json({"resourceType": "CapabilityStatement", "status": "active", "date": "2026-11-12",
        "kind": "instance", "fhirVersion": "4.0.1", "format": ["json"],
        "implementation": {"description": "Synthetic hackathon EHR mock; limited FHIR R4-style subset", "url": base},
        "rest": [{"mode": "server", "resource": resources}]})

@router.get("/fhir/{resource_type}", tags=["FHIR resources"], dependencies=[Depends(require_token)])
def search(resource_type: str, request: Request,
           count: int = Query(20, alias="_count", ge=1, le=100),
           offset: int = Query(0, alias="_offset", ge=0)):
    if resource_type not in RESOURCE_TYPES:
        raise HTTPException(404, f"Unsupported resource type: {resource_type}")
    filters = dict(request.query_params)
    filters.pop("_count", None); filters.pop("_offset", None)
    try:
        rows = search_resources(resource_type, filters)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    total = len(rows)
    page = rows[offset:offset + count]
    base = get_settings().ehr_base_url.rstrip("/")
    path = f"{base}/fhir/{resource_type}"
    query = "&".join(f"{k}={v}" for k, v in request.query_params.items())
    links = [{"relation": "self", "url": f"{path}?{query}" if query else path}]
    if offset + count < total: links.append({"relation": "next", "url": f"{path}?_count={count}&_offset={offset+count}"})
    if offset > 0: links.append({"relation": "previous", "url": f"{path}?_count={count}&_offset={max(0, offset-count)}"})
    return fhir_json({"resourceType": "Bundle", "type": "searchset", "total": total, "link": links,
        "entry": [{"fullUrl": f"{path}/{r['id']}", "resource": r, "search": {"mode": "match"}} for r in page]})

@router.get("/fhir/{resource_type}/{logical_id}", tags=["FHIR resources"], dependencies=[Depends(require_token)])
def read(resource_type: str, logical_id: str):
    if resource_type not in RESOURCE_TYPES:
        raise HTTPException(404, f"Unsupported resource type: {resource_type}")
    resource = repository.get(resource_type, logical_id)
    if resource is None:
        raise HTTPException(404, f"{resource_type}/{logical_id} not found")
    return fhir_json(resource)
