import json
from pathlib import Path
from typing import Any
from app.core.config import get_settings

RESOURCE_TYPES = {"Patient", "Encounter", "Condition", "MedicationRequest", "Observation"}

class ResourceRepository:
    # Read-only repository abstraction; storage can be replaced independently later.
    def __init__(self) -> None:
        settings = get_settings()
        path = Path(settings.ehr_data_file) if settings.ehr_data_file else Path(__file__).resolve().parents[1] / "data" / "seed.json"
        with path.open(encoding="utf-8") as handle:
            self.data: dict[str, list[dict[str, Any]]] = json.load(handle)

    def list(self, resource_type: str) -> list[dict[str, Any]]:
        if resource_type not in RESOURCE_TYPES:
            raise KeyError(resource_type)
        return self.data.get(resource_type, [])

    def get(self, resource_type: str, logical_id: str) -> dict[str, Any] | None:
        return next((r for r in self.list(resource_type) if r.get("id") == logical_id), None)

repository = ResourceRepository()

def _has_reference(resource: dict, patient_id: str) -> bool:
    for key in ("subject", "patient"):
        value = resource.get(key)
        if isinstance(value, dict) and value.get("reference", "").split("/")[-1] == patient_id:
            return True
    return False

def _codes(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        if isinstance(value.get("code"), str):
            found.add(value["code"].lower())
        for child in value.values():
            found |= _codes(child)
    elif isinstance(value, list):
        for child in value:
            found |= _codes(child)
    return found

def search_resources(resource_type: str, params: dict[str, str]) -> list[dict[str, Any]]:
    rows = repository.list(resource_type)
    for key, value in params.items():
        if resource_type == "Patient":
            if key == "_id": rows = [r for r in rows if r.get("id") == value]
            elif key == "identifier": rows = [r for r in rows if any(x.get("value") == value for x in r.get("identifier", []))]
            elif key == "family": rows = [r for r in rows if any(n.get("family", "").lower() == value.lower() for n in r.get("name", []))]
            elif key == "given": rows = [r for r in rows if any(value.lower() in [g.lower() for g in n.get("given", [])] for n in r.get("name", []))]
            elif key == "birthdate": rows = [r for r in rows if r.get("birthDate") == value]
            elif key == "gender": rows = [r for r in rows if r.get("gender") == value.lower()]
            else: raise ValueError(f"Unsupported search parameter '{key}' for Patient")
        else:
            if key == "_id": rows = [r for r in rows if r.get("id") == value]
            elif key == "patient": rows = [r for r in rows if _has_reference(r, value)]
            elif key == "status": rows = [r for r in rows if r.get("status") == value]
            elif key == "clinical-status" and resource_type == "Condition": rows = [r for r in rows if value.lower() in _codes(r.get("clinicalStatus"))]
            elif key == "class" and resource_type == "Encounter": rows = [r for r in rows if value.lower() in _codes(r.get("class"))]
            elif key == "category" and resource_type == "Observation": rows = [r for r in rows if value.lower() in _codes(r.get("category"))]
            elif key == "code" and resource_type == "Observation": rows = [r for r in rows if value.lower() in _codes(r.get("code"))]
            elif key == "date" and resource_type == "Observation": rows = [r for r in rows if r.get("effectiveDateTime", "").startswith(value)]
            else: raise ValueError(f"Unsupported search parameter '{key}' for {resource_type}")
    return rows
