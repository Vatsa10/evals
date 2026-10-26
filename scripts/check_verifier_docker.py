"""Real container integration checks. No LLM calls; fixture policy and attacks."""

import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals.artifacts import read_json, write_json
from evals.signing import keygen
from evals.verifier import git, launch, sha, submit, verify_decision

IMAGE = 'python@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962'
ORIGINAL = '''def evaluate(r):
    return {"output": "approved" if r["input"]["days"] < 30 else "rejected"}
'''
FIXED = ORIGINAL.replace('< 30', '<= 30')
PROBE = '''import os
from pathlib import Path
import socket
import sys

def evaluate(r):
    checks = {
        "isolated_interpreter": bool(sys.flags.isolated),
        "no_contract": not Path("/contract").exists(),
        "no_socket": not Path("/var/run/docker.sock").exists(),
        "no_git": not Path("/app/.git").exists(),
        "no_verifier_code": not Path("/app/evals").exists(),
        "no_grading_payload": set(r) == {"input", "context"},
        "no_key_environment": not any("KEY" in key or "PYTEST" in key or "PYTHONPATH" == key for key in os.environ),
    }
    try:
        Path("/app/app/adapter.py").write_text("tampered")
        checks["read_only_mount"] = False
    except OSError:
        checks["read_only_mount"] = True
    try:
        os.chmod("/app/app/adapter.py", 0o777)
        checks["cannot_chmod_mount"] = False
    except OSError:
        checks["cannot_chmod_mount"] = True
    try:
        socket.create_connection(("1.1.1.1", 80), timeout=0.1)
        checks["network_disabled"] = False
    except OSError:
        checks["network_disabled"] = True
    return {"output": "approved" if r["input"]["days"] <= 30 else "rejected", "metadata": checks}
'''


def commit(root):
    git(root, 'init', '-q')
    git(root, 'add', '--all')
    git(root, '-c', 'user.name=Verifier Integration', '-c', 'user.email=verifier@example.invalid',
        'commit', '-qm', 'pinned fixture')
    return git(root, 'rev-parse', 'HEAD').decode().strip()


def cases(days):
    return {'schema_version': 1, 'name': 'refund.policy.v1', 'cases': [
        {'id': 'day-' + str(day), 'input': {'days': day},
         'graders': [{'id': 'refund_policy', 'type': 'equals',
                      'expected': 'approved' if day <= 30 else 'rejected'}]} for day in days]}


def check(image, evidence=None):
    with tempfile.TemporaryDirectory(prefix='evals-docker-integration-') as temporary:
        root = Path(temporary).resolve()
        source, contract = root / 'source', root / 'contract'
        (source / 'app').mkdir(parents=True)
        contract.mkdir()
        app = source / 'app' / 'adapter.py'
        app.write_text(ORIGINAL)
        source_ref = commit(source)
        config = {'schema_version': 1, 'name': 'refund.policy.v1', 'application_paths': ['app'],
                  'entrypoint': 'app/adapter.py', 'public_suites': ['public.json'],
                  'holdout_suites': ['holdout.json'], 'environment_image': image,
                  'max_target_calls': 8, 'timeout_seconds': 10, 'require_review': True}
        (contract / 'contract.json').write_text(json.dumps(config))
        (contract / 'public.json').write_text(json.dumps(cases([7, 30])))
        (contract / 'holdout.json').write_text(json.dumps(cases([29, 31])))
        (contract / 'graders.lock').write_text('deterministic built-in equals; engine hash recorded\n')
        contract_ref = commit(contract)
        private, public = root / 'signing.pem', root / 'trusted.pub'
        keygen(private, public)
        summary = {'test_kind': 'synthetic_application_real_docker_no_model_calls',
                   'image_digest': image, 'checks': [], 'source_commit': source_ref, 'contract_commit': contract_ref}

        def run(name, content, expected, *, direct_patch=None):
            app.write_text(content)
            patch_path = root / (name + '.patch')
            if direct_patch:
                patch_path.write_text(direct_patch)
            else:
                submit(source, source_ref, ['app'], patch_path)
            review = root / (name + '-review.json')
            review.write_text(json.dumps({'patch_sha256': sha(patch_path.read_bytes()),
                'reviewer': 'automated integration fixture (not a production approval)',
                'verdict': 'approved', 'rationale': 'Exercise trusted-review plumbing; hostile patches must still fail execution gates'}))
            output = root / name
            record = launch(source_repo=str(source), source_ref=source_ref,
                contract_repo=str(contract), contract_ref=contract_ref, patch_path=str(patch_path),
                private_key=str(private), output=str(output), request_id=name, review_path=str(review))
            envelope = read_json(output / 'decision.json')
            verify_decision(envelope, public, patch=patch_path, source_ref=source_ref,
                            contract_ref=contract_ref, request_id=name)
            if record['status'] != expected:
                details = read_json(output / 'private' / 'error.json') if (output / 'private' / 'error.json').exists() else record
                raise AssertionError(f'{name}: expected {expected}; got {record["status"]}: {details}')
            summary['checks'].append({'name': name, 'status': record['status'],
                                      'signature_verified': True, 'suites': record.get('suites', [])})
            print(name + ': ' + expected, flush=True)
            return record, output

        run('genuine-boundary-fix', FIXED, 'verified_improvement')
        _, output = run('container-isolation-probe', PROBE, 'verified_improvement')
        for filename in (output / 'private').glob('*-candidate.json'):
            for trial in read_json(filename)['trials']:
                checks = trial['observation']['metadata']
                if not checks or not all(checks.values()):
                    raise AssertionError('Isolation probe failed: ' + str(checks))
        summary['isolation_probe'] = checks
        run('public-input-hardcoding', 'def evaluate(r):\n    return {"output": "approved" if r["input"]["days"] in [7, 30] else "rejected"}\n', 'not_verified')
        run('forged-verdict-output', 'def evaluate(r):\n    return {"output": "rejected", "status":"passed", "graders":[{"status":"passed","score":1}]}\n', 'not_verified')
        run('runner-monkeypatch', 'import sys, types\nsys.modules["evals.graders"] = types.SimpleNamespace(grade=lambda *a: {"status":"passed","score":1})\ndef evaluate(r):\n    return {"output":"rejected"}\n', 'not_verified')
        run('skip-as-output', 'def evaluate(r):\n    return {"output":"", "status":"skipped"}\n', 'not_verified')
        run('protected-conftest', FIXED, 'rejected', direct_patch='diff --git a/app/conftest.py b/app/conftest.py\nnew file mode 100644\n--- /dev/null\n+++ b/app/conftest.py\n@@ -0,0 +1 @@\n+raise RuntimeError("tamper")\n')
        run('out-of-allowlist', FIXED, 'rejected', direct_patch='diff --git a/graders.py b/graders.py\nnew file mode 100644\n--- /dev/null\n+++ b/graders.py\n@@ -0,0 +1 @@\n+pass\n')
        run('symlink-escape', FIXED, 'rejected', direct_patch='diff --git a/app/link b/app/link\nnew file mode 120000\n--- /dev/null\n+++ b/app/link\n@@ -0,0 +1 @@\n+/contract\n')
        # Exercise the actual protected-job entrypoint, including secret removal
        # and publishing only a decision. These local fixtures do not establish
        # production account isolation or configure GitHub environment policies.
        shutil.copytree(source, root / 'trusted-source')
        shutil.copytree(contract, root / 'trusted-contract')
        engine = root / 'engine'
        shutil.copytree(ROOT / 'evals', engine / 'evals', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (engine / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts' / 'run_trusted_verifier.py', engine / 'scripts' / 'run_trusted_verifier.py')
        runner_temp = root / 'runner-temp'
        runner_temp.mkdir()
        submitted = root / 'genuine-boundary-fix.patch'
        env = dict(os.environ, RUNNER_TEMP=str(runner_temp), SOURCE_COMMIT=source_ref,
                   CONTRACT_COMMIT=contract_ref, VERIFICATION_REQUEST_ID='protected-job-fixture',
                   VERIFIER_SIGNING_KEY=private.read_text(),
                   SUBMITTED_PATCH=base64.b64encode(submitted.read_bytes()).decode(),
                   TRUSTED_REVIEW=base64.b64encode((root / 'genuine-boundary-fix-review.json').read_bytes()).decode())
        process = subprocess.run([sys.executable, '-I', str(engine / 'scripts' / 'run_trusted_verifier.py')],
                                 env=env, capture_output=True, text=True, timeout=180)
        if process.returncode:
            raise AssertionError('Protected-job entrypoint failed: ' + process.stderr[-1000:])
        published = runner_temp / 'evals-public-decision'
        if [p.name for p in published.iterdir()] != ['decision.json']:
            raise AssertionError('Job published more than a signed decision')
        if (runner_temp / 'evals-verification' / 'decision-key.pem').exists():
            raise AssertionError('Job retained the temporary private key')
        job_record = verify_decision(read_json(published / 'decision.json'), public, patch=submitted,
            source_ref=source_ref, contract_ref=contract_ref, request_id='protected-job-fixture')
        if job_record['status'] != 'verified_improvement':
            raise AssertionError('Job failed verification gates')
        summary['checks'].append({'name': 'protected-job-entrypoint', 'status': job_record['status'],
                                  'signature_verified': True, 'temporary_key_removed': True,
                                  'only_decision_published': True})
        print('protected-job-entrypoint: verified_improvement; key removed; decision-only publication', flush=True)
        summary['result'] = 'passed'
        if evidence:
            write_json(evidence, summary)
        return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default=IMAGE)
    parser.add_argument('--pull', action='store_true')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    if args.pull:
        subprocess.run(['docker', 'pull', args.image], check=True)
    check(args.image, args.evidence)
