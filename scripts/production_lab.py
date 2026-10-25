"""Reproduce baseline -> evidence -> known architecture patch -> live re-evaluation.

The patch is supplied by this repository, not invented by this script. Use the
Evals skill in a coding agent when you want the agent to diagnose and author a fix.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals import improvement
from evals.artifacts import read_json, write_json
from evals.diagnostics import diagnose_report
from evals.monitoring import monitor
from evals.storage import Store
from examples.production_lab.scenarios import write_suites


def prepare(workspace, model):
    workspace = Path(workspace).resolve()
    if workspace.exists():
        raise ValueError("Use a fresh workspace; existing evidence will not be overwritten")
    source = ROOT / "examples" / "production_lab"
    workspace.mkdir(parents=True)
    for path in source.glob("*.py"):
        shutil.copy2(path, workspace / path.name)
    shutil.copy2(source / "knowledge.json", workspace / "knowledge.json")
    legacy = source / "fixtures" / "legacy_pipeline.py"
    if legacy.exists():
        shutil.copyfile(legacy, workspace / "pipeline.py")
    write_suites(workspace)
    write_json(workspace / "lab.json", {"model": model, "scope": "synthetic production-style application lab"})
    return workspace


def configure(workspace):
    mode = read_json(workspace / "lab.json")["model"]
    os.environ["EVALS_LAB_MODEL"] = mode
    os.environ["EVALS_LAB_STORE"] = str(workspace / ".evals" / "traces.db")
    return mode


def baseline(workspace, model, trials):
    workspace = prepare(workspace, model)
    configure(workspace)
    directory, _ = improvement.start(
        workspace / "suite.json", goal="Improve LLM, RAG, chatbot, multi-agent and tool workflows using trace evidence",
        track=[workspace / "pipeline.py"],
        lock=[workspace / name for name in ("backend.py", "model.py", "fixture_model.py", "knowledge.json", "lab.json")],
        regression_suites=[workspace / "regression.json"], max_attempts=2, trials=trials,
        output=workspace / ".evals" / "improvement", store=workspace / ".evals" / "runs.db",
    )
    report = read_json(directory / "baseline-0.json")
    write_json(directory / "diagnosis.json", diagnose_report(report))
    print(json.dumps({"phase": "baseline", "model": model, "summary": report["summary"], "evidence": str(directory)}, indent=2), flush=True)


def verify(workspace):
    workspace = Path(workspace).resolve()
    mode = configure(workspace)
    session = workspace / ".evals" / "improvement"
    shutil.copyfile(ROOT / "examples" / "production_lab" / "pipeline.py", workspace / "pipeline.py")
    attempt = improvement.check(session, hypothesis=(
        "Use typed output contracts, trusted tenant-scoped retrieval, session-scoped history, "
        "validated researcher/writer/reviewer handoffs, and authorized idempotent bounded HTTP retries."))
    decision = improvement.finish(session)
    report = read_json(session / attempt["reports"][0])
    mode_checks = {trial["observation"]["metadata"]["model_mode"] for trial in report["trials"] if "observation" in trial}
    if mode_checks != {mode}:
        raise ValueError("The candidate did not use the declared model mode")
    write_json(session / "candidate-diagnosis.json", diagnose_report(report))
    events = []
    if attempt["ready"]:
        monitor(workspace / "regression.json", Store(workspace / ".evals" / "monitor.db"),
                interval=0.01, iterations=2, emit=lambda line: events.append(json.loads(line)))
    summary = {"model": mode, "scope": "Observed frozen lab cases; no customer production traffic",
               "baseline": read_json(session / "baseline-0.json")["summary"], "candidate": report["summary"],
               "decision": decision["status"], "monitor_events": events,
               "trace_counts": Store(workspace / ".evals" / "traces.db").counts()}
    write_json(workspace / ".evals" / "verification.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return int(not attempt["ready"] or any(event["alert_id"] for event in events))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--phase", choices=["baseline", "verify", "all"], default="all")
    parser.add_argument("--model", choices=["live", "fixture"], default="live")
    parser.add_argument("--trials", type=int, default=1)
    args = parser.parse_args()
    if args.phase in {"baseline", "all"}:
        baseline(args.workspace, args.model, args.trials)
    if args.phase in {"verify", "all"}:
        return verify(args.workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
