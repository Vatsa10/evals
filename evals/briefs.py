"""Durable, validated intake shared by people, Claude Code, Codex and the CLI."""

from copy import deepcopy
import os
from pathlib import Path

from evals.artifacts import read_json, write_json


TEMPLATE = {"schema_version": 1, "project_root": ".", "mode": None, "target": None,
            "goal": None, "success_criteria": [], "system_types": [],
            "assets": {"entrypoint": None, "suite": None, "regression_suites": [],
                       "reports": [], "traces": [], "examples": [], "locked_files": []},
            "constraints": {"max_attempts": 3, "trials": 1, "max_target_calls": 100,
                            "allowed_changes": [], "notes": []},
            "execution": {"environment": None, "side_effects": None}}


def validate(brief):
    if not isinstance(brief, dict) or set(brief) != set(TEMPLATE) or type(brief.get("schema_version")) is not int or brief["schema_version"] != 1:
        raise ValueError("Invalid brief schema; use brief init and supported fields")
    for key in ("project_root", "target", "goal"):
        value = brief[key]
        if value is None and key != "project_root":
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Brief {key} must be a nonempty string or null")
    if brief["mode"] is not None and brief["mode"] not in ("evaluate", "improve", "trace", "report"):
        raise ValueError("Brief mode must be evaluate, improve, trace or report")
    for section in ("assets", "constraints", "execution"):
        if not isinstance(brief[section], dict) or set(brief[section]) != set(TEMPLATE[section]):
            raise ValueError(f"Invalid brief {section} fields")
    lists = [brief["success_criteria"], brief["system_types"],
             *[brief["assets"][k] for k in ("regression_suites", "reports", "traces", "examples", "locked_files")],
             brief["constraints"]["allowed_changes"], brief["constraints"]["notes"]]
    if any(not isinstance(items, list) or any(not isinstance(x, str) or not x.strip() for x in items) for items in lists):
        raise ValueError("Brief list fields must contain nonempty strings")
    for key in ("entrypoint", "suite"):
        value = brief["assets"][key]
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"Brief assets.{key} must be a nonempty string or null")
    for key in ("max_attempts", "trials", "max_target_calls"):
        if type(brief["constraints"][key]) is not int or brief["constraints"][key] < 1:
            raise ValueError(f"Brief constraints.{key} must be a positive integer")
    if brief["execution"]["environment"] not in (None, "local", "staging", "production"):
        raise ValueError("Unknown execution environment")
    if brief["execution"]["side_effects"] not in (None, "none", "sandboxed", "authorized"):
        raise ValueError("Unknown side-effect scope")
    if len(brief["assets"]["reports"]) > 2:
        raise ValueError("Supply one report, or baseline then candidate")


def merge(brief, answers):
    if not isinstance(answers, dict) or set(answers) - set(TEMPLATE):
        raise ValueError("Unknown brief answer fields")
    result = deepcopy(brief)
    for key, value in answers.items():
        if key in ("assets", "constraints", "execution"):
            if not isinstance(value, dict) or set(value) - set(TEMPLATE[key]):
                raise ValueError(f"Unknown brief {key} answer fields")
            result[key].update(value)
        else:
            result[key] = value
    validate(result)
    return result


def create(path, *, answers=None, project_root=None):
    path = Path(path).resolve()
    if path.exists():
        raise ValueError("Brief already exists; use brief update to preserve existing answers")
    result = merge(TEMPLATE, answers or {})
    if project_root is not None or not answers or "project_root" not in answers:
        result["project_root"] = os.path.relpath(Path(project_root or Path.cwd()).resolve(), path.parent)
    validate(result)
    write_json(path, result)
    return result


def load(path):
    path = Path(path).resolve()
    brief = read_json(path)
    validate(brief)
    root = (path.parent / brief["project_root"]).resolve()
    if not root.is_dir():
        raise ValueError("Brief project_root is not an existing directory")
    return brief, root


def update(path, answers):
    brief, _ = load(path)
    result = merge(brief, answers)
    write_json(path, result)
    return result


def readiness(brief):
    validate(brief)
    questions = []

    def need(field, condition, question, options=None):
        if not condition:
            item = {"field": field, "question": question}
            if options:
                item["options"] = options
            questions.append(item)

    mode, assets = brief["mode"], brief["assets"]
    need("mode", mode, "Should I evaluate only, implement improvements, add tracing, or prepare reports?",
         ["evaluate", "improve", "trace", "report"])
    need("target", brief["target"], "Which application or component should this work target?")
    need("goal", brief["goal"], "What exact behavior or failure do you want to measure or improve?")
    if mode in ("evaluate", "improve"):
        need("success_criteria", brief["success_criteria"], "What should a correct result do? Give acceptance rules or representative examples.")
        need("assets.entrypoint", assets["entrypoint"] or assets["suite"], "Where is the real application entrypoint or existing evaluation suite?")
    if mode == "improve":
        need("constraints.allowed_changes", brief["constraints"]["allowed_changes"], "Which application or prompt files may be changed?")
    if mode == "report":
        need("assets.reports", assets["reports"], "Which saved report should I use? For comparison, provide baseline then candidate.")
    if mode == "trace":
        need("assets.entrypoint", assets["entrypoint"] or assets["suite"] or assets["traces"], "Which real entrypoint should I instrument, or which existing trace should I inspect?")
    calls_app = mode in ("evaluate", "improve") or mode == "trace" and not assets["traces"]
    if calls_app:
        need("execution.environment", brief["execution"]["environment"], "Which environment may the evaluated application use?", ["local", "staging", "production"])
        need("execution.side_effects", brief["execution"]["side_effects"], "Are application actions read-only, isolated in a sandbox, or explicitly authorized writes?", ["none", "sandboxed", "authorized"])
    return {"ready": not questions, "mode": mode, "target": brief["target"],
            "missing": [q["field"] for q in questions], "questions": questions,
            "constraints": brief["constraints"],
            "next_action": "Inspect/create the real integration, then run workflow start" if not questions else "Ask only unanswered questions; retain project discoveries and prior answers"}
