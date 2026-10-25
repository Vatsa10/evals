"""Summarize observed failures and component evidence without guessing causality."""

from collections import Counter


def diagnose_report(report):
    failures = []
    components = Counter()
    for trial in report["trials"]:
        observation = trial.get("observation", {})
        spans = observation.get("trace", [])
        ids = {item.get("id") for item in spans if isinstance(item, dict)}
        errors, invalid = [], []
        for item in spans:
            if not isinstance(item, dict):
                invalid.append("Span is not an object")
                continue
            components[(item.get("kind", "custom"), item.get("name", "unnamed"))] += 1
            if item.get("parent_id") and item["parent_id"] not in ids:
                invalid.append(f"Unknown parent for {item.get('name', 'unnamed')}")
            if item.get("status") == "error":
                errors.append({key: item.get(key) for key in ("id", "parent_id", "name", "kind", "error")})
        if trial["status"] != "passed":
            failures.append({"case_id": trial["case_id"], "trial": trial["trial"],
                             "status": trial["status"], "error": trial.get("error"),
                             "failed_graders": [g for g in trial["graders"] if g["status"] != "passed"],
                             "error_spans": errors, "trace_issues": invalid,
                             "trace_id": observation.get("trace_id"), "span_count": len(spans)})
    return {"suite": report["suite"], "summary": report["summary"], "failures": failures,
            "components": [{"kind": kind, "name": name, "calls": count}
                           for (kind, name), count in sorted(components.items())],
            "interpretation": "Observed evidence only. A failed or recovered component is a diagnostic lead, not proof of root cause."}
