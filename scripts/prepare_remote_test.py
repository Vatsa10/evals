"""Create a private, portable remote test kit without account/repository changes."""

import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals.artifacts import read_json, write_json
from evals.verifier import git, sha


def prepare(workspace, output):
    workspace, output = Path(workspace).resolve(), Path(output).resolve()
    plan = read_json(workspace / 'plan.json')
    if git(ROOT, 'status', '--porcelain').strip():
        raise ValueError('Commit the reviewed engine before preparing a kit with its pinned revision')
    engine_ref = git(ROOT, 'rev-parse', 'HEAD').decode().strip()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    git(workspace / plan['source'], 'bundle', 'create', str(output / 'source.bundle'), plan['source_ref'], 'HEAD')
    git(workspace / plan['contract'], 'bundle', 'create', str(output / 'grading-contract.bundle'), plan['contract_ref'], 'HEAD')
    shutil.copyfile(workspace / plan['patch'], output / 'candidate.patch')
    shutil.copyfile(ROOT / 'verifier-requirements.lock', output / 'verifier-requirements.lock')
    write_json(output / 'review-template.json', {
        'patch_sha256': sha((output / 'candidate.patch').read_bytes()),
        'reviewer': 'pending-trusted-review', 'verdict': 'rejected',
        'rationale': 'Not reviewed. A trusted operator must inspect the diff for reward hacking before approving it.'})
    image = read_json(workspace / plan['contract'] / 'contract.json')['environment_image']
    remote = {'schema_version': 1, 'engine_repository': 'https://github.com/Vatsa10/evals.git',
              'engine_commit': engine_ref, 'engine_version': plan['engine_version'],
              'source_ref': plan['source_ref'], 'contract_ref': plan['contract_ref'],
              'environment_image': image, 'model': plan['model'],
              'files': {p.name: sha(p.read_bytes()) for p in sorted(output.iterdir()) if p.is_file()},
              'grading_visibility': 'example holdouts were generated locally; replace them privately for an agent-resistant production test',
              'accounts_changed': False, 'production_execution': False}
    write_json(output / 'plan.json', remote)
    readme = f'''# Standalone remote verification kit

Prepared from engine commit `{engine_ref}` without changing GitHub accounts,
repositories, environment policies or secrets. This directory is PRIVATE.
It contains example grading data. Never publish the bundles or raw results.
It contains NO signing key, provider credentials or raw model traces.

1. Transfer this kit over a trusted channel to a different controlled machine.
   The coding agent must have no shell, Docker, account or signing-key access
   there. These example holdouts were visible during local development; replace
   them with fresh private cases before claiming resistance to this coding agent.
2. Install Docker, Python 3.11+, Git and the reviewed engine:

```console
python -m pip install -r verifier-requirements.lock
python -m pip install "evals-framework[verifier] @ git+https://github.com/Vatsa10/evals.git@{engine_ref}"
```

3. For a live kit, provision an authenticated Claude CLI under the runner's
   account. Its model calls use that account's normal allowance. No interactive
   login or provider switch is performed by the runner script.
4. Generate the key ON THAT MACHINE, in a restricted directory:

```console
evals verifier keygen --private-key decision-key.pem --public-key decision-public.pem
```

5. Review candidate.patch. Copy review-template.json to a trusted review file,
   identify the reviewer and set approved only after reviewing it. The supplied
   template is rejected and cannot authorize a passing decision automatically.
6. Run (choose a fresh request ID and output directory):

```console
evals verifier run-kit --kit . --private-key /trusted/decision-key.pem --public-key /trusted/decision-public.pem --review /trusted/approved-review.json --request-id remote-test-unique-id --output /trusted/test-result
```

The independently installed engine clones pinned Git objects from the bundles, runs baseline and
candidate calls plus private pytest assertions, authenticates the signed receipt
and writes only an aggregate summary to stdout. Publish result/decision.json
only. Keep private/ and the bundles private. Receive the public verification key
through an independent trusted channel before accepting a decision.

The kit contains only data, never a Python or shell runner to execute. File
hashes detect transfer corruption; they do not authenticate an untrusted
kit author. The operator must approve the engine commit, source/contract refs,
image and review. The script cannot attest account or machine isolation.
'''
    (output / 'README.md').write_text(readme, encoding='utf-8')
    return remote


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.workspace, args.output)
    print('Prepared private remote kit: ' + str(args.output.resolve()))
    print('Pinned engine commit: ' + result['engine_commit'])
    print('Account changes: none; remote execution: not performed')
