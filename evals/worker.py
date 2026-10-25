"""Execute one user adapter in a fresh Python process using a JSON protocol."""

import asyncio
from contextlib import redirect_stdout
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import traceback


def main():
    path, function = Path(sys.argv[1]).resolve(), sys.argv[2]
    payload = json.load(sys.stdin)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(path.parent))
    sys.path.insert(0, str(Path.cwd()))
    try:
        # Application logging belongs on stderr; stdout carries only JSON.
        with redirect_stdout(sys.stderr):
            spec = importlib.util.spec_from_file_location("evals_user_adapter", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            # Read the entrypoint directly: timestamp-based .pyc caches can reuse
            # old code when an agent makes a same-size edit within one second.
            exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
            result = getattr(module, function)(payload)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
        print(json.dumps(result, allow_nan=False))
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
