from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

from evals.artifacts import read_json, write_json
from evals.cli import main
from evals.engine import compare_reports, run_suite
from evals.report_site import build_report_site, build_snapshot, verify_snapshot
from evals.reporting import compare_shared_reports, summarize_report


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def suite(self):
        return {"schema_version": 1, "name": "application", "mode": "recorded",
                "coverage_categories": ["llm", "rag", "tools"], "cases": [
                    {"id": "answer", "category": "llm", "input": "question", "observation": {"output": "correct"},
                     "graders": [{"id": "correct", "type": "equals", "expected": "correct"}]},
                    {"id": "retrieval", "category": "rag", "input": "find policy", "observation": {"output": "wrong"},
                     "graders": [{"id": "correct", "type": "equals", "expected": "correct"}]}]}

    def report(self, suite=None):
        return run_suite(suite or self.suite(), self.root)

    def test_coverage_distinguishes_failed_and_untested_categories(self):
        report = self.report()
        categories = {r["category"]: r for r in report["coverage"]}
        self.assertEqual(categories["llm"]["success_rate"], 1)
        self.assertEqual(categories["rag"]["success_rate"], 0)
        self.assertIsNone(categories["tools"]["success_rate"])
        self.assertEqual(categories["tools"]["status"], "untested")
        self.assertEqual(report["provenance"]["execution"], "replay")

    def test_imported_evidence_requires_source_and_never_claims_live_inference(self):
        suite = self.suite()
        suite["provenance"] = {"kind": "provider_reported", "source_url": "https://example.org/results", "evaluated_at": "2026-10-25"}
        report = self.report(suite)
        self.assertEqual(report["provenance"]["kind"], "provider_reported")
        self.assertEqual(report["provenance"]["execution"], "replay")
        suite["provenance"]["kind"] = "measured"
        with self.assertRaisesRegex(ValueError, "Replayed"):
            self.report(suite)

    def test_adapter_reported_model_identity_stays_distinct_from_declaration(self):
        (self.root / "app.py").write_text('def evaluate(request):\n return {"output":"correct","metadata":{"provider":"actual-port","model_ids":["model-b"],"model_mode":"fixture"}}\n')
        suite = self.suite()
        suite.update(mode="live", trials=2, target={"type": "python", "path": "app.py"},
                     environment={"provider": "declared-provider", "model": "model-a", "configuration": {"temperature": 0}})
        for case in suite["cases"]:
            del case["observation"]
        report = self.report(suite)
        provenance = report["provenance"]
        self.assertEqual(provenance["kind"], "measured")
        self.assertEqual(provenance["declared_environment"]["model"], "model-a")
        self.assertEqual(provenance["adapter_reported"]["model_ids"], ["model-b"])
        self.assertEqual(provenance["adapter_reported"]["model_modes"], ["fixture"])
        self.assertEqual(report["coverage"][0]["trials"], 2)

    def test_invalid_provenance_and_categories_fail_before_execution(self):
        for change in ({"coverage_categories": ["rag", "rag"]}, {"provenance": {"kind": "imported"}},
                       {"provenance": {"source_url": "javascript:alert(1)"}},
                       {"provenance": {"source_url": "https://user:password@example.org"}},
                       {"provenance": {"evaluated_at": "yesterday"}}, {"environment": {"configuration": []}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.report(self.suite() | change)

    def test_legacy_reports_do_not_invent_provenance_or_categories(self):
        report = self.report()
        for key in ("provenance", "coverage", "coverage_categories", "case_contracts"):
            report.pop(key)
        for case in report["cases"]:
            case.pop("category")
        result = summarize_report(report)
        self.assertEqual(result["provenance"]["kind"], "unknown")
        self.assertEqual([c["category"] for c in result["coverage"]], ["uncategorized"])

    def test_shared_comparison_exposes_additions_removals_and_changed_contracts(self):
        baseline = self.report()
        suite = self.suite()
        suite["cases"][1]["graders"][0]["expected"] = "new criterion"
        extra = deepcopy(suite["cases"][0])
        extra["id"] = "new-case"
        suite["cases"].append(extra)
        candidate = self.report(suite)
        with self.assertRaisesRegex(ValueError, "different inputs"):
            compare_reports(baseline, candidate)
        result = compare_shared_reports(baseline, candidate)
        self.assertEqual(result["shared_cases"], ["answer"])
        self.assertEqual(result["candidate_only"], ["new-case"])
        self.assertEqual(result["incompatible_cases"][0]["id"], "retrieval")
        self.assertFalse(result["verification_eligible"])
        suite["cases"] = suite["cases"][:1]
        self.assertEqual(compare_shared_reports(baseline, self.report(suite))["baseline_only"], ["retrieval"])

    def test_shared_comparison_detects_regression_in_compatible_case(self):
        baseline = self.report()
        suite = self.suite()
        suite["cases"][0]["observation"]["output"] = "wrong"
        suite["cases"] = suite["cases"][:1]
        result = compare_shared_reports(baseline, self.report(suite))
        self.assertEqual(result["regressions"][0]["id"], "answer")

    def test_shared_comparison_requires_known_case_and_grader_contracts(self):
        before, after = self.report(), self.report()
        before.pop("case_contracts")
        after.pop("case_contracts")
        self.assertEqual(len(compare_shared_reports(before, after)["shared_cases"]), 2)
        after["dataset_sha256"] = "different"
        self.assertEqual(compare_shared_reports(before, after)["shared_cases"], [])
        after = self.report()
        after["mode"] = "live"
        after.pop("provenance")
        with self.assertRaisesRegex(ValueError, "Recorded and live"):
            compare_shared_reports(before, after)

    def test_changed_python_and_command_judge_sources_cannot_be_shared(self):
        for kind in ("python", "command"):
            if kind == "python":
                source = 'def evaluate(request):\n return {"score":1,"reason":"first"}\n'
                adapter = {"type": "python", "path": "judge.py"}
            else:
                source = 'import json\nprint(json.dumps({"score":1,"reason":"first"}))\n'
                adapter = {"type": "command", "argv": ["{python}", "judge.py"]}
            path = self.root / "judge.py"
            path.write_text(source)
            suite = self.suite()
            suite["cases"] = suite["cases"][:1]
            suite["cases"][0]["graders"] = [{"id": "judge", "type": "custom", "adapter": adapter}]
            before = self.report(suite)
            path.write_text(source.replace("first", "other"))
            after = self.report(suite)
            self.assertEqual(compare_shared_reports(before, after)["shared_cases"], [])

    def test_summary_rejects_tampered_counts_duplicate_trials_and_invalid_scores(self):
        for mutate in (lambda r: r["summary"].update(passed=2),
                       lambda r: r["cases"][0].update(success_rate=0),
                       lambda r: r["trials"].append(deepcopy(r["trials"][0])),
                       lambda r: r["trials"][0]["graders"][0].update(score=float("nan")),
                       lambda r: r["trials"][0]["graders"][0].update(status="failed"),
                       lambda r: r["summary"].update(passed=True)):
            report = self.report()
            mutate(report)
            with self.assertRaises(ValueError):
                summarize_report(report)

    def test_snapshot_is_stable_changes_with_content_and_rejects_tampering(self):
        report = self.report()
        first, second = build_snapshot(report), build_snapshot(report)
        self.assertEqual(first, second)
        self.assertEqual(verify_snapshot(first), first["version"])
        first["runs"]["candidate"]["suite"] = "edited"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify_snapshot(first)
        report["suite"] = "different"
        self.assertNotEqual(build_snapshot(report)["version"], second["version"])

    def test_portable_site_omits_private_payloads_and_escapes_html(self):
        suite = self.suite()
        suite["name"] = '</script><script>window.injected=true</script>__EVALS_SNAPSHOT_FILE__'
        suite["environment"] = {"model": "example", "configuration": {"password": "CONFIG_PRIVATE_123"}}
        suite["cases"][0]["input"] = "INPUT_PRIVATE_123"
        suite["cases"][0]["observation"]["output"] = "OUTPUT_PRIVATE_123"
        report = self.report(suite)
        result = build_report_site(report, self.root / "site")
        page = Path(result["index"]).read_text(encoding="utf-8")
        data = Path(result["snapshot"]).read_text(encoding="utf-8")
        for secret in ("CONFIG_PRIVATE_123", "INPUT_PRIVATE_123", "OUTPUT_PRIVATE_123", str(self.root)):
            self.assertNotIn(secret, page + data)
        self.assertNotIn(suite["name"], page)
        embedded = json.loads(re.search(r'<script id="snapshot" type="application/json">(.*?)</script>', page, re.S)[1])
        self.assertEqual(embedded, read_json(result["snapshot"]))
        self.assertIn("configuration_sha256", data)
        self.assertEqual(build_report_site(report, self.root / "site"), result)
        write_json(result["snapshot"], {"corrupted": True})
        with self.assertRaisesRegex(ValueError, "immutable"):
            build_report_site(report, self.root / "site")

    def test_site_marks_partial_comparison_as_exploratory(self):
        before = self.report()
        suite = self.suite()
        suite["cases"] = suite["cases"][:1]
        snapshot = build_snapshot(self.report(suite), before)
        self.assertEqual(snapshot["comparison"]["scope"], "shared_cases")
        self.assertFalse(snapshot["comparison"]["verification_eligible"])

    def test_error_only_category_does_not_count_as_tested(self):
        suite = self.suite()
        suite["cases"] = suite["cases"][:1]
        suite["cases"][0]["graders"] = [{"type": "equals", "path": "/missing", "expected": True}]
        report = self.report(suite)
        coverage = next(c for c in report["coverage"] if c["category"] == "llm")
        self.assertEqual(coverage["status"], "error")
        self.assertEqual(coverage["evaluated_trials"], 0)
        self.assertEqual(coverage["success_rate"], 0)

    def test_shared_custom_judges_support_case_reordering(self):
        (self.root / "judge.py").write_text('def evaluate(request):\n return {"score":1,"reason":"ok"}\n')
        suite = self.suite()
        for case in suite["cases"]:
            case["graders"] = [{"id": "judge", "type": "custom", "adapter": {"type": "python", "path": "judge.py"}}]
        before = self.report(suite)
        suite["cases"].reverse()
        result = compare_shared_reports(before, self.report(suite))
        self.assertEqual(result["shared_cases"], ["answer", "retrieval"])

    def test_cli_summary_shared_comparison_snapshot_and_tamper_exit_codes(self):
        before, after = self.root / "before.json", self.root / "after.json"
        write_json(before, self.report())
        suite = self.suite()
        suite["cases"] = suite["cases"][:1]
        write_json(after, self.report(suite))
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["summarize", str(after), "--output", str(self.root / "summary.json")]), 0)
            self.assertEqual(main(["compare", str(before), str(after)]), 2)
            self.assertEqual(main(["compare", str(before), str(after), "--shared-only", "--output", str(self.root / "comparison.json")]), 0)
            self.assertFalse(read_json(self.root / "comparison.json")["verification_eligible"])
            self.assertEqual(main(["report-site", str(after), "--baseline", str(before), "--output", str(self.root / "site")]), 0)
            path = next((self.root / "site").glob("report-*.json"))
            self.assertEqual(main(["verify-snapshot", str(path)]), 0)
            snapshot = read_json(path)
            snapshot["runs"]["candidate"]["suite"] = "tampered"
            write_json(path, snapshot)
            self.assertEqual(main(["verify-snapshot", str(path)]), 2)


if __name__ == "__main__":
    unittest.main()
