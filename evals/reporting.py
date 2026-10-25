"""Pure provenance, coverage and comparison functions shared by CLI and report UI."""

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import math
from urllib.parse import urlsplit


ORIGINS = {"measured", "recorded", "imported", "provider_reported"}
STATUSES = {"passed", "failed", "error"}


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                     separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def validate_metadata(suite):
    categories = suite.get("coverage_categories", [])
    if not isinstance(categories, list) or any(not isinstance(c, str) or not c.strip() for c in categories) or len(set(categories)) != len(categories):
        raise ValueError("coverage_categories must be unique nonempty category names")
    for case in suite["cases"]:
        if "category" in case and (not isinstance(case["category"], str) or not case["category"].strip()):
            raise ValueError("Case category must be a nonempty string")
    provenance = suite.get("provenance", {})
    if not isinstance(provenance, dict) or set(provenance) - {"kind", "source_url", "evaluated_at", "label"}:
        raise ValueError("provenance supports kind, source_url, evaluated_at and label")
    origin = provenance.get("kind", "measured" if suite.get("mode", "live") == "live" else "recorded")
    if not isinstance(origin, str) or origin not in ORIGINS:
        raise ValueError("Unknown provenance kind")
    if suite.get("mode", "live") == "live" and origin != "measured":
        raise ValueError("Live adapter execution has measured provenance; use recorded mode for imported evidence")
    if suite.get("mode") == "recorded" and origin == "measured":
        raise ValueError("Replayed evidence cannot claim measured provenance")
    url = provenance.get("source_url")
    if url is not None:
        if not isinstance(url, str):
            raise ValueError("Provenance source_url must be an HTTP(S) URL")
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password:
            raise ValueError("Provenance source_url must be an HTTP(S) URL without credentials")
    if origin in {"imported", "provider_reported"} and not url:
        raise ValueError("Imported/provider-reported evidence requires source_url")
    if "label" in provenance and (not isinstance(provenance["label"], str) or not provenance["label"].strip()):
        raise ValueError("Provenance label must be a nonempty string")
    if "evaluated_at" in provenance:
        value = provenance["evaluated_at"]
        if not isinstance(value, str):
            raise ValueError("evaluated_at must be an ISO date or datetime")
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("evaluated_at must be an ISO date or datetime") from exc
    environment = suite.get("environment", {})
    if not isinstance(environment, dict) or set(environment) - {"provider", "model", "configuration"}:
        raise ValueError("environment supports provider, model and configuration")
    for key in ("provider", "model"):
        if key in environment and (not isinstance(environment[key], str) or not environment[key].strip()):
            raise ValueError(f"environment {key} must be a nonempty string")
    if "configuration" in environment and not isinstance(environment["configuration"], dict):
        raise ValueError("environment configuration must be an object")
    json.dumps(environment, allow_nan=False)


def run_provenance(suite, results, started_at):
    live = suite.get("mode", "live") == "live"
    providers, models, model_modes = set(), set(), set()
    for trial in results:
        metadata = trial.get("observation", {}).get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        provider = metadata.get("provider")
        if isinstance(provider, str) and provider:
            providers.add(provider)
        ids = metadata.get("model_ids", [])
        if isinstance(ids, list):
            models.update(m for m in ids if isinstance(m, str) and m)
        model_mode = metadata.get("model_mode")
        if isinstance(model_mode, str) and model_mode:
            model_modes.add(model_mode)
    return {"kind": "measured" if live else suite.get("provenance", {}).get("kind", "recorded"),
            "execution": "adapter_run" if live else "replay", "executed_at": started_at,
            "source": suite.get("provenance", {}), "declared_environment": suite.get("environment", {}),
            "adapter_reported": {"providers": sorted(providers), "model_ids": sorted(models), "model_modes": sorted(model_modes)}}


def validate_report(report):
    if not isinstance(report, dict) or type(report.get("schema_version")) is not int or report["schema_version"] != 1:
        raise ValueError("Unsupported report schema")
    if report.get("mode") not in {"live", "recorded"} or not isinstance(report.get("suite"), str):
        raise ValueError("Report requires suite name and live/recorded mode")
    trials, cases = report.get("trials"), report.get("cases")
    if not isinstance(trials, list) or not trials or not isinstance(cases, list) or not cases:
        raise ValueError("Report requires nonempty trials and cases")
    seen, by_case = set(), defaultdict(list)
    for trial in trials:
        if not isinstance(trial, dict) or not isinstance(trial.get("case_id"), str) or not trial["case_id"]:
            raise ValueError("Invalid trial case_id")
        if type(trial.get("trial")) is not int or trial["trial"] < 1 or trial.get("status") not in STATUSES:
            raise ValueError("Invalid trial number or status")
        key = (trial["case_id"], trial["trial"])
        if key in seen:
            raise ValueError("Duplicate trial")
        seen.add(key)
        by_case[trial["case_id"]].append(trial)
        if not isinstance(trial.get("graders"), list):
            raise ValueError("Trial graders must be a list")
        grader_ids = set()
        for verdict in trial["graders"]:
            if not isinstance(verdict, dict) or not isinstance(verdict.get("id"), str) or verdict.get("status") not in STATUSES | {"missing_evidence"}:
                raise ValueError("Invalid grader verdict")
            if not verdict["id"] or verdict["id"] in grader_ids:
                raise ValueError("Duplicate or empty grader id")
            grader_ids.add(verdict["id"])
            score = verdict.get("score")
            if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1):
                raise ValueError("Invalid grader score")
        if trial["graders"]:
            statuses = {g["status"] for g in trial["graders"]}
            outcome = "error" if statuses & {"error", "missing_evidence"} else "failed" if "failed" in statuses else "passed"
            if trial["status"] != outcome:
                raise ValueError("Trial status disagrees with grader evidence")
        elif trial["status"] != "error":
            raise ValueError("Successful/failed trials require grader evidence")
    ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if len(ids) != len(cases) or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids) or set(ids) != {t["case_id"] for t in trials}:
        raise ValueError("Report cases and trials disagree")
    validate_metadata({"mode": report["mode"], "cases": cases,
                       "coverage_categories": report.get("coverage_categories", [])})
    if "provenance" in report:
        provenance = report["provenance"]
        if not isinstance(provenance, dict) or not isinstance(provenance.get("kind"), str) or provenance["kind"] not in ORIGINS:
            raise ValueError("Invalid report provenance")
        source = provenance.get("source", {})
        if not isinstance(source, dict):
            raise ValueError("Invalid report provenance source")
        validate_metadata({"mode": report["mode"], "cases": cases,
                           "provenance": dict(source, kind=provenance["kind"]),
                           "environment": provenance.get("declared_environment", {})})
        if provenance.get("execution") != ("adapter_run" if report["mode"] == "live" else "replay"):
            raise ValueError("Provenance execution disagrees with report mode")
        observed = provenance.get("adapter_reported", {})
        if not isinstance(observed, dict) or any(
            not isinstance(observed.get(key, []), list) or any(not isinstance(v, str) for v in observed.get(key, []))
            for key in ("providers", "model_ids", "model_modes")):
            raise ValueError("Invalid adapter-reported model metadata")
    counts = Counter(t["status"] for t in trials)
    expected = {"total": len(trials), **{s: counts[s] for s in ("passed", "failed", "error")}, "success_rate": counts["passed"] / len(trials)}
    summary = report.get("summary", {})
    if not isinstance(summary, dict) or any(type(summary.get(key)) is not int for key in ("total", "passed", "failed", "error")) or isinstance(summary.get("success_rate"), bool) or summary != expected:
        raise ValueError("Report summary disagrees with trial evidence")
    for case in cases:
        rows = by_case[case["id"]]
        passed = sum(t["status"] == "passed" for t in rows)
        if any(type(case.get(key)) is not int for key in ("trials", "passed", "errors")) or isinstance(case.get("success_rate"), bool) or (case.get("trials"), case.get("passed"), case.get("errors"), case.get("success_rate")) != (len(rows), passed, sum(t["status"] == "error" for t in rows), passed / len(rows)):
            raise ValueError("Case summary disagrees with trial evidence")
    json.dumps(report, allow_nan=False)
    return by_case


def summarize_report(report):
    by_case = validate_report(report)
    rows = []
    for case in report["cases"]:
        trials = by_case[case["id"]]
        counts = Counter(t["status"] for t in trials)
        rows.append({"id": case["id"], "category": case.get("category", "uncategorized"),
                     "trials": len(trials), **{s: counts[s] for s in ("passed", "failed", "error")},
                     "success_rate": counts["passed"] / len(trials),
                     "status": "error" if counts["error"] else "failed" if counts["failed"] else "passed",
                     "failed_graders": sorted({g["id"] for t in trials for g in t["graders"] if g["status"] != "passed"})})
    categories = sorted(set(report.get("coverage_categories", [])) | {r["category"] for r in rows})
    coverage, category_rows = [], defaultdict(list)
    for row in rows:
        category_rows[row["category"]].append(row)
    for category in categories:
        members = category_rows[category]
        count = sum(r["trials"] for r in members)
        passed = sum(r["passed"] for r in members)
        coverage.append({"category": category, "cases": len(members), "trials": count,
                         **{s: sum(r[s] for r in members) for s in ("passed", "failed", "error")},
                         "success_rate": passed / count if count else None,
                         "evaluated_trials": sum(r["passed"] + r["failed"] for r in members),
                         "status": ("tested" if any(r["passed"] + r["failed"] for r in members) else "error") if count else "untested"})
    provenance = report.get("provenance") or {"kind": "unknown", "execution": "adapter_run" if report["mode"] == "live" else "replay",
                                               "source": {}, "declared_environment": {}, "adapter_reported": {}}
    return {"schema_version": 1, "suite": report["suite"], "mode": report["mode"],
            "started_at": report.get("started_at"), "dataset_sha256": report.get("dataset_sha256"),
            "engine_version": report.get("engine_version"), "summary": report["summary"],
            "provenance": provenance, "coverage": coverage, "cases": rows,
            "scope": "Observed cases and trials only; adapter execution does not establish live model inference."}


def compare_shared_reports(baseline, candidate):
    """Exploratory overlap only. Never used by the improvement verification gate."""
    validate_report(baseline)
    validate_report(candidate)
    if baseline["mode"] != candidate["mode"]:
        raise ValueError("Recorded and live reports cannot be compared")
    before = {c["id"] for c in baseline["cases"]}
    after = {c["id"] for c in candidate["cases"]}
    compatible, incompatible = [], []
    source_maps = []
    for report in (baseline, candidate):
        mapping = defaultdict(list)
        for source in report.get("custom_grader_sources", []):
            mapping[source["case_id"]].append(source)
        source_maps.append(mapping)
    for identifier in sorted(before & after):
        old = baseline.get("case_contracts", {}).get(identifier)
        new = candidate.get("case_contracts", {}).get(identifier)
        same_dataset = bool(baseline.get("dataset_sha256")) and baseline["dataset_sha256"] == candidate.get("dataset_sha256")
        same_contract = (old is not None and old == new) or (old is None and new is None and same_dataset)
        old_sources, new_sources = source_maps[0][identifier], source_maps[1][identifier]
        if same_contract and old_sources == new_sources and all(s.get("sha256") for s in old_sources):
            compatible.append(identifier)
        else:
            incompatible.append({"id": identifier, "reason": "Changed or unavailable case/grader contract"})
    difference = {"changes": [], "regressions": [], "improvements": [], "metric_changes": [],
                  "metric_regressions": [], "metric_improvements": [], "candidate_errors": 0}
    if compatible:
        from evals.engine import compare_reports

        def select(report):
            return dict(report, cases=[c for c in report["cases"] if c["id"] in compatible],
                        trials=[t for t in report["trials"] if t["case_id"] in compatible],
                        dataset_sha256=content_hash(compatible),
                        summary={"error": sum(t["status"] == "error" for t in report["trials"] if t["case_id"] in compatible)},
                        custom_grader_sources=sorted([s for s in report.get("custom_grader_sources", []) if s["case_id"] in compatible],
                                                     key=lambda s: (s["case_id"], s["grader_id"])))
        difference = compare_reports(select(baseline), select(candidate))
    return dict(difference, scope="shared_cases", verification_eligible=False,
                shared_cases=compatible, baseline_only=sorted(before - after), candidate_only=sorted(after - before),
                incompatible_cases=incompatible,
                warning="Exploratory comparison excludes one-sided/incompatible cases and cannot verify an improvement.")
