"""Live application adapter. Grading expectations are never passed to this code."""

import json
import os
from pathlib import Path
import tempfile

from evals import span, trace
from evals.storage import Store
from backend import tool_service
from model import ClaudeModel
import pipeline


def evaluate(request):
    data = request["input"]
    root = Path(__file__).parent
    documents = json.loads((root / "knowledge.json").read_text(encoding="utf-8"))
    mode = os.environ.get("EVALS_LAB_MODEL", "live")
    if mode == "fixture":
        from fixture_model import FixtureModel
        model = FixtureModel()
    elif mode == "live":
        model = ClaudeModel()
    else:
        raise ValueError("EVALS_LAB_MODEL must be live or fixture")
    store = Store(os.environ.get("EVALS_LAB_STORE", str(root / ".evals" / "traces.db")))
    with tempfile.TemporaryDirectory(prefix="evals-lab-service-") as folder:
        with tool_service(Path(folder) / "orders.db", data.get("fault")) as (url, backend):
            with trace("production-lab." + data["flow"], input=data,
                       thread_id=f"{request['case_id']}:{request['trial']}", store=store) as owner:
                with span(data["flow"], kind="agent", input=data) as current:
                    try:
                        observation = pipeline.run(data, model, documents, url)
                    except (ValueError, KeyError) as exc:
                        # A model contract violation is quality failure. Provider
                        # transport failures still propagate as evaluation errors.
                        observation = {"output": "", "result": {}, "status": "invalid_response",
                                       "contract_error": f"{type(exc).__name__}: {exc}"}
                    observation["ledger"] = backend.ledger()
                    observation["metadata"] = {"model_mode": mode, "model_calls": model.calls,
                                               "usage": model.usage, "model_ids": getattr(model, "model_ids", [])}
                    current.set_output({"status": observation["status"], "ledger": observation["ledger"]})
                owner.update(**observation)
            observation["trace"] = owner.record["spans"]
            observation["tools"] = owner.record["observation"].get("tools", [])
            if owner.receipt is None:
                raise RuntimeError("Trace persistence failed; no complete evidence was saved")
            observation["trace_id"] = owner.receipt["trace_id"]
            return observation
