"""Minimal container-side adapter. No grading code, labels, state or signing key."""

import asyncio
from contextlib import redirect_stdout
import importlib.util
import inspect
import json
from pathlib import Path
import sys


def main():
    path = Path('/app') / sys.argv[1]
    payload = json.load(sys.stdin)
    # Startup already completed under -I; application imports are now explicit.
    sys.path[:0] = [str(path.parent), '/app']
    with redirect_stdout(sys.stderr):
        spec = importlib.util.spec_from_file_location('application', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
        result = getattr(module, sys.argv[2])(payload)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
