import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evals.model_gateway import ModelGateway, validate
from evals.pytest_verifier import invariants, load_manifest, run_tests


def inventory(node='test_public.py::test_policy'):
    return {'nodeids': [node], 'skipped': 0, 'xfail': 0, 'xpassed': 0,
            'deselected': 0, 'target_calls': 1}


class GatewayTests(unittest.TestCase):
    def test_fixture_is_explicitly_labeled_and_budget_is_enforced(self):
        gateway = ModelGateway({'backend': 'fixture', 'max_model_calls': 1}, 'image-not-used')
        self.assertEqual(gateway.complete('example')['text'], 'fixture-model-response')
        self.assertFalse(gateway.summary()['live'])
        self.assertEqual(gateway.summary()['completed'], 1)
        with self.assertRaisesRegex(RuntimeError, 'budget'):
            gateway.complete('extra')
        self.assertEqual(gateway.summary()['rejected_calls'], 1)
        self.assertEqual(len(gateway.records), 1)

    def test_rejects_arbitrary_gateway_endpoints_commands_and_invalid_budgets(self):
        for config in ({'backend': 'http', 'url': 'http://arbitrary'},
                       {'backend': 'claude-cli', 'argv': ['arbitrary-command']},
                       {'backend': 'fixture', 'max_model_calls': False},
                       {'backend': 'fixture', 'timeout_seconds': 0}):
            with self.assertRaises(ValueError):
                validate(config)

    def test_prompt_bound_does_not_consume_a_model_call(self):
        gateway = ModelGateway({'backend': 'fixture'}, 'image-not-used')
        for prompt in ('', 'x' * 32769, {'not': 'text'}):
            with self.assertRaises(ValueError):
                gateway.complete(prompt)
        self.assertEqual(gateway.summary()['model_calls'], 0)

    def test_live_adapter_uses_fixed_cli_arguments_and_a_private_cwd(self):
        def provider(argv, payload, timeout, **kwargs):
            if '--version' in argv:
                return b'test-cli-version'
            self.assertIn('--strict-mcp-config', argv)
            self.assertIn('--disable-slash-commands', argv)
            self.assertEqual(argv[argv.index('--tools') + 1], '')
            self.assertEqual(payload, b'untrusted application prompt')
            self.assertTrue(Path(kwargs['cwd']).is_dir())
            return json.dumps({'result': 'actual envelope shape', 'usage': {'output_tokens': 4},
                               'modelUsage': {'provider-model-id': {}}}).encode()
        gateway = ModelGateway({'backend': 'claude-cli'}, 'image-not-used')
        with patch('evals.model_gateway.shutil.which', return_value='/trusted/claude'), \
                patch('evals.verifier.bounded_run', side_effect=provider):
            reply = gateway.complete('untrusted application prompt')
        self.assertEqual(reply['model_ids'], ['provider-model-id'])
        self.assertEqual(gateway.summary()['usage']['output_tokens'], 4)

    def test_consumer_can_require_real_model_execution(self):
        from evals.signing import keygen, sign
        from evals.verifier import sha, verify_decision
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private, public = root / 'key.pem', root / 'key.pub'
            keygen(private, public)
            patch_path = root / 'candidate.patch'
            patch_path.write_text('test patch bytes')
            record = {'schema_version': 1, 'patch_sha256': sha(patch_path.read_bytes()),
                      'source_commit': 'a' * 40, 'contract_commit': 'b' * 40, 'request_id': 'current',
                      'contract_file': 'contract.json', 'trust_profile': 'external-supervisor/docker-target',
                      'actual_target_calls': 1, 'model_gateway': {'backend': 'fixture', 'live': False}}
            with self.assertRaisesRegex(ValueError, 'live-model'):
                verify_decision(sign(record, private), public, patch=patch_path, source_ref='a' * 40,
                                contract_ref='b' * 40, request_id='current', require_live_model=True)


class PytestVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = {'public_tests': ['test_public.py'], 'holdout_tests': ['test_holdout.py'],
                       'manifest': 'manifest.json', 'timeout_seconds': 20}
        (self.root / 'test_public.py').write_text('def test_policy(evals_target):\n    assert evals_target({"days":30})["output"] == "approved"\n')
        (self.root / 'test_holdout.py').write_text('def test_policy(evals_target):\n    assert evals_target({"days":29})["output"] == "approved"\n')
        (self.root / 'manifest.json').write_text(json.dumps({
            'public': inventory(), 'holdout': inventory('test_holdout.py::test_policy')}))

    def test_actual_pytest_failure_then_success_with_exact_inventory(self):
        manifest = load_manifest(self.root, self.config)
        before = run_tests(self.root, self.config, 'public', lambda p: {'output': 'rejected'})
        after = run_tests(self.root, self.config, 'public', lambda p: {'output': 'approved'})
        self.assertEqual(before['summary']['failed'], 1)
        self.assertEqual(after['summary']['passed'], 1)
        self.assertTrue(invariants(before, manifest['public']))
        self.assertTrue(invariants(after, manifest['public']))
        self.assertEqual(before['target_calls'], 1)

    def test_conftest_and_environment_deselection_are_not_loaded(self):
        from unittest.mock import patch
        (self.root / 'conftest.py').write_text('raise RuntimeError("conftest must not load")')
        with patch.dict('os.environ', {'PYTEST_ADDOPTS': '-k nonexistent', 'PYTHONOPTIMIZE': '1'}):
            result = run_tests(self.root, self.config, 'public', lambda p: {'output': 'approved'})
        self.assertEqual(result['summary']['passed'], 1)
        self.assertTrue(invariants(result, inventory()))

    def test_skip_xfail_and_incorrect_collection_cannot_pass(self):
        for marker in ('skip(reason="disabled")', 'xfail(reason="ignored")', 'skipif(False, reason="conditional")'):
            (self.root / 'test_public.py').write_text('import pytest\n@pytest.mark.' + marker + '\ndef test_policy(evals_target):\n    assert evals_target({"days":30})["output"] == "approved"\n')
            result = run_tests(self.root, self.config, 'public', lambda p: {'output': 'approved'})
            self.assertFalse(invariants(result, inventory()))
        result['nodeids'] = ['different-test']
        self.assertFalse(invariants(result, inventory()))

    def test_manifest_refuses_weak_skips_and_missing_target_execution(self):
        for field, value in [('skipped', 1), ('xfail', 1), ('target_calls', 0)]:
            spec = inventory()
            spec[field] = value
            (self.root / 'manifest.json').write_text(json.dumps({'public': spec, 'holdout': inventory()}))
            with self.assertRaises(ValueError):
                load_manifest(self.root, self.config)

    def test_no_application_imports_are_needed_or_available(self):
        (self.root / 'test_public.py').write_text('import sys\ndef test_policy(evals_target):\n    assert sys.flags.isolated\n    assert "untrusted_app" not in sys.modules\n    assert evals_target({"days":30})["output"] == "approved"\n')
        result = run_tests(self.root, self.config, 'public', lambda p: {'output': 'approved'})
        self.assertEqual(result['summary']['passed'], 1)


if __name__ == '__main__':
    unittest.main()
