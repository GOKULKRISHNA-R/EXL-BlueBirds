import json
from integration_factory.core import run_workflow

if __name__ == "__main__":
    result = run_workflow()
    print(json.dumps({
        "run_id": result["run_id"], "status": result["status"],
        "validation": result["validation"], "patient": result["patient_context"]["patient"],
        "mapped_observations": len(result["patient_context"]["observations"]),
        "unlinked_rpm_records": len(result["patient_context"]["unlinked_rpm_readings"]),
        "generated_artifacts": result["generated_artifacts"]
    }, indent=2))
