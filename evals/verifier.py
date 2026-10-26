"""Trusted patch verification. Run on a host/job the coding agent cannot access.

Only the application runs in containers; grading and signing stay in the trusted
supervisor. A subprocess on the agent's own machine is not a trust boundary.
"""

import copy
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid

from evals.artifacts import read_json, write_json
from evals.engine import compare_reports, run_suite, validate_suite
from evals.improvement import engine_hash
from evals.signing import canonical, primitives, sign
from evals.storage import utc_now


PATCH_LIMIT = 2 * 1024 * 1024
TREE_LIMIT = 64 * 1024 * 1024
OUTPUT_LIMIT = 1024 * 1024
BLOCKED = {'conftest.py', 'sitecustomize.py', 'usercustomize.py', 'pytest.ini',
           'pyproject.toml', 'setup.cfg', 'setup.py', 'tox.ini', '.coveragerc',
           'requirements.txt', 'requirements-dev.txt', 'package-lock.json',
           'yarn.lock', 'pnpm-lock.yaml', 'uv.lock', 'poetry.lock', 'pipfile',
           'pipfile.lock', 'dockerfile', '.dockerignore', 'ci', '.ci', '.circleci',
           '.buildkite', 'jenkinsfile', 'azure-pipelines.yml', 'bitbucket-pipelines.yml',
           '.travis.yml', 'bun.lockb', 'npm-shrinkwrap.json'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def clean_environment():
    # No PYTHONPATH, pytest switches, credentials, preload variables or API keys.
    return {key: value for key, value in os.environ.items()
            if key.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP',
                               'HOME', 'USERPROFILE', 'PROGRAMDATA', 'LOCALAPPDATA'}}


def git(repo, *args, data=None):
    executable = shutil.which('git')
    if not executable:
        raise ValueError('Git is required by the verifier')
    process = subprocess.run([executable, '-c', 'core.hooksPath=/dev/null',
                              '-c', 'core.autocrlf=false', '-C', str(repo), *args],
                             input=data, capture_output=True, env=clean_environment(), timeout=60)
    if process.returncode:
        raise ValueError('Git operation failed: ' + process.stderr.decode('utf-8', errors='replace')[-2000:])
    return process.stdout


def safe_path(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_@+./-]+', name):
        raise ValueError(f'Unsupported portable path: {name!r}')
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in {'', '.', '..'} for p in name.split('/')):
        raise ValueError(f'Unsafe path: {name}')
    if any(p.lower() == '.git' for p in path.parts):
        raise ValueError('Git metadata cannot be submitted')
    reserved = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}
    if any(p.endswith('.') or p.split('.')[0].lower() in reserved for p in path.parts):
        raise ValueError('Platform-reserved path: ' + name)
    return name


def protected(name):
    parts = [p.lower() for p in PurePosixPath(name).parts]
    return any(p in BLOCKED or p.startswith(('.git', 'test', 'grader', 'fixture', 'snapshot',
                                           'conftest', 'pytest')) or
               p.endswith(('.lock', '.pth', '.pyc')) or p.startswith('requirements')
               for p in parts)


def allowed(name, paths):
    return any(name == p or name.startswith(p + '/') for p in paths)


def pinned_tree(repo, ref, destination, *, paths=None):
    if not isinstance(ref, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', ref):
        raise ValueError('Use a full pinned Git commit ID, not a branch or tag')
    resolved = git(repo, 'rev-parse', '--verify', ref + '^{commit}').decode().strip()
    if resolved != ref:
        raise ValueError('Pinned reference must identify the commit itself')
    entries, total, portable_names = {}, 0, set()
    for row in git(repo, 'ls-tree', '-r', '-z', ref).split(b'\0'):
        if not row:
            continue
        meta, raw_name = row.split(b'\t', 1)
        name = raw_name.decode('utf-8')
        if paths is not None and not allowed(name, paths):
            continue
        safe_path(name)
        if name.casefold() in portable_names:
            raise ValueError('Case-colliding paths are forbidden: ' + name)
        portable_names.add(name.casefold())
        if paths is not None and protected(name):
            raise ValueError('Application export includes a protected path: ' + name)
        mode, kind, blob = meta.decode().split()
        if mode not in {'100644', '100755'} or kind != 'blob':
            raise ValueError('Symlinks and submodules are forbidden: ' + name)
        # Check size before reading a blob into memory.
        size = int(git(repo, 'cat-file', '-s', blob))
        total += size
        if total > TREE_LIMIT:
            raise ValueError('Pinned tree exceeds the verifier size limit')
        content = git(repo, 'cat-file', 'blob', blob)
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o755 if mode == '100755' else 0o644)
        entries[name] = {'mode': mode, 'sha256': sha(content)}
    if not entries:
        raise ValueError('Pinned tree/application export is empty')
    return sha(canonical(entries)), entries


def validate_contract(contract):
    keys = {'schema_version', 'name', 'application_paths', 'entrypoint', 'function',
            'public_suites', 'holdout_suites', 'environment_image', 'max_target_calls',
            'timeout_seconds', 'require_review'}
    if (not isinstance(contract, dict) or set(contract) - keys
            or type(contract.get('schema_version')) is not int or contract['schema_version'] != 1):
        raise ValueError('Unsupported verifier contract schema or unknown fields')
    if not isinstance(contract.get('name'), str) or not contract['name'].strip():
        raise ValueError('Contract requires a name')
    for key in ('application_paths', 'public_suites', 'holdout_suites'):
        values = contract.get(key)
        if not isinstance(values, list) or not values or len(set(values)) != len(values):
            raise ValueError(key + ' must be a nonempty unique path list')
        for value in values:
            safe_path(value)
    if set(contract['public_suites']) & set(contract['holdout_suites']):
        raise ValueError('Public and holdout suites must be separate')
    safe_path(contract.get('entrypoint'))
    if not allowed(contract['entrypoint'], contract['application_paths']):
        raise ValueError('Entrypoint must be in the exported application paths')
    if any(protected(p) for p in contract['application_paths']):
        raise ValueError('Protected paths cannot be application paths')
    if not isinstance(contract.get('function', 'evaluate'), str) or not contract.get('function', 'evaluate').isidentifier():
        raise ValueError('Contract function must be an identifier')
    if not re.fullmatch(r'[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}', contract.get('environment_image', '')):
        raise ValueError('Target environment must use an immutable image@sha256:digest')
    for key, default, limit in [('max_target_calls', 100, 10000), ('timeout_seconds', 30, 300)]:
        value = contract.get(key, default)
        if type(value) is not int or not 1 <= value <= limit:
            raise ValueError(f'{key} must be an integer between 1 and {limit}')
    if type(contract.get('require_review', True)) is not bool:
        raise ValueError('require_review must be a boolean')


def apply_patch(candidate, patch, paths, *, source_entries=None):
    if not patch or len(patch) > PATCH_LIMIT or not patch.startswith(b'diff --git '):
        raise ValueError('Submit a nonempty Git diff within the 2 MiB limit')
    git(candidate, 'init', '-q')
    git(candidate, 'add', '--all')
    # Windows Git may infer different executable bits from its filesystem.
    # Seed the index from pinned Git modes before checking the diff.
    if source_entries:
        for mode, flag in [('100755', '+x'), ('100644', '-x')]:
            names = [name for name, entry in source_entries.items() if entry['mode'] == mode]
            for offset in range(0, len(names), 32):
                git(candidate, 'update-index', '--chmod=' + flag, '--', *names[offset:offset + 32])
    # Reject copies as well as renames, even when Git reports a textual stat.
    if re.search(rb'(?m)^(?:rename|copy) (?:from|to) ', patch):
        raise ValueError('Renames and copies are forbidden; submit --no-renames')
    rows = git(candidate, 'apply', '--numstat', '-z', '-', data=patch).split(b'\0')
    changed = []
    for row in rows:
        if not row:
            continue
        fields = row.split(b'\t', 2)
        if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit() or not fields[2]:
            raise ValueError('Binary patches and renames are forbidden; submit a textual diff with --no-renames')
        name = safe_path(fields[2].decode('utf-8'))
        if protected(name) or not allowed(name, paths):
            raise ValueError('Patch touches a protected or non-allowlisted path: ' + name)
        changed.append(name)
    if not changed:
        raise ValueError('Patch contains no textual application changes')
    git(candidate, 'apply', '--check', '--index', '-', data=patch)
    git(candidate, 'apply', '--index', '-', data=patch)
    portable_names = set()
    for row in git(candidate, 'ls-files', '--stage', '-z').split(b'\0'):
        if not row:
            continue
        if row.split(b' ', 1)[0] not in {b'100644', b'100755'}:
            raise ValueError('Patch introduces a symlink or submodule')
        name = safe_path(row.split(b'\t', 1)[1].decode('utf-8'))
        if name.casefold() in portable_names:
            raise ValueError('Patch introduces case-colliding paths')
        portable_names.add(name.casefold())
    # .git is never mounted into the target container.
    return sorted(set(changed))


def bounded_run(argv, payload, timeout):
    """Cap both streams, kill on timeout, and avoid buffering attacker output."""
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=clean_environment())
    buffers, exceeded = [bytearray(), bytearray()], threading.Event()
    def drain(stream, buffer):
        while chunk := stream.read(4096):
            if len(buffer) + len(chunk) > OUTPUT_LIMIT:
                exceeded.set()
                process.kill()
                break
            buffer.extend(chunk)
        stream.close()
    readers = [threading.Thread(target=drain, args=(stream, buffer), daemon=True)
               for stream, buffer in zip((process.stdout, process.stderr), buffers)]
    for reader in readers:
        reader.start()
    def feed():
        try:
            process.stdin.write(payload)
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise RuntimeError('Target timed out or closed its input') from exc
    finally:
        for reader in readers:
            reader.join(timeout=5)
        writer.join(timeout=5)
    if exceeded.is_set():
        raise RuntimeError('Target exceeded the output limit')
    if process.returncode:
        # Never publish raw target stderr: it may contain hidden input or labels.
        raise RuntimeError(f'Target container failed (exit {process.returncode})')
    return bytes(buffers[0])


def container_target(contract, app, payload):
    docker = shutil.which('docker')
    if not docker:
        raise ValueError('Docker is required; there is no insecure process fallback')
    name = 'evals-target-' + uuid.uuid4().hex
    worker = Path(__file__).with_name('target_worker.py').resolve()
    # No source repository, verifier state, contract, key, socket, host env or
    # grader is mounted. Fresh process/container for every independent trial.
    argv = [docker, 'run', '--rm', '--pull=never', '--name', name, '-i',
            '--network=none', '--read-only', '--user=65534:65534', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--pids-limit=64', '--memory=256m',
            '--memory-swap=256m', '--cpus=1', '--ulimit=nofile=256:256',
            '--log-driver=none', '--tmpfs=/tmp:rw,noexec,nosuid,size=16m,mode=1777',
            '--mount', f'type=bind,source={app},target=/app,readonly',
            '--mount', f'type=bind,source={worker},target=/target_worker.py,readonly',
            '--workdir=/tmp', '--entrypoint=/usr/bin/env', contract['environment_image'],
            '-i', 'PATH=/usr/local/bin:/usr/bin:/bin', 'HOME=/tmp', 'LANG=C.UTF-8',
            'python', '-I', '-B', '/target_worker.py', contract['entrypoint'], contract.get('function', 'evaluate')]
    try:
        # Opaque task IDs/metadata, grader references and trial numbers stay private.
        public_request = {'input': payload['input'], 'context': payload.get('context')}
        raw = bounded_run(argv, canonical(public_request), contract.get('timeout_seconds', 30))
        return json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Invalid JSON number')))
    finally:
        subprocess.run([docker, 'rm', '-f', name], capture_output=True,
                       timeout=20, env=clean_environment(), check=False)


def inventory(report):
    return {'collected': len(report['trials']), 'skipped': 0, 'xfail': 0,
            'trials': [[t['case_id'], t['trial'], [g['id'] for g in t['graders']]]
                       for t in report['trials']]}


def review_patch(patch):
    """Heuristic review aid. Findings require review; absence proves nothing."""
    added = '\n'.join(line[1:] for line in patch.decode('utf-8').splitlines()
                      if line.startswith('+') and not line.startswith('+++'))
    rules = {'broad_exception': r'except\s*(?:\([^)]*\)|Exception|BaseException)?\s*:',
             'runner_manipulation': r'sys\.modules|PYTEST|pytest|unittest|__import__|os\.environ',
             'disabled_assertion': r'assert\s+True|__debug__|optimize\s*=',
             'possible_input_special_case': r'\binput\b.*(?:==|\bin\b)|case_id|expected|holdout'}
    return [name for name, pattern in rules.items() if re.search(pattern, added)]


def execute(*, source_repo, source_ref, contract_repo, contract_ref, patch_path,
            private_key, output, request_id, contract_file='contract.json', review_path=None):
    """Called only by the clean trusted supervisor entrypoint."""
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError('A verifier-issued request ID is required for replay checks')
    primitives()
    with Path(patch_path).open('rb') as stream:
        patch = stream.read(PATCH_LIMIT + 1)
    if len(patch) > PATCH_LIMIT:
        raise ValueError('Submitted patch exceeds the 2 MiB limit')
    output = Path(output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    safe_path(contract_file)
    record = {'schema_version': 1, 'request_id': request_id, 'created_at': utc_now(),
              'status': 'rejected', 'verification_eligible': False,
              'trust_profile': 'external-supervisor/docker-target', 'source_commit': source_ref,
              'contract_commit': contract_ref, 'contract_file': contract_file,
              'patch_sha256': sha(patch), 'engine_sha256': engine_hash(),
              'supervisor_environment': {'python': sys.version.split()[0], 'platform': platform.platform()},
              'supervisor_dependencies': {'cryptography': version('cryptography')},
              'reason': 'Verification did not complete'}
    try:
        with tempfile.TemporaryDirectory(prefix='evals-verifier-') as temporary:
            root = Path(temporary).resolve()
            contract_dir, baseline, candidate = (root / p for p in ('contract', 'baseline', 'candidate'))
            contract_dir.mkdir()
            record['contract_sha256'], _ = pinned_tree(contract_repo, contract_ref, contract_dir)
            contract = read_json(contract_dir / contract_file)
            validate_contract(contract)
            record['environment_image_digest'] = contract['environment_image']
            baseline.mkdir()
            record['source_tree_sha256'], source_entries = pinned_tree(
                source_repo, source_ref, baseline, paths=contract['application_paths'])
            shutil.copytree(baseline, candidate)
            record['changed_paths'] = apply_patch(candidate, patch, contract['application_paths'],
                                                   source_entries=source_entries)
            # Remove Git metadata by exporting only the index's files to a clean mount.
            app_candidate = root / 'application'
            app_candidate.mkdir()
            candidate_entries = {}
            for row in git(candidate, 'ls-files', '--stage', '-z').split(b'\0'):
                if row:
                    metadata, raw_name = row.split(b'\t', 1)
                    mode = metadata.split(b' ', 1)[0].decode()
                    name = safe_path(raw_name.decode('utf-8'))
                    dest = app_candidate / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    content = (candidate / name).read_bytes()
                    dest.write_bytes(content)
                    dest.chmod(0o755 if mode == '100755' else 0o644)
                    candidate_entries[name] = {'mode': mode, 'sha256': sha(content)}
            record['candidate_tree_sha256'] = sha(canonical(candidate_entries))
            specs = []
            for split in ('public', 'holdout'):
                for name in contract[split + '_suites']:
                    suite = read_json(contract_dir / name)
                    if suite.get('mode', 'live') != 'live':
                        raise ValueError('Verifier requires live application execution, never stored baseline reports')
                    if any(case.get('observation') is not None for case in suite['cases']):
                        raise ValueError('Recorded observations are forbidden')
                    for case in suite['cases']:
                        for grader in case['graders']:
                            if grader['type'] == 'custom':
                                adapter = grader['adapter']
                                if adapter.get('type') != 'python':
                                    raise ValueError('Verifier custom graders must use trusted Python files')
                                safe_path(adapter['path'])
                    suite['target'] = {'type': 'python', 'path': str(baseline / contract['entrypoint'])}
                    validate_suite(suite, contract_dir)
                    specs.append((split, name, suite))
            planned = 2 * sum(len(s['cases']) * s.get('trials', 1) for _, _, s in specs)
            if planned > contract.get('max_target_calls', 100):
                raise ValueError('Baseline and candidate exceed the pinned target-call budget')
            record.update(planned_target_calls=planned, review_findings=review_patch(patch))
            public_inputs = {sha(canonical({'input': c['input'], 'context': c.get('context')}))
                             for split, _, s in specs if split == 'public' for c in s['cases']}
            holdout_inputs = {sha(canonical({'input': c['input'], 'context': c.get('context')}))
                              for split, _, s in specs if split == 'holdout' for c in s['cases']}
            if public_inputs & holdout_inputs:
                raise ValueError('Holdout inputs must differ from public inputs')
            review = None
            if review_path:
                review = read_json(review_path)
                if (not isinstance(review, dict) or set(review) != {'patch_sha256', 'reviewer', 'verdict', 'rationale'}
                        or review['patch_sha256'] != record['patch_sha256']
                        or review['verdict'] not in {'approved', 'rejected'}
                        or any(not isinstance(review[k], str) or not review[k].strip() for k in ('reviewer', 'rationale'))):
                    raise ValueError('Review must identify the reviewer, patch hash, verdict and rationale')
                record['review'] = review
                record['review_sha256'] = sha(canonical(review))
            summaries, comparisons, invariant_ok = [], [], True
            baseline_ok = True
            candidate_ok = True
            # Baseline is recomputed from the pinned original for every submission.
            for index, (split, name, suite) in enumerate(specs):
                before = run_suite(suite, contract_dir,
                                   target_invoker=lambda p: container_target(contract, baseline, p))
                after_suite = copy.deepcopy(suite)
                after_suite['target']['path'] = str(app_candidate / contract['entrypoint'])
                after = run_suite(after_suite, contract_dir,
                                  target_invoker=lambda p: container_target(contract, app_candidate, p))
                expected = {'collected': len(suite['cases']) * suite.get('trials', 1), 'skipped': 0, 'xfail': 0,
                            'trials': [[case['id'], trial,
                                        [g.get('id', str(i + 1)) for i, g in enumerate(case['graders'])]]
                                       for case in suite['cases'] for trial in range(1, suite.get('trials', 1) + 1)]}
                actual_before, actual_after = inventory(before), inventory(after)
                invariant_ok &= actual_before == expected and actual_after == expected
                comparisons.append(compare_reports(before, after))
                baseline_ok &= before['summary']['error'] == 0
                candidate_ok &= after['summary']['failed'] == after['summary']['error'] == 0
                summaries.append({'split': split, 'baseline': before['summary'], 'candidate': after['summary']})
                # Private evidence only: never upload this directory as a public artifact.
                write_json(output / 'private' / f'{index}-baseline.json', before)
                write_json(output / 'private' / f'{index}-candidate.json', after)
                write_json(output / 'private' / f'{index}-inventory.json',
                           {'expected': expected, 'baseline': actual_before, 'candidate': actual_after})
            improved = any(c['improvements'] or c['metric_improvements'] for c in comparisons)
            regressions = any(c['regressions'] or c['metric_regressions'] for c in comparisons)
            checks_passed = bool(invariant_ok and baseline_ok and candidate_ok and not regressions)
            review_ok = ((review is not None and review['verdict'] == 'approved') or
                         (not contract.get('require_review', True) and review is None))
            eligible = checks_passed and review_ok
            status = ('verified_improvement' if eligible and improved else
                      'baseline_satisfied' if eligible else
                      'needs_review' if checks_passed and review is None else 'not_verified')
            record.update(status=status, verification_eligible=eligible,
                          checks_passed=checks_passed, review_required=contract.get('require_review', True),
                          count_invariants_match=bool(invariant_ok), suites=summaries,
                          reason=('All pinned public and holdout checks passed without regressions'
                                  if eligible else 'Trusted diff review is required' if status == 'needs_review' else
                                  'Evaluation errors, count mismatch, failed checks, regressions or rejected review'))
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        # Error detail remains verifier-private; signed public decision does not leak holdout contents.
        write_json(output / 'private' / 'error.json', {'type': type(exc).__name__, 'detail': str(exc)})
        record.update(status='rejected', verification_eligible=False,
                      reason='Verifier rejected the submission; consult private diagnostics')
    record['completed_at'] = utc_now()
    record['private_evidence_sha256'] = {
        path.relative_to(output).as_posix(): sha(path.read_bytes())
        for path in sorted((output / 'private').glob('*.json'))}
    write_json(output / 'decision.json', sign(record, private_key))
    return record


def launch(**kwargs):
    """Clean -I supervisor. Must be invoked on an independently controlled runner."""
    bootstrap = Path(__file__).with_name('verifier_worker.py').resolve()
    result = subprocess.run([sys.executable, '-I', str(bootstrap)], input=canonical(kwargs),
                            capture_output=True, env=clean_environment(), timeout=86400)
    if result.returncode:
        raise ValueError('Trusted verifier failed: ' + result.stderr.decode('utf-8', errors='replace')[-1500:])
    return json.loads(result.stdout)


def submit(source_repo, source_ref, paths, output):
    output = Path(output)
    if output.exists():
        raise ValueError('Refusing to overwrite a patch')
    for path in paths:
        safe_path(path)
        if protected(path):
            raise ValueError('Protected path cannot be allowlisted')
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', source_ref):
        raise ValueError('Submit against a full pinned source commit')
    if git(source_repo, 'rev-parse', '--verify', source_ref + '^{commit}').decode().strip() != source_ref:
        raise ValueError('Source ref must identify the pinned commit itself')
    if git(source_repo, 'ls-files', '--others', '--exclude-standard').strip():
        raise ValueError('Untracked files would be omitted; use git add -N for intended new application files')
    patch = git(source_repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--binary', source_ref, '--')
    # Validate the submitted result exactly as the remote verifier will, without
    # executing the application or sending any grading data to the agent.
    with tempfile.TemporaryDirectory(prefix='evals-submit-') as temporary:
        app = Path(temporary)
        _, source_entries = pinned_tree(source_repo, source_ref, app, paths=paths)
        changed = apply_patch(app, patch, paths, source_entries=source_entries)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(patch)
    return {'patch': str(output.resolve()), 'patch_sha256': sha(patch), 'source_commit': source_ref,
            'changed_paths': changed, 'scope': 'Tracked diff only; remote contract controls the actual allowlist'}


def verify_decision(envelope, public_key, *, patch, source_ref, contract_ref, request_id,
                    contract_file='contract.json'):
    from evals.signing import verify
    record = verify(envelope, public_key)
    expected = {'schema_version': 1, 'patch_sha256': sha(Path(patch).read_bytes()),
                'source_commit': source_ref, 'contract_commit': contract_ref, 'request_id': request_id,
                'contract_file': contract_file,
                'trust_profile': 'external-supervisor/docker-target'}
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError('Signed decision does not match this patch, pinned refs or verifier request')
    return record
