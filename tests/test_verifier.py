import copy
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch as mock_patch

from evals.adapters import invoke
from evals.artifacts import read_json
from evals.cli import main
from evals.openai_import import import_jsonl
from evals.signing import keygen, verify
from evals.verifier import (apply_patch, bounded_run, clean_environment, execute, git, inventory,
                            pinned_tree, protected, review_patch, safe_path, sha,
                            submit, validate_contract, verify_decision)


IMAGE = 'python@sha256:' + 'a' * 64
ORIGINAL = 'def evaluate(r):\n    return {"output": "approved" if r["input"]["days"] < 30 else "rejected"}\n'
FIXED = ORIGINAL.replace('< 30', '<= 30')


def commit(root):
    git(root, 'init', '-q')
    git(root, 'add', '--all')
    git(root, '-c', 'user.name=Verifier Test', '-c', 'user.email=verifier@example.invalid',
        'commit', '-qm', 'fixture')
    return git(root, 'rev-parse', 'HEAD').decode().strip()


def suite(days):
    return {'schema_version': 1, 'name': 'refund', 'cases': [
        {'id': f'day-{day}', 'input': {'days': day}, 'graders': [
            {'id': 'policy', 'type': 'equals', 'expected': 'approved' if day <= 30 else 'rejected'}]}
        for day in days]}


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source, self.contract = (self.root / p for p in ('source', 'contract'))
        self.source.mkdir()
        self.contract.mkdir()
        (self.source / 'app').mkdir()
        self.app = self.source / 'app' / 'adapter.py'
        self.app.write_text(ORIGINAL)
        self.source_ref = commit(self.source)
        self.config = {'schema_version': 1, 'name': 'refund.dev.v1', 'application_paths': ['app'],
                       'entrypoint': 'app/adapter.py', 'public_suites': ['public.json'],
                       'holdout_suites': ['holdout.json'], 'environment_image': IMAGE,
                       'max_target_calls': 8, 'require_review': False}
        (self.contract / 'public.json').write_text(json.dumps(suite([7, 30])))
        (self.contract / 'holdout.json').write_text(json.dumps(suite([29, 31])))
        (self.contract / 'requirements.lock').write_text('# Entire contract tree is pinned\n')
        self.pin_contract()
        self.app.write_text(FIXED)
        self.patch = self.root / 'candidate.patch'
        self.patch.write_bytes(git(self.source, 'diff', '--no-renames', self.source_ref))
        self.private, self.public = self.root / 'private.pem', self.root / 'public.pem'
        keygen(self.private, self.public)
        self.sequence = 0

    def pin_contract(self):
        (self.contract / 'contract.json').write_text(json.dumps(self.config))
        self.contract_ref = commit(self.contract)

    def run_verifier(self, *, target=None, **overrides):
        self.sequence += 1
        output = self.root / ('result-' + str(self.sequence))
        kwargs = dict(source_repo=str(self.source), source_ref=self.source_ref,
                      contract_repo=str(self.contract), contract_ref=self.contract_ref,
                      patch_path=str(self.patch), private_key=str(self.private),
                      output=str(output), request_id='request-1')
        kwargs.update(overrides)
        # Unit fixture uses a real subprocess adapter, NOT a security boundary.
        # scripts/check_verifier_docker.py exercises actual hostile containers.
        def fixture_target(config, app, payload):
            return invoke({'type': 'python', 'path': config['entrypoint']}, payload, app)
        with mock_patch('evals.verifier.container_target', side_effect=target or fixture_target):
            record = execute(**kwargs)
        return record, output

    def test_recomputes_baseline_and_verifies_signed_patch(self):
        record, output = self.run_verifier()
        self.assertEqual(record['status'], 'verified_improvement')
        self.assertTrue(record['count_invariants_match'])
        self.assertEqual(record['suites'][0]['baseline']['passed'], 1)
        self.assertEqual(record['suites'][0]['candidate']['passed'], 2)
        # A dirty source/contract working tree is ignored in favor of commits.
        self.app.write_text('raise RuntimeError("dirty source must not execute")')
        (self.contract / 'public.json').write_text('{}')
        again, _ = self.run_verifier()
        self.assertEqual(again['status'], 'verified_improvement')
        envelope = read_json(output / 'decision.json')
        accepted = verify_decision(envelope, self.public, patch=self.patch,
                                   source_ref=self.source_ref, contract_ref=self.contract_ref, request_id='request-1')
        self.assertEqual(accepted['patch_sha256'], sha(self.patch.read_bytes()))
        self.assertNotIn('day-29', (output / 'decision.json').read_text())

    def test_signature_rejects_edits_wrong_key_and_replay(self):
        _, output = self.run_verifier()
        envelope = read_json(output / 'decision.json')
        altered = copy.deepcopy(envelope)
        altered['record']['status'] = 'fake'
        with self.assertRaisesRegex(ValueError, 'signature'):
            verify(altered, self.public)
        other_private, other_public = self.root / 'other.pem', self.root / 'other.pub'
        keygen(other_private, other_public)
        with self.assertRaisesRegex(ValueError, 'identity'):
            verify(envelope, other_public)
        for overrides in ({'request_id': 'replay'}, {'source_ref': 'b' * 40}, {'contract_ref': 'b' * 40}):
            kwargs = dict(patch=self.patch, source_ref=self.source_ref, contract_ref=self.contract_ref, request_id='request-1')
            kwargs.update(overrides)
            with self.assertRaisesRegex(ValueError, 'does not match'):
                verify_decision(envelope, self.public, **kwargs)
        self.patch.write_bytes(self.patch.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            verify_decision(envelope, self.public, patch=self.patch, source_ref=self.source_ref,
                            contract_ref=self.contract_ref, request_id='request-1')

    def test_public_hardcoding_fails_unseen_holdout(self):
        self.app.write_text('def evaluate(r):\n    return {"output": "approved" if r["input"]["days"] in [7, 30] else "rejected"}\n')
        self.patch.write_bytes(git(self.source, 'diff', '--no-renames', self.source_ref))
        record, _ = self.run_verifier()
        self.assertEqual(record['status'], 'not_verified')
        self.assertEqual(record['suites'][0]['candidate']['failed'], 0)
        self.assertEqual(record['suites'][1]['candidate']['failed'], 1)

    def test_whole_contract_tree_dependencies_affect_contract_hash(self):
        first, _ = self.run_verifier()
        (self.contract / 'requirements.lock').write_text('changed dependency pin\n')
        self.pin_contract()
        second, _ = self.run_verifier()
        self.assertNotEqual(first['contract_sha256'], second['contract_sha256'])

    def test_budget_refuses_before_target_calls(self):
        self.config['max_target_calls'] = 7
        self.pin_contract()
        with mock_patch('evals.verifier.container_target') as target:
            record, _ = self.run_verifier(target=target)
            target.assert_not_called()
        self.assertEqual(record['status'], 'rejected')

    def test_no_baseline_degradation_by_stored_reports(self):
        (self.source / 'baseline.json').write_text('{"summary":{"passed":0}}')
        record, _ = self.run_verifier()
        self.assertEqual(record['suites'][0]['baseline']['failed'], 1)

    def test_required_review_is_bound_to_exact_patch(self):
        self.config['require_review'] = True
        self.pin_contract()
        record, _ = self.run_verifier()
        self.assertEqual(record['status'], 'needs_review')
        self.assertFalse(record['verification_eligible'])
        review_path = self.root / 'review.json'
        review = {'patch_sha256': sha(self.patch.read_bytes()), 'reviewer': 'fixture reviewer',
                  'verdict': 'approved', 'rationale': 'Boundary comparison only; no hardcoded examples or runner edits'}
        review_path.write_text(json.dumps(review))
        approved, _ = self.run_verifier(review_path=str(review_path))
        self.assertEqual(approved['status'], 'verified_improvement')
        review['patch_sha256'] = '0' * 64
        review_path.write_text(json.dumps(review))
        rejected, _ = self.run_verifier(review_path=str(review_path))
        self.assertEqual(rejected['status'], 'rejected')

    def test_counts_catch_deselected_graders(self):
        from evals.engine import run_suite as real_run
        def missing(*args, **kwargs):
            report = real_run(*args, **kwargs)
            report['trials'][0]['graders'] = []
            return report
        with mock_patch('evals.verifier.run_suite', side_effect=missing):
            record, _ = self.run_verifier()
        self.assertFalse(record['count_invariants_match'])
        self.assertFalse(record['verification_eligible'])

    def test_failed_or_missing_observations_cannot_pass(self):
        record, _ = self.run_verifier(target=lambda *args: {})
        self.assertFalse(record['verification_eligible'])
        self.assertGreater(record['suites'][0]['candidate']['error'], 0)

    def test_protected_patch_rejected_and_signed(self):
        self.patch.write_text('diff --git a/app/conftest.py b/app/conftest.py\nnew file mode 100644\n--- /dev/null\n+++ b/app/conftest.py\n@@ -0,0 +1 @@\n+print("tampered")\n')
        record, output = self.run_verifier()
        self.assertEqual(record['status'], 'rejected')
        self.assertEqual(verify(read_json(output / 'decision.json'), self.public)['status'], 'rejected')

    def test_symlink_patch_rejected(self):
        self.patch.write_text('diff --git a/app/link b/app/link\nnew file mode 120000\n--- /dev/null\n+++ b/app/link\n@@ -0,0 +1 @@\n+/contract\n')
        record, _ = self.run_verifier()
        self.assertEqual(record['status'], 'rejected')

    def test_ref_and_image_must_be_immutable(self):
        record, _ = self.run_verifier(source_ref='HEAD')
        self.assertEqual(record['status'], 'rejected')
        self.config['environment_image'] = 'python:latest'
        with self.assertRaisesRegex(ValueError, 'immutable'):
            validate_contract(self.config)

    def test_holdout_must_be_disjoint(self):
        (self.contract / 'holdout.json').write_text(json.dumps(suite([30])))
        self.pin_contract()
        record, _ = self.run_verifier()
        self.assertEqual(record['status'], 'rejected')

    def test_submitted_patch_uses_allowlist_and_refuses_untracked(self):
        patch_file = self.root / 'submitted.patch'
        result = submit(self.source, self.source_ref, ['app'], patch_file)
        self.assertEqual(result['changed_paths'], ['app/adapter.py'])
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            submit(self.source, self.source_ref, ['app'], patch_file)
        (self.source / 'untracked.py').write_text('pass')
        with self.assertRaisesRegex(ValueError, 'Untracked'):
            submit(self.source, self.source_ref, ['app'], self.root / 'omitted.patch')

    def test_no_state_overwrite(self):
        _, output = self.run_verifier()
        with self.assertRaises(FileExistsError):
            self.run_verifier(output=str(output))

    def test_portable_paths_and_protected_files(self):
        for name in ('../app.py', '/app.py', 'app/../x', 'C:/app.py', 'app\\x', 'app//x'):
            with self.assertRaises(ValueError):
                safe_path(name)
        for name in ('app/conftest.py', 'app/.github/ci.yml', 'app/grader.py', 'app/fixtures/data.json',
                     'app/pyproject.toml', 'app/test_config.py', 'app/sitecustomize.py', 'app/uv.lock'):
            self.assertTrue(protected(name), name)

    def test_environment_removes_injection_and_credentials(self):
        with mock_patch.dict('os.environ', {'PYTHONPATH': 'attack', 'PYTEST_ADDOPTS': '-k nothing',
                                           'LD_PRELOAD': 'attack.so', 'OPENAI_API_KEY': 'secret'}):
            clean = clean_environment()
        for key in ('PYTHONPATH', 'PYTEST_ADDOPTS', 'LD_PRELOAD', 'OPENAI_API_KEY'):
            self.assertNotIn(key, clean)

    def test_diff_review_flags_runner_and_exception_manipulation(self):
        findings = review_patch(b'diff --git a/app.py b/app.py\n+except Exception:\n+    sys.modules["grader"] = None\n+assert True\n')
        self.assertIn('broad_exception', findings)
        self.assertIn('runner_manipulation', findings)
        self.assertIn('disabled_assertion', findings)

    def test_cli_import_and_signature_verification(self):
        _, output = self.run_verifier()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['verifier', 'verify-decision', str(output / 'decision.json'),
                '--public-key', str(self.public), '--patch', str(self.patch), '--source-ref', self.source_ref,
                '--contract-ref', self.contract_ref, '--request-id', 'request-1']), 0)

    def test_consumer_binds_selected_contract_file(self):
        _, output = self.run_verifier()
        with self.assertRaisesRegex(ValueError, 'does not match'):
            verify_decision(read_json(output / 'decision.json'), self.public, patch=self.patch,
                            source_ref=self.source_ref, contract_ref=self.contract_ref,
                            request_id='request-1', contract_file='another-policy.json')


class ResourceLimitTests(unittest.TestCase):
    def test_output_flood_is_bounded(self):
        with self.assertRaisesRegex(RuntimeError, 'output limit'):
            bounded_run([sys.executable, '-I', '-c', 'import sys; sys.stdout.write("x" * 3000000)'], b'', 5)

    def test_blocked_stdin_is_still_subject_to_timeout(self):
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            bounded_run([sys.executable, '-I', '-c', 'import time; time.sleep(5)'], b'x' * 1000000, 0.1)

    def test_target_stderr_never_leaks_into_public_errors(self):
        with self.assertRaises(RuntimeError) as failure:
            bounded_run([sys.executable, '-I', '-c', 'import sys; sys.stderr.write("hidden reference"); sys.exit(1)'], b'', 5)
        self.assertNotIn('hidden reference', str(failure.exception))


class ImportTests(unittest.TestCase):
    def test_import_is_strict_stable_and_does_not_execute(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / 'samples.jsonl'
            data.write_text(json.dumps({'input': [{'role': 'user', 'content': 'hello'}], 'ideal': 'hi'}) + '\n')
            first = import_jsonl(data, name='chat', adapter='app.py', output=root / 'first.json')
            second = import_jsonl(data, name='chat', adapter='app.py', output=root / 'second.json')
            self.assertEqual(first, second)
            self.assertEqual(first['name'], 'chat.dev.v1')
            self.assertIsInstance(first['cases'][0]['input'], list)
            self.assertEqual(first['dataset_source']['sha256'], sha(data.read_bytes()))
            data.write_text(json.dumps({'input': 'hello', 'ideal': ['hi', 'hey']}) + '\n')
            with self.assertRaisesRegex(ValueError, 'single string'):
                import_jsonl(data, name='chat', adapter='app.py', output=root / 'invalid.json')
            self.assertFalse((root / 'invalid.json').exists())


if __name__ == '__main__':
    unittest.main()
