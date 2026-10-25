"""JSON-in/JSON-out Python and command adapters, shared by targets and judges."""

import json
import math
import os
from pathlib import Path
import subprocess
import sys


def reject_constant(value):
    raise ValueError(f"Invalid JSON number: {value}")


def validate_adapter(config, root):
    if not isinstance(config, dict):
        raise ValueError("Adapter must be an object")
    timeout = config.get("timeout_seconds", 60)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Adapter timeout_seconds must be a positive finite number")
    kind = config.get("type")
    if kind == "python":
        path = config.get("path")
        function = config.get("function", "evaluate")
        if not isinstance(path, str) or not (root / path).is_file():
            raise ValueError(f"Python adapter file does not exist: {path!r}")
        if not isinstance(function, str) or not function.isidentifier():
            raise ValueError("Python adapter function must be a function name")
    elif kind == "command":
        argv = config.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
            raise ValueError("Command adapter argv must be a nonempty list of strings")
    else:
        raise ValueError(f"Unknown adapter type: {kind!r}")


def invoke(config, payload, root):
    validate_adapter(config, root)
    if config["type"] == "python":
        argv = [sys.executable, str(Path(__file__).with_name("worker.py")),
                str((root / config["path"]).resolve()), config.get("function", "evaluate")]
    else:
        argv = [sys.executable if part == "{python}" else part for part in config["argv"]]
    environment = os.environ.copy()
    environment.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        process = subprocess.run(
            argv, input=json.dumps(payload, allow_nan=False), cwd=root,
            text=True, encoding="utf-8", capture_output=True,
            timeout=config.get("timeout_seconds", 60), check=False, env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Adapter timed out after {config.get('timeout_seconds', 60)} seconds") from exc
    if process.returncode:
        raise RuntimeError(f"Adapter exited {process.returncode}: {process.stderr[-4000:].strip()}")
    try:
        return json.loads(process.stdout, parse_constant=reject_constant)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Adapter stdout must contain exactly one JSON value") from exc
