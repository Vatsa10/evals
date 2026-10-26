"""Bootstrap only the explicitly installed trusted engine under python -I."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.verifier import execute

if __name__ == '__main__':
    print(json.dumps(execute(**json.load(sys.stdin)), allow_nan=False))
