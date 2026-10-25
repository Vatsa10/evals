from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evals.cli import main
from evals.engine import compare_reports, run_suite
from evals.improvement import check, finish, load_session, start


class ImprovementTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.app = self.root / "app.py"
        self.write_app("wrong")
        self.suite = {"schema_version": 1, "name": "response-quality", "mode": "live",
                      "target": {"type": "python", "path": "app.py"},
                      "cases": [{"id": "answer", "input": "question",
                                 "graders": [{"id": "correct", "type": "equals", "expected": "answer"}]}]}
        self.suite_path = self.root / "suite.json"
        self.suite_path.write_text(json.dumps(self.suite))

    def write_app(self, value):
        self.app.write_text(f'def evaluate(request):\n    return {{"output": {value!r}}}\n', encoding="utf-8")

    def begin(self, **kwargs):
        return start(self.suite_path, goal="Return the correct answer", track=[self.app],
                     output=self.root / "session", store=self.root / "history.db", **kwargs)[0]

    def test_complete_loop_preserves_baseline_and_records_patch(self):
        session = self.begin()
        self.assertIn("wrong", (session / "brief.md").read_text())
        self.write_app("answer")
        candidate = check(session, hypothesis="Fix the application's response")
        self.assertTrue(candidate["ready"])
        decision = finish(session)
        self.assertEqual(decision["status"], "verified_improvement")
        self.assertIn("+    return", decision["changed_files"][0]["diff"])
        state = load_session(session)[1]
        baseline = json.loads((session / state["baseline_reports"][0]).read_text())
        self.assertEqual(baseline["summary"]["failed"], 1)
        self.assertEqual(finish(session), decision)

    def test_modified_cases_are_rejected_before_spending_an_attempt(self):
        session = self.begin()
        self.suite["cases"][0]["graders"][0]["expected"] = "wrong"
        self.suite_path.write_text(json.dumps(self.suite))
        with self.assertRaisesRegex(ValueError, "contract changed"):
            check(session, hypothesis="Weaken the expected answer")
        self.assertEqual(len(load_session(session)[1]["attempts"]), 0)

    def test_custom_grader_and_extra_rubric_are_locked(self):
        judge = self.root / "judge.py"
        judge.write_text('def evaluate(request):\n    return {"score": 0, "reason": "fail"}\n')
        self.suite["cases"][0]["graders"] = [{"type": "custom", "adapter": {"type": "python", "path": "judge.py"}}]
        self.suite_path.write_text(json.dumps(self.suite))
        rubric = self.root / "rubric.txt"
        rubric.write_text("Correctness is required")
        session = self.begin(lock=[rubric])
        rubric.write_text("Anything is fine")
        with self.assertRaisesRegex(ValueError, "contract changed"):
            check(session, hypothesis="Change rubric")
        rubric.write_text("Correctness is required")
        judge.write_text('def evaluate(request):\n    return {"score": 1, "reason": "pass"}\n')
        with self.assertRaisesRegex(ValueError, "contract changed"):
            check(session, hypothesis="Change judge")

    def test_application_changed_after_check_cannot_be_verified(self):
        session = self.begin()
        self.write_app("answer")
        self.assertTrue(check(session, hypothesis="Fix output")["ready"])
        self.write_app("untested change")
        self.assertEqual(finish(session)["status"], "not_verified")
        self.assertEqual(load_session(session)[1]["status"], "active")

    def test_revert_to_previously_checked_candidate_selects_that_attempt(self):
        session = self.begin()
        self.write_app("answer")
        check(session, hypothesis="Correct response")
        self.write_app("worse")
        self.assertFalse(check(session, hypothesis="A failed alternative")["ready"])
        self.write_app("answer")
        self.assertEqual(finish(session)["selected_attempt"], 1)

    def test_budget_is_enforced(self):
        session = self.begin(max_attempts=1)
        check(session, hypothesis="First attempt")
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            check(session, hypothesis="Unbounded retry")

    def test_interrupted_attempt_still_counts_and_never_verifies(self):
        session = self.begin(max_attempts=1)
        self.write_app("answer")
        with patch("evals.improvement.evaluate_specs", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                check(session, hypothesis="Interrupted run")
        self.assertEqual(load_session(session)[1]["attempts"][0]["status"], "interrupted")
        self.assertEqual(finish(session)["status"], "not_verified")
        self.assertFalse((session / ".lock").exists())

    def test_regression_suite_blocks_otherwise_successful_change(self):
        regression = deepcopy(self.suite)
        regression["name"] = "preserve-working-behavior"
        regression["cases"][0]["graders"][0]["expected"] = "wrong"
        path = self.root / "regression.json"
        path.write_text(json.dumps(regression))
        session = self.begin(regression_suites=[path])
        self.write_app("answer")
        candidate = check(session, hypothesis="Fix one thing and break another")
        self.assertFalse(candidate["ready"])
        self.assertIn("regressed", candidate["reason"])
        self.assertEqual(finish(session)["status"], "not_verified")

    def test_existing_success_does_not_claim_an_improvement(self):
        self.write_app("answer")
        session = self.begin()
        decision = finish(session)
        self.assertEqual(decision["status"], "baseline_satisfied")
        self.assertIsNone(decision["selected_attempt"])

    def test_random_success_without_application_change_is_not_an_improvement(self):
        self.app.write_text('''from pathlib import Path
def evaluate(request):
    counter = Path("counter.txt")
    seen = counter.exists()
    counter.write_text("seen")
    return {"output": "answer" if seen else "wrong"}
''')
        session = self.begin()
        candidate = check(session, hypothesis="Retry without changing anything")
        self.assertTrue(candidate["improved"])
        self.assertFalse(candidate["ready"])
        self.assertIn("No tracked application change", candidate["reason"])

    def test_session_lock_prevents_overlapping_checks(self):
        session = self.begin()
        (session / ".lock").touch()
        with self.assertRaisesRegex(ValueError, "busy"):
            check(session, hypothesis="Concurrent attempt")

    def test_recorded_observations_cannot_verify_a_fix(self):
        self.suite.update(mode="recorded")
        del self.suite["target"]
        self.suite["cases"][0]["observation"] = {"output": "answer"}
        self.suite_path.write_text(json.dumps(self.suite))
        with self.assertRaisesRegex(ValueError, "live suites"):
            self.begin()

    def test_metric_regression_is_detected_even_when_both_cases_pass(self):
        judge = self.root / "judge.py"
        judge.write_text('def evaluate(request):\n    return {"score": float(request["observation"]["output"]), "reason": "quality"}\n')
        self.suite["cases"][0]["graders"] = [{"id": "quality", "type": "custom", "threshold": 0.5,
            "adapter": {"type": "python", "path": "judge.py"}}]
        self.write_app("0.9")
        before = run_suite(self.suite, self.root)
        self.write_app("0.6")
        comparison = compare_reports(before, run_suite(self.suite, self.root))
        self.assertEqual(comparison["regressions"], [])
        self.assertEqual(len(comparison["metric_regressions"]), 1)
        self.assertAlmostEqual(comparison["metric_regressions"][0]["score_delta"], -0.3)

    def test_cli_flow(self):
        session = self.root / "cli-session"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["improve", "start", str(self.suite_path), "--goal", "Correct answer",
                "--track", str(self.app), "--output", str(session), "--store", str(self.root / "history.db")]), 0)
            self.write_app("answer")
            self.assertEqual(main(["improve", "check", str(session), "--hypothesis", "Fix app"]), 0)
            self.assertEqual(main(["improve", "finish", str(session)]), 0)


if __name__ == "__main__":
    unittest.main()
