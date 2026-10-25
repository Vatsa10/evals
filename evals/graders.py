"""Deterministic graders and a provider-neutral custom judge protocol."""

import json
import math
import re

from evals.adapters import invoke, reject_constant, validate_adapter


TYPES = {"equals", "contains", "regex", "json_valid", "max_value", "tool_calls",
         "retrieval_precision", "retrieval_recall", "custom"}


class MissingEvidence(ValueError):
    pass


def resolve(document, pointer):
    """Resolve a JSON Pointer, preserving the difference between absent and null."""
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("Evidence path must be a JSON Pointer, such as /output")
    value = document
    for token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", token):
            raise ValueError(f"Invalid JSON Pointer escape: {pointer}")
        key = token.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(value, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", key):
                    raise KeyError(key)
                value = value[int(key)]
            elif isinstance(value, dict):
                value = value[key]
            else:
                raise KeyError(key)
        except (KeyError, IndexError) as exc:
            raise MissingEvidence(f"Missing evidence at {pointer}") from exc
    return value


def validate_grader(config, root):
    if not isinstance(config, dict) or config.get("type") not in TYPES:
        raise ValueError(f"Unknown grader type: {config!r}")
    kind = config["type"]
    threshold = config.get("threshold", 1.0)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError("Grader threshold must be greater than 0 and at most 1")
    if kind not in {"json_valid", "custom"} and "expected" not in config:
        raise ValueError(f"{kind} grader requires expected")
    pointer = config.get("path", "/output")
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")) or re.search(r"~(?![01])", pointer):
        raise ValueError("Grader path must be a valid JSON Pointer")
    expected = config.get("expected")
    if kind in {"contains", "regex"} and not isinstance(expected, str):
        raise ValueError(f"{kind} grader expected must be a string")
    if kind == "regex":
        try:
            re.compile(expected)
        except re.error as exc:
            raise ValueError(f"Invalid grader regular expression: {exc}") from exc
    if kind == "max_value" and (isinstance(expected, bool) or not isinstance(expected, (int, float)) or not math.isfinite(expected)):
        raise ValueError("max_value expected must be a finite number")
    if kind == "tool_calls":
        if not isinstance(expected, list) or not expected or not all(isinstance(t, dict) and isinstance(t.get("name"), str) for t in expected):
            raise ValueError("tool_calls expected must be a nonempty list of named tools")
        for flag in ("ordered", "allow_extra"):
            if flag in config and not isinstance(config[flag], bool):
                raise ValueError(f"tool_calls {flag} must be boolean")
    if kind in {"retrieval_precision", "retrieval_recall"}:
        if not isinstance(expected, list) or not expected or not all(isinstance(x, str) for x in expected):
            raise ValueError("Retrieval expected must be a nonempty list of relevant document IDs")
    if kind == "custom":
        validate_adapter(config.get("adapter"), root)


def tool_score(actual, expected, ordered, allow_extra):
    if not isinstance(actual, list) or not all(isinstance(t, dict) and isinstance(t.get("name"), str) for t in actual):
        raise ValueError("Tool evidence must be a list of named tool-call objects")
    if not allow_extra and len(actual) != len(expected):
        return 0.0
    used, cursor = set(), 0
    for wanted in expected:
        candidates = range(cursor, len(actual)) if ordered else range(len(actual))
        match = next((i for i in candidates if i not in used and
                      all(k in actual[i] and json.dumps(actual[i][k], sort_keys=True) ==
                          json.dumps(v, sort_keys=True) for k, v in wanted.items())), None)
        if match is None:
            return 0.0
        used.add(match)
        cursor = match + 1
    return 1.0


def grade(config, observation, case, root):
    kind = config["type"]
    defaults = {"tool_calls": "/tools", "retrieval_precision": "/retrieval_context", "retrieval_recall": "/retrieval_context"}
    pointer = config.get("path", defaults.get(kind, "/output"))
    expected = config.get("expected")
    if kind == "custom":
        verdict = invoke(config["adapter"], {
            "case": case, "observation": observation, "rubric": config.get("rubric", "")
        }, root)
        if not isinstance(verdict, dict):
            raise ValueError("Custom grader must return a verdict object")
        score, reason = verdict.get("score"), verdict.get("reason")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Custom grader score must be a finite number between 0 and 1")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Custom grader must provide a reason")
        evidence = verdict.get("evidence")
    else:
        evidence = resolve(observation, pointer)
        if kind == "equals":
            # bool and number have different meanings in JSON.
            score = float(json.dumps(evidence, sort_keys=True) == json.dumps(expected, sort_keys=True))
        elif kind in {"contains", "regex", "json_valid"}:
            if not isinstance(evidence, str):
                raise ValueError(f"{kind} requires string evidence")
            if kind == "contains":
                score = float(expected in evidence)
            elif kind == "regex":
                score = float(re.search(expected, evidence) is not None)
            else:
                try:
                    json.loads(evidence, parse_constant=reject_constant)
                    score = 1.0
                except ValueError:
                    score = 0.0
        elif kind == "max_value":
            if isinstance(evidence, bool) or not isinstance(evidence, (int, float)) or not math.isfinite(evidence):
                raise ValueError("max_value requires finite numeric evidence")
            score = float(evidence <= expected)
        elif kind == "tool_calls":
            score = tool_score(evidence, expected, config.get("ordered", False), config.get("allow_extra", True))
        else:
            if not isinstance(evidence, list) or not all(isinstance(d, dict) and isinstance(d.get("id"), str) for d in evidence):
                raise ValueError("Retrieval evidence must be a list of document objects with string IDs")
            retrieved, relevant = {d["id"] for d in evidence}, set(expected)
            denominator = len(retrieved) if kind == "retrieval_precision" else len(relevant)
            score = len(retrieved & relevant) / denominator if denominator else 0.0
        reason = f"{kind} at {pointer}: score {score:g}, threshold {config.get('threshold', 1):g}"
    return {"status": "passed" if score >= config.get("threshold", 1) else "failed",
            "score": score, "reason": reason, "evidence": evidence}
