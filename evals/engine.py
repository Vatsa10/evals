"""Suite validation, trial execution, and evidence-backed local reports."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from evals import __version__
from evals.adapters import invoke, reject_constant, validate_adapter
from evals.graders import MissingEvidence, grade, validate_grader


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def load_suite(path):
    path = Path(path).resolve()
    suite = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
    validate_suite(suite, path.parent)
    return suite, path.parent


def validate_suite(suite, root):
    if not isinstance(suite, dict) or type(suite.get("schema_version")) is not int or suite["schema_version"] != 1:
        raise ValueError("Suite schema_version must be 1")
    if not isinstance(suite.get("name"), str) or not suite["name"].strip():
        raise ValueError("Suite requires a name")
    mode = suite.get("mode", "live")
    if mode not in {"live", "recorded"}:
        raise ValueError("Suite mode must be live or recorded")
    trials = suite.get("trials", 1)
    if type(trials) is not int or trials < 1:
        raise ValueError("Suite trials must be a positive integer")
    if mode == "recorded":
        if trials != 1 or "target" in suite:
            raise ValueError("Recorded suites require one trial and no target; replay does not measure reliability")
    else:
        validate_adapter(suite.get("target"), root)
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Suite cases must be a nonempty list")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"].strip():
            raise ValueError("Each case requires a nonempty string id")
        if case["id"] in seen:
            raise ValueError(f"Duplicate case id: {case['id']}")
        seen.add(case["id"])
        if "input" not in case:
            raise ValueError(f"Case {case['id']} requires input")
        if mode == "recorded":
            validate_observation(case.get("observation"))
        elif "observation" in case:
            raise ValueError("Live cases cannot contain a recorded observation")
        graders = case.get("graders")
        if not isinstance(graders, list) or not graders:
            raise ValueError(f"Case {case['id']} must have at least one grader")
        grader_ids = set()
        for index, config in enumerate(graders):
            validate_grader(config, root)
            grader_id = config.get("id", str(index + 1))
            if not isinstance(grader_id, str) or not grader_id or grader_id in grader_ids:
                raise ValueError(f"Invalid or duplicate grader id in {case['id']}")
            grader_ids.add(grader_id)


def validate_observation(observation):
    if not isinstance(observation, dict):
        raise ValueError("Target observation must be a JSON object")
    if "output" in observation and not isinstance(observation["output"], str):
        raise ValueError("Observation output must be a string")
    for key in ("tools", "retrieval_context", "messages", "trace"):
        if key in observation and not isinstance(observation[key], list):
            raise ValueError(f"Observation {key} must be a list")
    if "messages" in observation:
        for message in observation["messages"]:
            if not isinstance(message, dict) or not isinstance(message.get("role"), str) or not isinstance(message.get("content"), str):
                raise ValueError("Each message requires string role and content")
    json.dumps(observation, allow_nan=False)


def source_digest(adapter, root):
    if adapter and adapter.get("type") == "python":
        return hashlib.sha256((root / adapter["path"]).read_bytes()).hexdigest()
    return None


def run_suite(suite, root, trials=None):
    root = Path(root).resolve()
    suite = json.loads(json.dumps(suite, allow_nan=False))
    if trials is not None:
        suite["trials"] = trials
    validate_suite(suite, root)
    started = datetime.now(timezone.utc).isoformat()
    target_source = source_digest(suite.get("target"), root)
    custom_sources = [{"case_id": case["id"], "grader_id": g.get("id", str(i + 1)),
                       "sha256": source_digest(g.get("adapter"), root)}
                      for case in suite["cases"] for i, g in enumerate(case["graders"])
                      if g["type"] == "custom"]
    results = []
    for case in suite["cases"]:
        for trial in range(1, suite.get("trials", 1) + 1):
            timer = time.perf_counter()
            result = {"case_id": case["id"], "trial": trial, "graders": []}
            try:
                if suite.get("mode", "live") == "recorded":
                    observation = case["observation"]
                else:
                    # References and grading criteria are not sent to the target.
                    observation = invoke(suite["target"], {
                        "case_id": case["id"], "trial": trial,
                        "input": case["input"], "context": case.get("context"),
                    }, root)
                result["target_duration_ms"] = (round((time.perf_counter() - timer) * 1000, 3)
                                                if suite.get("mode", "live") == "live" else None)
                validate_observation(observation)
                result["observation"] = observation
                for index, config in enumerate(case["graders"]):
                    verdict = {"id": config.get("id", str(index + 1)), "type": config["type"]}
                    try:
                        verdict.update(grade(config, observation, case, root))
                    except MissingEvidence as exc:
                        verdict.update(status="missing_evidence", score=None, reason=str(exc))
                    except Exception as exc:
                        verdict.update(status="error", score=None, reason=f"{type(exc).__name__}: {exc}")
                    result["graders"].append(verdict)
                statuses = {g["status"] for g in result["graders"]}
                result["status"] = "error" if statuses & {"missing_evidence", "error"} else ("failed" if "failed" in statuses else "passed")
            except Exception as exc:
                result.update(status="error", error=f"{type(exc).__name__}: {exc}")
            result["duration_ms"] = round((time.perf_counter() - timer) * 1000, 3)
            results.append(result)
    counts = Counter(r["status"] for r in results)
    per_case = []
    for case in suite["cases"]:
        attempts = [r for r in results if r["case_id"] == case["id"]]
        passed = sum(r["status"] == "passed" for r in attempts)
        per_case.append({"id": case["id"], "trials": len(attempts), "passed": passed,
                         "errors": sum(r["status"] == "error" for r in attempts),
                         "success_rate": passed / len(attempts),
                         "any_trial_passed": passed > 0, "all_trials_passed": passed == len(attempts)})
    # Compare the same inputs and grading contract; execution settings may vary.
    dataset = [{k: v for k, v in case.items() if k != "observation"} for case in suite["cases"]]
    return {"schema_version": 1, "engine_version": __version__, "suite": suite["name"],
            "mode": suite.get("mode", "live"), "started_at": started,
            "suite_sha256": digest(suite), "dataset_sha256": digest(dataset),
            "target": suite.get("target"), "target_source_sha256": target_source,
            "custom_grader_sources": custom_sources,
            "summary": {"total": len(results), **{s: counts[s] for s in ("passed", "failed", "error")},
                        "success_rate": counts["passed"] / len(results)},
            "cases": per_case, "trials": results}


def compare_reports(baseline, candidate):
    if baseline.get("schema_version") != 1 or candidate.get("schema_version") != 1:
        raise ValueError("Unsupported report schema")
    if not baseline.get("dataset_sha256") or baseline["dataset_sha256"] != candidate.get("dataset_sha256"):
        raise ValueError("Reports have different inputs or grading criteria; use the same dataset")
    if baseline.get("mode") != candidate.get("mode"):
        raise ValueError("Recorded and live reports cannot be compared")
    if baseline.get("custom_grader_sources") != candidate.get("custom_grader_sources"):
        raise ValueError("Custom grader code changed; rerun the baseline with the same graders")
    before = {c["id"]: c for c in baseline["cases"]}
    after = {c["id"]: c for c in candidate["cases"]}
    if before.keys() != after.keys():
        raise ValueError("Reports contain different cases")
    changes = [{"id": key, "baseline": before[key]["success_rate"],
                "candidate": after[key]["success_rate"],
                "delta": after[key]["success_rate"] - before[key]["success_rate"]}
               for key in before]
    return {"regressions": [c for c in changes if c["delta"] < 0],
            "improvements": [c for c in changes if c["delta"] > 0],
            "candidate_errors": candidate["summary"]["error"], "changes": changes}
