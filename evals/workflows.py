"""Execute a ready project brief through the existing evaluation primitives."""

from pathlib import Path
import uuid

from evals.artifacts import read_json, write_json
from evals.briefs import load, readiness
from evals.engine import load_suite, run_suite
from evals.improvement import start as start_improvement
from evals.monitoring import alert_for_run, record_trace, save_run
from evals.report_site import build_report_site
from evals.reporting import summarize_report
from evals.storage import Store, utc_now


def start(brief_path, *, output=None):
    brief_path = Path(brief_path).resolve()
    brief, root = load(brief_path)
    status = readiness(brief)
    if not status["ready"]:
        raise ValueError("Brief is incomplete: " + ", ".join(status["missing"]))
    mode, assets, constraints = brief["mode"], brief["assets"], brief["constraints"]
    resolve = lambda name: (root / name).resolve()
    specs, reports, traces = [], [], []
    if mode in ("evaluate", "improve") or mode == "trace" and not assets["traces"]:
        if not assets["suite"]:
            raise ValueError("Create a real suite/adapter and save assets.suite before execution; no demo is substituted")
        names = [assets["suite"], *(assets["regression_suites"] if mode == "improve" else [])]
        for name in names:
            suite, directory = load_suite(resolve(name))
            if mode in ("improve", "trace") and suite.get("mode", "live") != "live":
                raise ValueError("Improvement and live tracing require live suites")
            if suite.get("mode", "live") == "recorded" and constraints["trials"] != 1:
                raise ValueError("Recorded evidence cannot be repeated to estimate reliability")
            specs.append((resolve(name), suite, directory))
    elif mode == "report":
        reports = [read_json(resolve(name)) for name in assets["reports"]]
        for report in reports:
            summarize_report(report)
    else:
        from evals.monitoring import validate_trace
        traces = [read_json(resolve(name)) for name in assets["traces"]]
        for record in traces:
            validate_trace(record)
    batch_calls = sum(len(s["cases"]) * constraints["trials"] for _, s, _ in specs if s.get("mode", "live") == "live")
    planned_calls = batch_calls * (1 + constraints["max_attempts"] if mode == "improve" else 1)
    if planned_calls > constraints["max_target_calls"]:
        raise ValueError(f"Plan needs up to {planned_calls} target adapter calls; brief budget is {constraints['max_target_calls']}. Adjust the plan before execution.")
    tracked = [resolve(p) for p in constraints["allowed_changes"]] if mode == "improve" else []
    if any(not p.is_relative_to(root) or not p.is_file() for p in tracked):
        raise ValueError("allowed_changes must name existing application files inside project_root")
    for name in assets["locked_files"]:
        if not resolve(name).is_file():
            raise ValueError(f"Locked reference is not a file: {name}")
    directory = Path(output).resolve() if output else root / ".evals" / "workflows" / uuid.uuid4().hex[:12]
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "request.json", brief)
    manifest = {"schema_version": 1, "id": uuid.uuid4().hex, "created_at": utc_now(), "mode": mode,
                "status": "running", "brief": str(brief_path), "project_root": str(root),
                "planned_target_calls": planned_calls, "max_target_calls": constraints["max_target_calls"]}
    write_json(directory / "workflow.json", manifest)
    try:
        store = Store(directory / "history.db")
        if mode == "improve":
            session, state = start_improvement(specs[0][0], goal=brief["goal"], track=tracked,
                regression_suites=[s[0] for s in specs[1:]], trials=constraints["trials"],
                max_attempts=constraints["max_attempts"], output=directory / "improvement", store=store.path,
                lock=[brief_path, directory / "request.json", *[resolve(p) for p in assets["locked_files"]]])
            manifest.update(status="baseline_ready", session=str(session),
                            baseline_reports=[str(session / p) for p in state["baseline_reports"]],
                            next_action="Read the failure brief, make the authorized application change, then use improve check/finish")
        elif specs:
            _, suite, suite_root = specs[0]
            report = save_run(store, run_suite(suite, suite_root, constraints["trials"]))
            alert_for_run(store, report)
            write_json(directory / "report.json", report)
            write_json(directory / "summary.json", summarize_report(report))
            if mode == "trace" and any(not trial.get("observation", {}).get("trace") for trial in report["trials"]):
                raise ValueError("Trace evidence is missing; instrument the real entrypoint before claiming tracing success. See report.json.")
            site = build_report_site(report, directory / "review")
            manifest.update(status="evaluation_complete", report=str(directory / "report.json"),
                            summary=report["summary"], report_site=site)
        elif reports:
            site = build_report_site(reports[-1], directory / "review", reports[0] if len(reports) == 2 else None)
            manifest.update(status="report_ready", report_site=site)
        else:
            receipts = [record_trace(record, store) for record in traces]
            manifest.update(status="traces_recorded", receipts=receipts,
                            next_action="Inspect captured evidence; ingestion does not prove a new live request was executed")
    except BaseException as exc:
        manifest.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "error", error=f"{type(exc).__name__}: {exc}")
        write_json(directory / "workflow.json", manifest)
        raise
    write_json(directory / "workflow.json", manifest)
    return directory, manifest


def status(directory):
    manifest = read_json(Path(directory) / "workflow.json")
    if manifest.get("session"):
        session = Path(manifest["session"])
        state = read_json(session / "session.json")
        manifest["improvement_status"] = state["status"]
        manifest["attempts_used"] = len(state["attempts"])
        if (session / "decision.json").exists():
            manifest["decision"] = read_json(session / "decision.json")
    return manifest
