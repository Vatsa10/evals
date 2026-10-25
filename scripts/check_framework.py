"""Run framework tests and expose failures as CI annotations as well as logs."""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover("tests"))
if os.environ.get("GITHUB_ACTIONS") == "true":
    for test, traceback in [*result.failures, *result.errors]:
        message = traceback.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        title = str(test).replace("%", "%25").replace(",", "%2C").replace("\n", " ").replace("\r", " ")
        print(f"::error title={title}::{message}")
raise SystemExit(not result.wasSuccessful())
