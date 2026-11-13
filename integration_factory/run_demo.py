import json
from integration_factory.agents import run_agentic

if __name__ == "__main__":
    result = run_agentic()
    for e in result["trace"]: print(f"{e['step']:>2} {'ok  ' if e['ok'] else 'FAIL'} {e['agent']} [{e['mode']}] {e['action']}: {e['detail']}")
    print(json.dumps({
        "run_id": result["run_id"], "status": result["status"],
        "metrics": result["metrics"], "patient": result["patient_context"]["patient"],
        "mapped_observations": len(result["patient_context"]["observations"]),
        "unlinked_rpm_records": len(result["patient_context"]["unlinked_rpm_readings"]),
        "generated_artifacts": result["generated_artifacts"]
    }, indent=2))
