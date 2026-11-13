from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path
from .core import discover, run_workflow
app=FastAPI(title="EXL Agentic Healthcare Integration Factory",version="0.1.0",description="Synthetic-data prototype for EXL × UCD Challenge 01")
RUNS={}
@app.get("/health")
def health(): return {"status":"ok","mode":"synthetic-demo"}
@app.get("/api/systems")
def systems(): return [x.model_dump() for x in discover()]
@app.post("/api/runs")
def create_run(patient_id: str="ehr-pat-001"):
    try: data=run_workflow(patient_id); RUNS[data["run_id"]]=data; return data
    except Exception as exc: raise HTTPException(400,str(exc))
@app.get("/api/runs")
def list_runs(): return list(RUNS.values())
@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    if run_id not in RUNS: raise HTTPException(404,"Run not found")
    return RUNS[run_id]
@app.post("/api/runs/{run_id}/approve-mapping")
def approve_mapping(run_id: str):
    data=RUNS.get(run_id)
    if not data: raise HTTPException(404,"Run not found")
    if not data["validation"]["passed"]: raise HTTPException(409,"Validation errors block approval")
    data["approvals"]["mapping_approved"]=True; data["status"]="mapping_approved_pending_release"; return data
@app.post("/api/runs/{run_id}/approve-release")
def approve_release(run_id: str):
    data=RUNS.get(run_id)
    if not data: raise HTTPException(404,"Run not found")
    if not data["approvals"]["mapping_approved"]: raise HTTPException(409,"Mapping approval required first")
    data["approvals"]["release_approved"]=True; data["status"]="approved_for_release"; return data
@app.get("/",response_class=HTMLResponse)
def dashboard(): return (Path(__file__).parent/"dashboard.html").read_text()
