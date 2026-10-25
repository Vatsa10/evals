from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evals.artifacts import read_json, write_json
from evals.briefs import create, load, readiness, update
from evals.cli import main
from evals.engine import run_suite
from evals.improvement import check, finish
from evals.storage import Store
from evals.workflows import start, status


class GuidedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        # Windows runners may provide an 8.3 TEMP alias; the brief loader returns
        # the canonical project root, so compare canonical paths in these checks.
        self.root = Path(self.folder.name).resolve()
        self.app = self.root / "app.py"
        self.app.write_text('def evaluate(request):\n return {"output":"wrong"}\n')
        self.suite = {"schema_version": 1, "name": "actual-app", "mode": "live",
                      "target": {"type": "python", "path": "app.py"}, "cases": [
                          {"id": "answer", "input": "question", "graders": [{"type": "equals", "expected": "answer"}]}]}
        write_json(self.root / "suite.json", self.suite)
        self.path = self.root / "evaluations" / "brief.json"
        self.answers = {"mode": "evaluate", "target": "Application response", "goal": "Answer the request correctly",
                        "success_criteria": ["Return answer for the representative request"], "system_types": ["llm"],
                        "assets": {"entrypoint": "app.py:evaluate", "suite": "suite.json"},
                        "execution": {"environment": "local", "side_effects": "none"}}

    def brief(self, answers=None):
        return create(self.path, answers=answers or self.answers, project_root=self.root)

    def test_draft_is_durable_and_never_overwrites_answers(self):
        draft = create(self.path, project_root=self.root)
        pending = readiness(draft)
        self.assertFalse(pending["ready"])
        self.assertIn("goal", pending["missing"])
        self.assertEqual(load(self.path)[1], self.root)
        update(self.path, {"target": "Known app", "goal": "Known goal"})
        update(self.path, {"mode": "evaluate"})
        saved = load(self.path)[0]
        self.assertEqual(saved["goal"], "Known goal")
        self.assertNotIn("goal", readiness(saved)["missing"])
        with self.assertRaisesRegex(ValueError, "already exists"):
            create(self.path)

    def test_incomplete_intake_does_not_call_target_or_create_workflow(self):
        create(self.path, project_root=self.root)
        output = self.root / "workflow"
        with patch("evals.workflows.run_suite") as invoke, self.assertRaisesRegex(ValueError, "incomplete"):
            start(self.path, output=output)
        invoke.assert_not_called()
        self.assertFalse(output.exists())

    def test_evaluate_only_saves_evidence_and_preserves_application(self):
        self.brief()
        before = self.app.read_bytes()
        directory, manifest = start(self.path, output=self.root / "workflow")
        self.assertEqual(manifest["summary"]["failed"], 1)
        self.assertEqual(self.app.read_bytes(), before)
        self.assertEqual(manifest["planned_target_calls"], 1)
        self.assertTrue((directory / "review/index.html").is_file())
        self.assertEqual(Store(directory / "history.db").counts()["alerts"], 1)

    def test_execution_requires_real_integration_even_after_intake_is_ready(self):
        answers = deepcopy(self.answers)
        answers["assets"]["suite"] = None
        self.assertTrue(readiness(self.brief(answers))["ready"])
        with self.assertRaisesRegex(ValueError, "real suite/adapter"):
            start(self.path, output=self.root / "workflow")
        self.assertFalse((self.root / "workflow").exists())

    def test_improvement_freezes_brief_and_preserves_attempt_budget(self):
        answers = self.answers | {"mode": "improve", "constraints": {"allowed_changes": ["app.py"], "max_attempts": 2, "max_target_calls": 3}}
        self.brief(answers)
        directory, manifest = start(self.path, output=self.root / "workflow")
        self.assertEqual(manifest["planned_target_calls"], 3)
        session = Path(manifest["session"])
        self.app.write_text('def evaluate(request):\n return {"output":"answer"}\n')
        result = check(session, hypothesis="Fix the app response")
        self.assertTrue(result["ready"])
        self.assertEqual(finish(session)["status"], "verified_improvement")
        self.assertEqual(status(directory)["decision"]["status"], "verified_improvement")
        self.assertEqual(status(directory)["attempts_used"], 1)

    def test_changing_agreed_brief_invalidates_candidate_before_execution(self):
        self.brief(self.answers | {"mode": "improve", "constraints": {"allowed_changes": ["app.py"]}})
        _, manifest = start(self.path, output=self.root / "workflow")
        update(self.path, {"goal": "Changed goal"})
        with self.assertRaisesRegex(ValueError, "contract changed"):
            check(manifest["session"], hypothesis="Try to use changed intent")

    def test_plan_budget_is_checked_before_any_application_calls(self):
        self.brief(self.answers | {"mode": "improve", "constraints": {"allowed_changes": ["app.py"], "max_target_calls": 1}})
        with patch("evals.workflows.start_improvement") as invoke, self.assertRaisesRegex(ValueError, "budget"):
            start(self.path, output=self.root / "workflow")
        invoke.assert_not_called()
        self.assertFalse((self.root / "workflow").exists())

    def test_allowed_change_files_cannot_escape_the_project(self):
        self.brief(self.answers | {"mode": "improve", "constraints": {"allowed_changes": ["../outside.py"]}})
        with self.assertRaisesRegex(ValueError, "inside project_root"):
            start(self.path, output=self.root / "workflow")

    def test_report_mode_needs_no_provider_scope_or_new_target_calls(self):
        report = run_suite(self.suite, self.root)
        write_json(self.root / "report.json", report)
        self.brief({"mode": "report", "target": "Saved run", "goal": "Review failures", "assets": {"reports": ["report.json"]}})
        with patch("evals.workflows.run_suite") as invoke:
            _, manifest = start(self.path, output=self.root / "workflow")
        invoke.assert_not_called()
        self.assertEqual(manifest["status"], "report_ready")
        self.assertEqual(manifest["planned_target_calls"], 0)

    def test_capture_ingestion_is_labeled_without_claiming_new_live_calls(self):
        write_json(self.root / "trace.json", {"name": "captured", "observation": {"output": "answer"}})
        self.brief({"mode": "trace", "target": "Captured request", "goal": "Inspect the trace", "assets": {"traces": ["trace.json"]}})
        directory, manifest = start(self.path, output=self.root / "workflow")
        self.assertEqual(manifest["status"], "traces_recorded")
        self.assertEqual(manifest["planned_target_calls"], 0)
        self.assertEqual(Store(directory / "history.db").counts()["traces"], 1)

    def test_live_trace_mode_requires_actual_component_evidence(self):
        self.brief(self.answers | {"mode": "trace"})
        with self.assertRaisesRegex(ValueError, "Trace evidence is missing"):
            start(self.path, output=self.root / "workflow")
        self.assertEqual(read_json(self.root / "workflow/workflow.json")["status"], "error")
        self.assertTrue((self.root / "workflow/report.json").is_file())

    def test_live_trace_mode_runs_instrumented_entrypoint_and_persists_spans(self):
        self.app.write_text('''from pathlib import Path
from evals import trace, span, Store
def evaluate(request):
    with trace("actual-request", store=Store(Path(__file__).with_name("traces.db"))) as owner:
        with span("actual-component", kind="tool") as component:
            component.set_output("answer")
        owner.update(output="answer")
    return {"output":"answer", "trace":owner.record["spans"]}
''')
        self.brief(self.answers | {"mode": "trace"})
        directory, manifest = start(self.path, output=self.root / "workflow")
        self.assertEqual(manifest["summary"]["passed"], 1)
        self.assertEqual(read_json(directory / "report.json")["trials"][0]["observation"]["trace"][0]["name"], "actual-component")
        self.assertEqual(Store(self.root / "traces.db").counts()["traces"], 1)

    def test_invalid_answers_are_rejected_without_replacing_the_saved_brief(self):
        self.brief()
        before = self.path.read_bytes()
        for answers in ({"constraints": {"trials": True}}, {"mode": "autofix-everything"}, {"unknown": True}):
            with self.assertRaises(ValueError):
                update(self.path, answers)
            self.assertEqual(self.path.read_bytes(), before)

    def test_cli_draft_ready_execution_and_existing_output_protection(self):
        answers = self.root / "answers.json"
        write_json(answers, self.answers)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["brief", "init", str(self.path), "--project-root", str(self.root)]), 0)
            self.assertEqual(main(["brief", "check", str(self.path)]), 1)
            self.assertEqual(main(["brief", "update", str(self.path), "--from", str(answers)]), 0)
            self.assertEqual(main(["brief", "check", str(self.path)]), 0)
            self.assertEqual(main(["workflow", "start", str(self.path), "--output", str(self.root / "workflow")]), 1)
            self.assertEqual(main(["workflow", "status", str(self.root / "workflow")]), 1)
            self.assertEqual(main(["workflow", "start", str(self.path), "--output", str(self.root / "workflow")]), 2)


if __name__ == "__main__":
    unittest.main()
