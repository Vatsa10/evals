import asyncio
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from evals import observe, span, trace
from evals.cli import main
from evals.monitoring import monitor, record_trace
from evals.server import make_server
from evals.starter import initialize
from evals.storage import Store


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = Store(self.root / "history.db")
        self.policy = {"name": "format", "graders": [{"type": "json_valid"}]}

    def test_store_persists_and_filters_conversations(self):
        for thread in ("a", "b"):
            record_trace({"name": "request", "thread_id": thread, "observation": {"output": "hello"}}, self.store)
        reopened = Store(self.store.path)
        self.assertEqual(reopened.counts()["traces"], 2)
        self.assertEqual(len(reopened.list("traces", thread_id="a")), 1)

    def test_online_grading_and_alerts(self):
        receipt = record_trace({"name": "bad-answer", "observation": {"output": "not JSON"}}, self.store, self.policy)
        self.assertEqual(self.store.get("runs", receipt["run_id"])["summary"]["failed"], 1)
        self.assertEqual(self.store.list("alerts")[0]["run_id"], receipt["run_id"])

    def test_missing_online_evidence_is_error(self):
        receipt = record_trace({"name": "missing-answer", "observation": {}}, self.store, self.policy)
        self.assertEqual(self.store.get("runs", receipt["run_id"])["summary"]["error"], 1)

    def test_nested_spans_and_sync_decorator(self):
        @observe(kind="tool")
        def lookup(order_id):
            return {"order_id": order_id}

        with trace("support", thread_id="thread", store=self.store) as request:
            with span("agent", kind="agent") as agent:
                lookup("o1")
            request.update(output="done")
        saved = self.store.get("traces", request.receipt["trace_id"])
        self.assertEqual(saved["spans"][1]["parent_id"], agent.record["id"])
        self.assertEqual(saved["observation"]["tools"][0]["arguments"], {"order_id": "o1"})
        self.assertEqual(saved["thread_id"], "thread")

    def test_async_traces_do_not_share_context(self):
        @observe(kind="agent", store=self.store)
        async def respond(value):
            await asyncio.sleep(0)
            with span("child", kind="tool", input={"value": value}) as current:
                current.set_output(value)
            return str(value)

        async def both():
            return await asyncio.gather(respond(1), respond(2))

        self.assertEqual(asyncio.run(both()), ["1", "2"])
        records = self.store.list("traces")
        self.assertEqual(len(records), 2)
        self.assertEqual({r["observation"]["output"] for r in records}, {"1", "2"})
        for record in records:
            self.assertEqual(record["spans"][1]["parent_id"], record["spans"][0]["id"])

    def test_trace_preserves_application_exception(self):
        with self.assertRaisesRegex(RuntimeError, "application failed"):
            with trace("bad", store=self.store):
                with span("tool", kind="tool"):
                    raise RuntimeError("application failed")
        self.assertEqual(self.store.list("traces")[0]["status"], "error")
        self.assertEqual(self.store.counts()["alerts"], 1)

    def test_monitor_detects_regression_between_iterations(self):
        path = initialize(self.root / "demo")
        events = []

        def emit(event):
            events.append(json.loads(event))
            if len(events) == 1:
                app = path.parent / "app.py"
                app.write_text(app.read_text().replace('"Paris"', '"Lyon"'), encoding="utf-8")

        code = monitor(path, self.store, interval=0.001, iterations=2, emit=emit)
        self.assertEqual(code, 1)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["regressions"][0]["id"], "llm-answer")
        self.assertEqual(self.store.counts()["runs"], 2)
        self.assertEqual(self.store.counts()["alerts"], 1)

    def test_http_ingestion_and_history(self):
        server = make_server(port=0, store=self.store, policy=self.policy)
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}"
        data = json.dumps({"name": "online", "observation": {"output": "{}"}}).encode()
        with urlopen(Request(url + "/api/traces", data=data, headers={"Content-Type": "application/json"}), timeout=5) as response:
            self.assertEqual(response.status, 201)
            self.assertIsNotNone(json.load(response)["run_id"])
        with urlopen(url + "/api/runs", timeout=5) as response:
            self.assertEqual(json.load(response)["items"][0]["summary"]["passed"], 1)
        with urlopen(url + "/health", timeout=5) as response:
            self.assertEqual(json.load(response)["counts"]["traces"], 1)
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(url + "/api/traces", data=data, headers={"Origin": "https://example.com"}), timeout=5)
        self.assertEqual(error.exception.code, 403)

    def test_export_roundtrip(self):
        receipt = record_trace({"name": "capture", "observation": {"output": "{}"}}, self.store)
        policy_path, output = self.root / "policy.json", self.root / "captured.json"
        policy_path.write_text(json.dumps(self.policy))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["export", receipt["trace_id"], "--policy", str(policy_path),
                                   "--output", str(output), "--store", str(self.store.path)]), 0)
            self.assertEqual(main(["run", str(output), "--output", str(self.root / "report.json"),
                                   "--store", str(self.store.path)]), 0)

    def test_clean_plugin_build_excludes_development_and_reference_files(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "build_plugin.py"
        spec = importlib.util.spec_from_file_location("builder", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        built = module.build(self.root / "marketplace")
        plugin = built / "plugins" / "evals"
        self.assertTrue((plugin / "scripts" / "evals.py").is_file())
        for excluded in (".git", ".upstream", ".venv", ".evals", "tests"):
            self.assertFalse((plugin / excluded).exists())
        self.assertEqual(json.loads((built / ".claude-plugin" / "marketplace.json").read_text())["plugins"][0]["source"], "./plugins/evals")


if __name__ == "__main__":
    unittest.main()
