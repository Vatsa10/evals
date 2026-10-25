"""Export reviewable evidence from this synthetic lab without machine paths/auth data."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.artifacts import read_json, write_json


def compact_report(report):
    rows = []
    for trial in report["trials"]:
        observation = trial.get("observation", {})
        rows.append({"case_id": trial["case_id"], "trial": trial["trial"], "status": trial["status"],
                     "graders": trial["graders"], "error": trial.get("error"),
                     "observation": {key: observation[key] for key in
                                     ("output", "result", "status", "contract_error", "trace_id", "messages", "tools",
                                      "retrieval_context", "ledger", "metadata", "handoff", "review") if key in observation},
                     # Preserve the actual execution tree and recovery evidence.
                     # Model prompts remain in local reports, not this public summary.
                     "spans": [{key: span[key] for key in
                                ("id", "parent_id", "name", "kind", "started_at", "finished_at", "duration_ms", "status", "error")
                                if key in span} for span in observation.get("trace", [])]})
    return {key: report[key] for key in ("engine_version", "suite", "mode", "started_at", "dataset_sha256", "summary")} | {"trials": rows}


def export(workspace, output):
    workspace = Path(workspace).resolve()
    marker = read_json(workspace / "lab.json")
    if marker.get("scope") != "synthetic production-style application lab":
        raise ValueError("Exporter only supports the synthetic application lab; review other traces for private data manually")
    session = workspace / ".evals" / "improvement"
    state = read_json(session / "session.json")
    decision = read_json(session / "decision.json")
    attempt = next((a for a in state["attempts"] if a["number"] == decision["selected_attempt"]), None)
    if attempt is None:
        raise ValueError("No selected candidate to export")
    baselines = [read_json(session / name) for name in state["baseline_reports"]]
    candidates = [read_json(session / name) for name in attempt["reports"]]
    if any(trial.get("observation", {}).get("metadata", {}).get("model_mode") != marker["model"]
           for report in [*baselines, *candidates] for trial in report["trials"]):
        raise ValueError("Reports contain a different model mode or missing model evidence")
    result = {"schema_version": 1, "scope": marker["scope"], "model_mode": marker["model"],
              "engine_sha256": state["engine_sha256"], "session_id": state["id"],
              "max_attempts": state["max_attempts"], "attempts_used": len(state["attempts"]),
              "baseline": [compact_report(report) for report in baselines],
              "candidate": [compact_report(report) for report in candidates],
              "comparison": attempt["comparisons"],
              "decision": {key: decision[key] for key in ("status", "selected_attempt", "reason", "scope")},
              "source_changes": [{"file": Path(item["path"]).name,
                                  "before_sha256": item["before_sha256"], "after_sha256": item["after_sha256"],
                                  "diff": item["diff"]} for item in decision["changed_files"]],
              "verification": read_json(workspace / ".evals" / "verification.json")}
    write_json(output, result)
    return Path(output).resolve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(export(args.workspace, args.output))
