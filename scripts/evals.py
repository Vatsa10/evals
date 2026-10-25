"""Run the packaged engine from any project without installing dependencies."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.cli import main

raise SystemExit(main())
