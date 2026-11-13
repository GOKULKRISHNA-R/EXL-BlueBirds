from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path
from .core import discover, run_workflow
from .agents import run_agentic, retry_adapter, submit_adapter_code, audit
from .config import ARTIFACTS_DIR
from pydantic import BaseModel
import json
app=FastAPI(title="EXL Agentic Healthcare Integration Factory",version="0.1.0",description="Synthetic-data prototype for EXL × UCD Challenge 01")
RUNS={}
def save(run):
    """Persist every change so a server reload doesn't lose the run (and silently break the approval buttons)."""
    RUNS[run["run_id"]]=run
    try: d=ARTIFACTS_DIR/run["run_id"]; d.mkdir(parents=True,exist_ok=True); (d/"run.json").write_text(json.dumps(run,default=str))
    except OSError: pass
    return run
def find(run_id):
    if run_id in RUNS: return RUNS[run_id]
    f=ARTIFACTS_DIR/run_id/"run.json"
    if run_id.startswith("run-") and "/" not in run_id and f.exists():
        try: RUNS[run_id]=json.loads(f.read_text()); return RUNS[run_id]
        except ValueError: pass
    raise HTTPException(404,"Run not found. Start a new run.")
class CodeBody(BaseModel): code: str
@app.get("/health")
def health(): return {"status":"ok","mode":"synthetic-demo"}
@app.get("/api/systems")
def systems(): return [x.model_dump() for x in discover()]
@app.post("/api/runs")
def create_run(patient_id: str="ehr-pat-001"):
    try: data=save(run_workflow(patient_id)); return data
    except Exception as exc: raise HTTPException(400,str(exc))
@app.post("/api/agentic-runs")
def create_agentic_run(patient_id: str="ehr-pat-001", inject_fault: bool=False):
    """Full agent pipeline: discover -> design -> generate -> validate/repair -> stop for human approval."""
    try: data=save(run_agentic(patient_id, inject_fault)); return data
    except Exception as exc: raise HTTPException(400,str(exc))
@app.get("/api/runs")
def list_runs(): return list(RUNS.values())
@app.get("/api/runs/{run_id}")
def get_run(run_id: str): return find(run_id)
@app.post("/api/runs/{run_id}/approve-mapping")
def approve_mapping(run_id: str):
    data=find(run_id)
    if not data["validation"]["passed"]:
        bad=[r["system"] for r in data.get("agent_validation",[]) if not r["passed"]]
        raise HTTPException(409,"Approval is blocked: validation failed"+(f" for the {', '.join(bad)} adapter" if bad else " (identity/data checks)")+". Fix it first: retry, use the safe template, or edit the code.")
    data["approvals"]["mapping_approved"]=True; data["status"]="mapping_approved_pending_release"; audit(data,"reviewer","approve_mapping"); return save(data)
@app.post("/api/runs/{run_id}/approve-release")
def approve_release(run_id: str):
    data=find(run_id)
    if not data["approvals"]["mapping_approved"]: raise HTTPException(409,"Mapping approval required first")
    data["approvals"]["release_approved"]=True; data["status"]="approved_for_release"; audit(data,"reviewer","approve_release"); return save(data)
@app.post("/api/runs/{run_id}/adapters/{system}/retry")
def retry(run_id: str, system: str, strategy: str="template", hint: str=""):
    """strategy=ai re-prompts the model with the failures (+ optional reviewer hint); strategy=template regenerates deterministically."""
    if strategy not in ("ai","template"): raise HTTPException(400,"strategy must be 'ai' or 'template'")
    data=find(run_id)
    try: return save(retry_adapter(data,system,strategy,hint))
    except KeyError: raise HTTPException(404,f"No adapter for system '{system}'")
@app.put("/api/runs/{run_id}/adapters/{system}/code")
def edit_code(run_id: str, system: str, body: CodeBody):
    if len(body.code)>20000: raise HTTPException(413,"Adapter code too large")
    data=find(run_id)
    try: return save(submit_adapter_code(data,system,body.code))
    except KeyError: raise HTTPException(404,f"No adapter for system '{system}'")
@app.get("/",response_class=HTMLResponse)
def dashboard(): return (Path(__file__).parent/"dashboard.html").read_text()
