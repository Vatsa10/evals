"""Exercise new reporting on real five-system application runs, or labeled CI doubles."""

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals import improvement
from evals.artifacts import read_json, write_json
from evals.report_site import build_report_site, verify_snapshot
from evals.reporting import compare_shared_reports, summarize_report
from scripts.production_lab import configure, prepare


def run(workspace, model):
    workspace = prepare(workspace, model)
    configure(workspace)
    suite = read_json(workspace / "suite.json")
    identifiers = {"llm-quantity-and-currency", "rag-current-policy", "chatbot-retains-preference",
                   "chatbot-session-isolation", "multi-agent-reviewed-handoff", "tools-response-lost-after-commit"}
    suite["cases"] = [case for case in suite["cases"] if case["id"] in identifiers]
    # A declared but untested category demonstrates missing coverage honestly.
    suite["coverage_categories"].append("vision")
    suite["provenance"] = {"label": "Live models; synthetic application data" if model == "live" else "Deterministic orchestration checks"}
    suite["environment"] = {"provider": "claude-code-cli" if model == "live" else "fixture-model",
                            "configuration": {"transport": "existing-login-cli" if model == "live" else "test-double"}}
    write_json(workspace / "suite.json", suite)
    regression = dict(suite, name="reporting-protected-session-isolation",
                      cases=[case for case in suite["cases"] if case["id"] == "chatbot-session-isolation"])
    write_json(workspace / "regression.json", regression)
    directory, _ = improvement.start(workspace / "suite.json", goal="Verify provenance, coverage and report artifacts across five system types",
        track=[workspace / "pipeline.py"], regression_suites=[workspace / "regression.json"], max_attempts=1,
        lock=[workspace / name for name in ("backend.py", "model.py", "fixture_model.py", "knowledge.json", "lab.json")],
        output=workspace / ".evals" / "improvement", store=workspace / ".evals" / "runs.db")
    baseline = read_json(directory / "baseline-0.json")
    print(json.dumps({"phase": "baseline", "model": model, "summary": baseline["summary"]}), flush=True)
    shutil.copyfile(ROOT / "examples" / "production_lab" / "pipeline.py", workspace / "pipeline.py")
    attempt = improvement.check(directory, hypothesis="Apply the repository's previously verified application architecture repair; validate the new reporting on its actual execution evidence")
    decision = improvement.finish(directory)
    candidate = read_json(directory / attempt["reports"][0])
    summary = summarize_report(candidate)
    write_json(workspace / ".evals" / "summary.json", summary)
    site = build_report_site(candidate, workspace / ".evals" / "report", baseline)
    verify_snapshot(read_json(site["snapshot"]))
    protected = read_json(directory / "baseline-1.json")
    exploratory = compare_shared_reports(protected, candidate)
    write_json(workspace / ".evals" / "shared-comparison.json", exploratory)
    build_report_site(candidate, workspace / ".evals" / "exploratory-report", protected)
    assert decision["status"] == "verified_improvement", decision["reason"]
    assert candidate["summary"]["passed"] == 6 and candidate["summary"]["error"] == 0
    assert sum(c["status"] == "tested" for c in summary["coverage"]) == 5
    assert next(c for c in summary["coverage"] if c["category"] == "vision")["success_rate"] is None
    assert exploratory["shared_cases"] == ["chatbot-session-isolation"] and len(exploratory["candidate_only"]) == 5
    assert exploratory["verification_eligible"] is False
    result = {"model": model, "baseline": baseline["summary"], "candidate": candidate["summary"],
              "decision": decision["status"], "coverage": summary["coverage"], "provenance": summary["provenance"],
              "report_site": site, "shared_cases": exploratory["shared_cases"],
              "candidate_only": exploratory["candidate_only"], "source_session": str(directory)}
    write_json(workspace / ".evals" / "reporting-verification.json", result)
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--model", choices=["live", "fixture"], default="live")
    args = parser.parse_args()
    raise SystemExit(run(args.workspace, args.model))
