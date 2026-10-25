from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from evals.adapters import invoke
from evals.cli import main
from evals.engine import compare_reports, run_suite, validate_suite
from evals.graders import MissingEvidence, grade, resolve
from evals.starter import initialize


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def recorded(self, observation=None, graders=None):
        return {"schema_version": 1, "name": "test", "mode": "recorded",
                "cases": [{"id": "case", "input": "question",
                           "observation": observation if observation is not None else {"output": "answer"},
                           "graders": graders if graders is not None else [{"type": "equals", "expected": "answer"}]}]}

    def write_adapter(self, source, filename="adapter.py"):
        (self.root / filename).write_text(source, encoding="utf-8")
        return {"type": "python", "path": filename, "function": "evaluate"}

    def live(self, adapter, graders=None):
        suite = self.recorded(graders=graders)
        suite.update(mode="live", target=adapter)
        del suite["cases"][0]["observation"]
        return suite

    def test_demo_runs_all_four_use_cases(self):
        path = initialize(self.root / "suite")
        suite = json.loads(path.read_text())
        report = run_suite(suite, path.parent, trials=2)
        self.assertEqual(report["summary"], {"total": 8, "passed": 8, "failed": 0, "error": 0, "success_rate": 1.0})
        self.assertEqual(len(report["cases"]), 4)

    def test_repeat_starts_fresh_python_and_excludes_grading_data(self):
        adapter = self.write_adapter('''counter = 0
async def evaluate(request):
    global counter
    counter += 1
    assert "graders" not in request and "expected" not in request
    print("application log")
    return {"output": str(counter)}
''')
        report = run_suite(self.live(adapter, [{"type": "equals", "expected": "1"}]), self.root, 3)
        self.assertEqual(report["summary"]["passed"], 3)
        self.assertTrue(all(t["target_duration_ms"] >= 0 for t in report["trials"]))

    def test_command_adapter_protocol(self):
        (self.root / "command.py").write_text('import json,sys\nr=json.load(sys.stdin)\nprint(json.dumps({"output": r["input"]}))\n')
        adapter = {"type": "command", "argv": ["{python}", "command.py"]}
        self.assertEqual(invoke(adapter, {"input": "hello"}, self.root), {"output": "hello"})

    def test_unicode_application_logging_preserves_results(self):
        adapter = self.write_adapter('def evaluate(request):\n    print("नमस्ते 世界")\n    return {"output": "नमस्ते 世界"}\n')
        report = run_suite(self.live(adapter, [{"type": "equals", "expected": "नमस्ते 世界"}]), self.root)
        self.assertEqual(report["summary"]["passed"], 1)

    def test_missing_state_is_error_and_other_graders_still_run(self):
        suite = self.recorded(graders=[{"type": "equals", "path": "/state/status", "expected": "processed"},
                                       {"type": "equals", "expected": "answer"}])
        report = run_suite(suite, self.root)
        self.assertEqual(report["summary"]["error"], 1)
        verdicts = report["trials"][0]["graders"]
        self.assertEqual([v["status"] for v in verdicts], ["missing_evidence", "passed"])

    def test_failed_grade_is_not_infrastructure_error(self):
        report = run_suite(self.recorded({"output": "wrong"}), self.root)
        self.assertEqual(report["summary"]["failed"], 1)
        self.assertEqual(report["summary"]["error"], 0)

    def test_recorded_replays_do_not_measure_reliability(self):
        with self.assertRaisesRegex(ValueError, "one trial"):
            run_suite(self.recorded(), self.root, trials=2)

    def test_adapter_timeout_is_reported(self):
        adapter = self.write_adapter('import time\ndef evaluate(request):\n    time.sleep(5)\n    return {"output":"answer"}\n')
        adapter["timeout_seconds"] = 0.05
        report = run_suite(self.live(adapter), self.root)
        self.assertEqual(report["summary"]["error"], 1)
        self.assertIn("timed out", report["trials"][0]["error"])

    def test_invalid_target_observation_is_error(self):
        adapter = self.write_adapter('def evaluate(request):\n    return "not an observation"\n')
        report = run_suite(self.live(adapter), self.root)
        self.assertEqual(report["summary"]["error"], 1)

    def test_command_noise_and_nonzero_exit_are_errors(self):
        for source in ('print("not JSON")', 'import sys\nprint("broken", file=sys.stderr)\nsys.exit(7)'):
            (self.root / "command.py").write_text(source)
            adapter = {"type": "command", "argv": ["{python}", "command.py"]}
            report = run_suite(self.live(adapter), self.root)
            self.assertEqual(report["summary"]["error"], 1)

    def test_command_adapter_rejects_nonstandard_json_numbers(self):
        (self.root / "command.py").write_text('print(\'{"score": 1, "reason": "bad evidence", "evidence": NaN}\')')
        adapter = {"type": "command", "argv": ["{python}", "command.py"]}
        report = run_suite(self.recorded(graders=[{"type": "custom", "adapter": adapter}]), self.root)
        self.assertEqual(report["summary"]["error"], 1)
        json.dumps(report, allow_nan=False)

    def test_same_size_source_edit_executes_current_code(self):
        adapter = self.write_adapter('def evaluate(request):\n    return {"output": "first"}\n')
        suite = self.live(adapter, [{"type": "equals", "expected": "first"}])
        baseline = run_suite(suite, self.root)
        path = self.root / "adapter.py"
        timestamp = path.stat().st_mtime_ns
        self.write_adapter('def evaluate(request):\n    return {"output": "other"}\n')
        os.utime(path, ns=(timestamp, timestamp))
        candidate = run_suite(suite, self.root)
        self.assertEqual(candidate["summary"]["failed"], 1)
        self.assertNotEqual(baseline["target_source_sha256"], candidate["target_source_sha256"])

    def test_json_pointer_escaping_null_and_missing(self):
        self.assertIsNone(resolve({"a/b": {"~key": None}}, "/a~1b/~0key"))
        with self.assertRaises(MissingEvidence):
            resolve({"items": [1]}, "/items/-1")
        with self.assertRaises(ValueError):
            resolve({}, "/bad~2key")

    def test_all_graders_are_required(self):
        suite = self.recorded(graders=[{"type": "equals", "expected": "answer"},
                                       {"type": "contains", "expected": "missing"}])
        report = run_suite(suite, self.root)
        self.assertEqual(report["summary"]["passed"], 0)
        self.assertEqual(report["summary"]["failed"], 1)

    def test_tool_order_and_repeated_call_matching(self):
        actual = {"tools": [{"name": "refund"}, {"name": "verify"}]}
        config = {"type": "tool_calls", "ordered": True, "expected": [{"name": "verify"}, {"name": "refund"}]}
        self.assertEqual(grade(config, actual, {}, self.root)["status"], "failed")
        config["ordered"] = False
        self.assertEqual(grade(config, actual, {}, self.root)["status"], "passed")
        config["expected"] = [{"name": "refund"}, {"name": "refund"}]
        self.assertEqual(grade(config, actual, {}, self.root)["status"], "failed")

    def test_tool_arguments_and_extra_calls(self):
        actual = {"tools": [{"name": "refund", "arguments": {"order_id": "wrong"}}, {"name": "log"}]}
        config = {"type": "tool_calls", "expected": [{"name": "refund", "arguments": {"order_id": "o1"}}]}
        self.assertEqual(grade(config, actual, {}, self.root)["score"], 0)
        config["expected"] = [{"name": "refund"}]
        config["allow_extra"] = False
        self.assertEqual(grade(config, actual, {}, self.root)["score"], 0)

    def test_tool_arguments_do_not_coerce_booleans_to_numbers(self):
        config = {"type": "tool_calls", "expected": [{"name": "refund", "arguments": {"amount": 1}}]}
        observation = {"tools": [{"name": "refund", "arguments": {"amount": True}}]}
        self.assertEqual(grade(config, observation, {}, self.root)["score"], 0)

    def test_retrieval_uses_unique_document_ids(self):
        evidence = {"retrieval_context": [{"id": "a"}, {"id": "a"}, {"id": "b"}]}
        for kind, wanted in (("retrieval_precision", 0.5), ("retrieval_recall", 0.5)):
            config = {"type": kind, "expected": ["a", "c"], "threshold": 0.5}
            self.assertEqual(grade(config, evidence, {}, self.root)["score"], wanted)

    def test_text_json_and_numeric_checks(self):
        cases = [({"type": "contains", "expected": "ans"}, {"output": "answer"}, 1),
                 ({"type": "regex", "expected": "^answer$"}, {"output": "answer"}, 1),
                 ({"type": "json_valid"}, {"output": '{"valid":true}'}, 1),
                 ({"type": "json_valid"}, {"output": "NaN"}, 0),
                 ({"type": "max_value", "path": "/usage/tokens", "expected": 200}, {"usage": {"tokens": 201}}, 0),
                 ({"type": "equals", "path": "/value", "expected": 1}, {"value": True}, 0)]
        for config, observation, score in cases:
            with self.subTest(config=config):
                self.assertEqual(grade(config, observation, {}, self.root)["score"], score)

    def test_custom_judge_returns_evidence(self):
        adapter = self.write_adapter('def evaluate(request):\n    assert request["rubric"] == "helpful"\n    return {"score": 0.8, "reason": "Human-calibrated example", "evidence": request["observation"]["output"]}\n')
        suite = self.recorded(graders=[{"type": "custom", "adapter": adapter, "rubric": "helpful", "threshold": 0.7}])
        report = run_suite(suite, self.root)
        verdict = report["trials"][0]["graders"][0]
        self.assertEqual(verdict["status"], "passed")
        self.assertEqual(verdict["evidence"], "answer")

    def test_bad_custom_judge_score_is_error(self):
        adapter = self.write_adapter('def evaluate(request):\n    return {"score": True, "reason": "bad score"}\n')
        report = run_suite(self.recorded(graders=[{"type": "custom", "adapter": adapter}]), self.root)
        self.assertEqual(report["summary"]["error"], 1)

    def test_comparison_rejects_changed_grading_contract(self):
        baseline = run_suite(self.recorded(), self.root)
        changed = self.recorded(graders=[{"type": "equals", "expected": "new"}])
        with self.assertRaisesRegex(ValueError, "different inputs"):
            compare_reports(baseline, run_suite(changed, self.root))

    def test_comparison_finds_real_output_regression(self):
        baseline = run_suite(self.recorded(), self.root)
        candidate = run_suite(self.recorded({"output": "wrong"}), self.root)
        comparison = compare_reports(baseline, candidate)
        self.assertEqual(comparison["regressions"][0]["delta"], -1)

    def test_changed_custom_grader_code_requires_new_baseline(self):
        adapter = self.write_adapter('def evaluate(request):\n    return {"score": 1, "reason": "first"}\n')
        suite = self.recorded(graders=[{"type": "custom", "adapter": adapter}])
        before = run_suite(suite, self.root)
        self.write_adapter('def evaluate(request):\n    return {"score": 1, "reason": "other"}\n')
        with self.assertRaisesRegex(ValueError, "Custom grader code changed"):
            compare_reports(before, run_suite(suite, self.root))

    def test_configuration_rejects_empty_duplicate_and_invalid_checks(self):
        invalid = []
        suite = self.recorded()
        suite["cases"] = []
        invalid.append(suite)
        suite = self.recorded()
        suite["cases"].append(deepcopy(suite["cases"][0]))
        invalid.append(suite)
        for graders in ([], [{"type": "equals"}], [{"type": "regex", "expected": "["}],
                        [{"type": "equals", "expected": "answer", "threshold": 0}],
                        [{"type": "equals", "expected": "answer", "path": "/bad~2path"}]):
            invalid.append(self.recorded(graders=graders))
        for suite in invalid:
            with self.subTest(suite=suite), self.assertRaises(ValueError):
                validate_suite(suite, self.root)

    def test_init_does_not_overwrite_user_files(self):
        (self.root / "app.py").write_text("user data")
        with self.assertRaises(ValueError):
            initialize(self.root)
        self.assertFalse((self.root / "suite.json").exists())
        self.assertEqual((self.root / "app.py").read_text(), "user data")

    def test_cli_exit_codes_and_saved_report(self):
        path, report = self.root / "suite.json", self.root / "report.json"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            path.write_text(json.dumps(self.recorded()))
            self.assertEqual(main(["run", str(path), "--output", str(report)]), 0)
            self.assertEqual(json.loads(report.read_text())["summary"]["passed"], 1)
            path.write_text(json.dumps(self.recorded({"output": "wrong"})))
            self.assertEqual(main(["run", str(path), "--output", str(report)]), 1)
            path.write_text("{}")
            self.assertEqual(main(["run", str(path)]), 2)

    def test_plugin_shim_runs_from_a_different_working_directory(self):
        shim = Path(__file__).resolve().parents[1] / "scripts" / "evals.py"
        process = subprocess.run([sys.executable, str(shim), "doctor"], cwd=self.root,
                                 capture_output=True, text=True, check=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("runtime dependencies: none", process.stdout)


if __name__ == "__main__":
    unittest.main()
