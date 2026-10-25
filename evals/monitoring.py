"""Offline monitoring and online scoring share the same engine and graders."""

import json
import math
from pathlib import Path
import time

from evals.engine import compare_reports, load_suite, run_suite, validate_observation
from evals.graders import validate_grader
from evals.storage import Store


def save_run(store, report):
    counts = report["summary"]
    report = dict(report, status="error" if counts["error"] else ("failed" if counts["failed"] else "passed"))
    return store.add("runs", report)


def alert_for_run(store, report, comparison=None):
    counts = report["summary"]
    if counts["failed"] or counts["error"] or (comparison and (comparison["regressions"] or comparison["metric_regressions"])):
        return store.add("alerts", {"run_id": report["id"], "name": report["suite"],
                                   "status": "open", "summary": counts, "comparison": comparison})
    return None


def monitor(suite_path, store=None, interval=60, iterations=None, baseline=None, emit=print):
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
        raise ValueError("Monitor interval must be a positive finite number")
    if iterations is not None and (type(iterations) is not int or iterations < 1):
        raise ValueError("Monitor iterations must be a positive integer")
    store = store or Store()
    failed, index, reference = False, 0, baseline
    while iterations is None or index < iterations:
        # Reload each time so updates to the suite and adapter are observed.
        suite, root = load_suite(suite_path)
        if suite.get("mode", "live") != "live":
            raise ValueError("Continuous monitoring requires a live suite")
        report = save_run(store, run_suite(suite, root))
        comparison = compare_reports(reference, report) if reference else None
        alert = alert_for_run(store, report, comparison)
        if reference is None:
            reference = report
        failed = failed or alert is not None
        emit(json.dumps({"run_id": report["id"], "iteration": index + 1,
                         "summary": report["summary"], "alert_id": alert["id"] if alert else None,
                         "regressions": comparison["regressions"] if comparison else [],
                         "metric_regressions": comparison["metric_regressions"] if comparison else []}))
        index += 1
        if iterations is None or index < iterations:
            time.sleep(interval)
    return int(failed)


def load_policy(path):
    path = Path(path).resolve()
    policy = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(policy, dict) or not isinstance(policy.get("graders"), list) or not policy["graders"]:
        raise ValueError("Online policy must contain a nonempty graders list")
    for grader in policy["graders"]:
        validate_grader(grader, path.parent)
    return policy, path.parent


def validate_trace(record):
    if not isinstance(record, dict) or not isinstance(record.get("name"), str) or not record["name"]:
        raise ValueError("Trace requires a nonempty name")
    if "thread_id" in record and record["thread_id"] is not None and not isinstance(record["thread_id"], str):
        raise ValueError("Trace thread_id must be a string")
    for key in ("id", "created_at", "started_at", "finished_at", "status"):
        if key in record and (not isinstance(record[key], str) or not record[key]):
            raise ValueError(f"Trace {key} must be a nonempty string")
    validate_observation(record.get("observation"))


def record_trace(record, store=None, policy=None, root=None):
    validate_trace(record)
    store = store or Store()
    # The policy is trusted local configuration; incoming traces never supply code.
    if policy:
        for grader in policy["graders"]:
            validate_grader(grader, Path(root or ".").resolve())
    trace_record = store.add("traces", record)
    if trace_record.get("status") == "error":
        store.add("alerts", {"trace_id": trace_record["id"], "name": trace_record["name"],
                             "status": "open", "reason": trace_record.get("error", "Request failed")})
    report = None
    if policy:
        suite = {"schema_version": 1, "name": policy.get("name", "online-evaluation"), "mode": "recorded",
                 "cases": [{"id": trace_record["id"], "input": trace_record.get("input"),
                            "observation": trace_record["observation"], "graders": policy["graders"]}]}
        report = run_suite(suite, root or Path.cwd())
        report["trace_id"] = trace_record["id"]
        report["thread_id"] = trace_record.get("thread_id")
        report = save_run(store, report)
        alert_for_run(store, report)
    return {"trace_id": trace_record["id"], "run_id": report["id"] if report else None}
