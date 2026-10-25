from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from evals.cli import main
from evals.diagnostics import diagnose_report
from evals.storage import Store
from examples.production_lab.backend import ToolError, refund_request, tool_service
from evals import trace
from scripts.production_lab import baseline, verify
from scripts.export_lab_evidence import export


class ProductionLabTests(unittest.TestCase):
    def test_all_categories_baseline_fix_reevaluate_and_monitor(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {}), redirect_stdout(io.StringIO()):
            root = Path(folder) / "lab"
            baseline(root, "fixture", 1)
            before = json.loads((root / ".evals/improvement/baseline-0.json").read_text())
            self.assertEqual(before["summary"], {"total": 16, "passed": 1, "failed": 15, "error": 0, "success_rate": 1 / 16})
            self.assertEqual(verify(root), 0)
            result = json.loads((root / ".evals/verification.json").read_text())
            self.assertEqual(result["candidate"]["passed"], 16)
            self.assertEqual(result["decision"], "verified_improvement")
            self.assertEqual([event["alert_id"] for event in result["monitor_events"]], [None, None])
            session = json.loads((root / ".evals/improvement/session.json").read_text())
            after = json.loads((root / ".evals/improvement/attempt-1-0.json").read_text())
            self.assertEqual(before["dataset_sha256"], after["dataset_sha256"])
            self.assertEqual(len(session["attempts"]), 1)
            exported = export(root, Path(folder) / "evidence.json")
            evidence = json.loads(exported.read_text())
            self.assertEqual(evidence["model_mode"], "fixture")
            self.assertEqual(evidence["candidate"][0]["summary"]["passed"], 16)
            self.assertEqual(evidence["source_changes"][0]["file"], "pipeline.py")
            self.assertNotIn(str(root), exported.read_text())
            store = Store(root / ".evals/traces.db")
            self.assertEqual(store.counts()["traces"], 44)
            candidate_traces = [trial["observation"] for trial in after["trials"]]
            lost = next(o for o in candidate_traces if any(s.get("error", "").endswith("response_lost_after_commit") for s in o["trace"]))
            self.assertEqual(len(lost["ledger"]), 1)
            self.assertEqual([s["status"] for s in lost["trace"] if s["name"] == "refund.http"], ["error", "ok"])

    def test_concurrent_delivery_is_atomic_and_key_cannot_change_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "traces.db")
            with tool_service(Path(folder) / "orders.db") as (url, backend):
                errors = []
                body = {"order_id": "O-100", "amount_cents": 2500, "key": "same-logical-request"}

                def deliver():
                    try:
                        with trace("delivery", store=store):
                            refund_request(url, "customer-a", body)
                    except Exception as exc:
                        errors.append(exc)

                threads = [Thread(target=deliver) for _ in range(4)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(5)
                self.assertFalse(any(thread.is_alive() for thread in threads))
                self.assertEqual(errors, [])
                self.assertEqual(len(backend.ledger()), 1)
                with trace("conflict", store=store), self.assertRaises(ToolError) as failure:
                    refund_request(url, "customer-a", {**body, "amount_cents": 5000})
                self.assertEqual(failure.exception.status, 409)
                with trace("denied", store=store), self.assertRaises(ToolError) as failure:
                    refund_request(url, "customer-b", body)
                self.assertEqual(failure.exception.status, 403)
                self.assertEqual(backend.ledger()[0]["amount_cents"], 2500)

    def test_diagnostics_include_failed_grader_error_component_and_bad_parent(self):
        report = {"suite": "agent", "summary": {"failed": 1}, "trials": [
            {"case_id": "timeout", "trial": 1, "status": "failed", "graders": [{"id": "truth", "status": "failed"}],
             "observation": {"trace_id": "persisted", "trace": [
                 {"id": "s1", "parent_id": "missing", "kind": "tool", "name": "http", "status": "error", "error": "503"}]}}]}
        diagnosis = diagnose_report(report)
        self.assertEqual(diagnosis["failures"][0]["error_spans"][0]["error"], "503")
        self.assertEqual(diagnosis["failures"][0]["trace_issues"], ["Unknown parent for http"])
        self.assertEqual(diagnosis["components"][0]["calls"], 1)
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            path, output = Path(folder) / "report.json", Path(folder) / "diagnosis.json"
            path.write_text(json.dumps(report))
            self.assertEqual(main(["diagnose", str(path), "--output", str(output)]), 0)
            self.assertEqual(json.loads(output.read_text()), diagnosis)


if __name__ == "__main__":
    unittest.main()
