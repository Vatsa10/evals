import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

from evals import __version__
from evals.engine import compare_reports, load_suite, run_suite
from evals.starter import initialize
from evals.monitoring import alert_for_run, load_policy, monitor, record_trace, save_run
from evals.storage import Store
from evals.artifacts import write_json as write_report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="evals", description="Independent LLM and agent evaluation framework")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a runnable demo suite without overwriting files")
    init.add_argument("directory", nargs="?", default="evaluations")
    brief = commands.add_parser("brief", help="Save project targets, answers and execution constraints")
    brief_commands = brief.add_subparsers(dest="brief_command", required=True)
    begin_brief = brief_commands.add_parser("init", help="Create a draft brief without replacing existing answers")
    begin_brief.add_argument("path", nargs="?", type=Path, default=Path("evaluations/brief.json"))
    begin_brief.add_argument("--from", dest="answers", type=Path)
    begin_brief.add_argument("--project-root", type=Path)
    edit_brief = brief_commands.add_parser("update", help="Merge explicit answers into an existing brief")
    edit_brief.add_argument("path", type=Path)
    edit_brief.add_argument("--from", dest="answers", type=Path, required=True)
    for name in ("show", "check"):
        item = brief_commands.add_parser(name)
        item.add_argument("path", type=Path)
    workflow = commands.add_parser("workflow", help="Execute a ready project brief through the evaluation engine")
    workflow_commands = workflow.add_subparsers(dest="workflow_command", required=True)
    start_workflow = workflow_commands.add_parser("start")
    start_workflow.add_argument("brief", type=Path)
    start_workflow.add_argument("--output", type=Path)
    workflow_status = workflow_commands.add_parser("status")
    workflow_status.add_argument("directory", type=Path)
    validate = commands.add_parser("validate", help="Validate a suite without executing adapters")
    validate.add_argument("suite")
    run = commands.add_parser("run", help="Execute a suite and save an evidence-backed JSON report")
    run.add_argument("suite")
    run.add_argument("--trials", type=int)
    run.add_argument("--output", type=Path)
    run.add_argument("--store", type=Path, help="SQLite history path (default: .evals/evals.db)")
    report = commands.add_parser("report", help="Read a saved report")
    report.add_argument("path", type=Path)
    summary = commands.add_parser("summarize", help="Show provenance, case/trial counts and category coverage")
    summary.add_argument("path", type=Path)
    summary.add_argument("--output", type=Path)
    site = commands.add_parser("report-site", help="Build an offline report page and content-versioned summary snapshot")
    site.add_argument("path", type=Path)
    site.add_argument("--baseline", type=Path)
    site.add_argument("--output", type=Path, required=True)
    snapshot = commands.add_parser("verify-snapshot", help="Check a report snapshot's content hash")
    snapshot.add_argument("path", type=Path)
    diagnose = commands.add_parser("diagnose", help="Summarize failed graders and component trace evidence")
    diagnose.add_argument("path", type=Path)
    diagnose.add_argument("--output", type=Path)
    compare = commands.add_parser("compare", help="Compare case success rates on the same dataset")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    compare.add_argument("--shared-only", action="store_true", help="Exploratory compatible-case overlap; cannot verify an improvement")
    compare.add_argument("--output", type=Path)
    monitoring = commands.add_parser("monitor", help="Continuously evaluate a suite and record regression alerts")
    monitoring.add_argument("suite")
    monitoring.add_argument("--interval", type=float, default=60)
    monitoring.add_argument("--iterations", type=int, help="Omit to run until interrupted")
    monitoring.add_argument("--baseline", type=Path)
    monitoring.add_argument("--store", type=Path)
    history = commands.add_parser("history", help="Inspect saved evaluation runs, traces, or alerts")
    history.add_argument("--kind", choices=["runs", "traces", "alerts"], default="runs")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--thread-id")
    history.add_argument("--store", type=Path)
    ingest = commands.add_parser("ingest", help="Record a trace and optionally apply online graders")
    ingest.add_argument("trace", type=Path)
    ingest.add_argument("--policy", type=Path)
    ingest.add_argument("--store", type=Path)
    serve = commands.add_parser("serve", help="Serve a local monitoring and trace-ingestion JSON API")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--policy", type=Path)
    serve.add_argument("--store", type=Path)
    export = commands.add_parser("export", help="Turn a captured trace into a recorded regression suite")
    export.add_argument("trace_id")
    export.add_argument("--policy", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--store", type=Path)
    improve = commands.add_parser("improve", help="Run a guarded evaluation and application-improvement session")
    improvement_commands = improve.add_subparsers(dest="improve_command", required=True)
    begin = improvement_commands.add_parser("start", help="Freeze criteria, evaluate a baseline, and prepare a failure brief")
    begin.add_argument("suite", type=Path)
    begin.add_argument("--goal", required=True)
    begin.add_argument("--track", type=Path, action="append", required=True, help="Application/prompt file to track (repeatable)")
    begin.add_argument("--lock", type=Path, action="append", default=[], help="Additional rubric/reference file to freeze")
    begin.add_argument("--regression-suite", type=Path, action="append", default=[])
    begin.add_argument("--max-attempts", type=int, default=3)
    begin.add_argument("--trials", type=int)
    begin.add_argument("--output", type=Path)
    begin.add_argument("--store", type=Path)
    begin.add_argument("--allow-partial", action="store_true", help="Permit measured partial improvement; default requires the primary suite to pass")
    candidate = improvement_commands.add_parser("check", help="Evaluate an application change against frozen baselines")
    candidate.add_argument("session", type=Path)
    candidate.add_argument("--hypothesis", required=True)
    for name in ("status", "brief", "finish"):
        command = improvement_commands.add_parser(name)
        command.add_argument("session", type=Path)
    commands.add_parser("doctor", help="Show engine and Python versions")
    args = parser.parse_args(argv)
    try:
        if args.command == "brief":
            from evals import briefs
            from evals.artifacts import read_json
            if args.brief_command == "init":
                result = briefs.create(args.path, answers=read_json(args.answers) if args.answers else None,
                                       project_root=args.project_root)
            elif args.brief_command == "update":
                result = briefs.update(args.path, read_json(args.answers))
            else:
                result = briefs.load(args.path)[0]
            if args.brief_command != "show":
                result = dict(briefs.readiness(result), brief=str(args.path.resolve()))
            print(json.dumps(result, indent=2))
            return int(args.brief_command == "check" and not result["ready"])
        elif args.command == "workflow":
            from evals import workflows
            if args.workflow_command == "status":
                result = workflows.status(args.directory)
            else:
                directory, result = workflows.start(args.brief, output=args.output)
                result = dict(result, directory=str(directory))
            print(json.dumps(result, indent=2))
            return int(bool(result.get("summary", {}).get("failed") or result.get("summary", {}).get("error")))
        elif args.command == "init":
            print(f"Created demo fixture suite: {initialize(args.directory)}")
            print("Replace the demo adapter and cases with your real application before assessing its quality.")
        elif args.command == "doctor":
            print(f"Evals {__version__}; Python {sys.version.split()[0]}; runtime dependencies: none")
        elif args.command == "validate":
            suite, _ = load_suite(args.suite)
            print(f"Valid suite: {suite['name']} ({len(suite['cases'])} cases)")
        elif args.command == "run":
            suite, root = load_suite(args.suite)
            store = Store(args.store)
            result = save_run(store, run_suite(suite, root, args.trials))
            alert_for_run(store, result)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = args.output or Path(".evals/runs") / f"{stamp}-{uuid.uuid4().hex[:8]}.json"
            write_report(path, result)
            counts = result["summary"]
            print(f"{result['suite']}: {counts['passed']} passed, {counts['failed']} failed, {counts['error']} errors")
            print(f"Report: {path.resolve()}")
            return int(counts["failed"] > 0 or counts["error"] > 0)
        elif args.command == "report":
            result = json.loads(args.path.read_text(encoding="utf-8-sig"))
            print(json.dumps(result, indent=2))
        elif args.command == "summarize":
            from evals.artifacts import read_json
            from evals.reporting import summarize_report
            result = summarize_report(read_json(args.path))
            if args.output:
                write_report(args.output, result)
            print(json.dumps(result, indent=2))
        elif args.command == "report-site":
            from evals.artifacts import read_json
            from evals.report_site import build_report_site
            result = build_report_site(read_json(args.path), args.output,
                                       read_json(args.baseline) if args.baseline else None)
            print(json.dumps(result, indent=2))
        elif args.command == "verify-snapshot":
            from evals.artifacts import read_json
            from evals.report_site import verify_snapshot
            print(f"Valid snapshot: {verify_snapshot(read_json(args.path))}")
        elif args.command == "diagnose":
            from evals.artifacts import read_json
            from evals.diagnostics import diagnose_report
            result = diagnose_report(read_json(args.path))
            if args.output:
                write_report(args.output, result)
            print(json.dumps(result, indent=2))
        elif args.command == "compare":
            from evals.artifacts import read_json
            from evals.reporting import compare_shared_reports
            baseline = read_json(args.baseline)
            candidate = read_json(args.candidate)
            difference = compare_shared_reports(baseline, candidate) if args.shared_only else compare_reports(baseline, candidate)
            if args.output:
                write_report(args.output, difference)
            print(json.dumps(difference, indent=2))
            if args.shared_only and not difference["shared_cases"]:
                return 2
            return int(bool(difference["regressions"] or difference["metric_regressions"]) or difference["candidate_errors"] > 0)
        elif args.command == "monitor":
            baseline = json.loads(args.baseline.read_text(encoding="utf-8-sig")) if args.baseline else None
            return monitor(args.suite, Store(args.store), args.interval, args.iterations, baseline)
        elif args.command == "history":
            print(json.dumps(Store(args.store).list(args.kind, args.limit, args.thread_id), indent=2))
        elif args.command == "ingest":
            record = json.loads(args.trace.read_text(encoding="utf-8-sig"))
            policy, root = load_policy(args.policy) if args.policy else (None, None)
            receipt = record_trace(record, Store(args.store), policy, root)
            print(json.dumps(receipt, indent=2))
            if receipt["run_id"]:
                result = Store(args.store).get("runs", receipt["run_id"])
                return int(result["summary"]["failed"] > 0 or result["summary"]["error"] > 0)
        elif args.command == "serve":
            from evals.server import make_server
            policy, root = load_policy(args.policy) if args.policy else (None, None)
            with make_server(port=args.port, store=Store(args.store), policy=policy, root=root) as server:
                print(f"Evals monitoring API: http://127.0.0.1:{server.server_port}", flush=True)
                server.serve_forever(poll_interval=0.2)
        elif args.command == "export":
            if args.output.exists():
                raise ValueError(f"Refusing to overwrite {args.output}")
            record = Store(args.store).get("traces", args.trace_id)
            if record is None:
                raise ValueError(f"Trace not found: {args.trace_id}")
            policy, root = load_policy(args.policy)
            for grader in policy["graders"]:
                if grader["type"] == "custom":
                    adapter = grader["adapter"]
                    if adapter["type"] == "python":
                        adapter["path"] = str((root / adapter["path"]).resolve())
                    else:
                        raise ValueError("Export command judges manually so their working directory remains explicit")
            suite = {"schema_version": 1, "name": f"captured-{record['name']}", "mode": "recorded",
                     "cases": [{"id": record["id"], "input": record.get("input"),
                                "observation": record["observation"], "graders": policy["graders"]}]}
            write_report(args.output, suite)
            print(f"Exported recorded suite: {args.output}")
        elif args.command == "improve":
            from evals import improvement
            if args.improve_command == "start":
                directory, state = improvement.start(args.suite, goal=args.goal, track=args.track,
                    lock=args.lock, regression_suites=args.regression_suite, max_attempts=args.max_attempts,
                    trials=args.trials, output=args.output, store=args.store, allow_partial=args.allow_partial)
                print(json.dumps({"session": str(directory), "goal": state["goal"],
                                  "brief": str(directory / "brief.md"), "max_attempts": state["max_attempts"]}, indent=2))
            elif args.improve_command == "check":
                attempt = improvement.check(args.session, hypothesis=args.hypothesis)
                print(json.dumps(attempt, indent=2))
                return int(not attempt["ready"])
            elif args.improve_command == "finish":
                decision = improvement.finish(args.session)
                print(json.dumps(decision, indent=2))
                return int(decision["status"] == "not_verified")
            elif args.improve_command == "brief":
                directory, _ = improvement.load_session(args.session)
                print((directory / "brief.md").read_text(encoding="utf-8"))
            else:
                _, state = improvement.load_session(args.session)
                print(json.dumps(state, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"evals: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("evals: interrupted", file=sys.stderr)
        return 130
    return 0
