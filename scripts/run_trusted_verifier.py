"""GitHub Actions entrypoint. Dispatch input is data, never shell source.

Use only in a protected verifier job; never in pull_request_target with untrusted
checkout code. Keep the contract repository, engine and private key inaccessible
to the coding agent. Only decision.json is suitable for publication.
"""

import base64
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals.verifier import clean_environment, launch, validate_contract


def main():
    runtime = Path(os.environ['RUNNER_TEMP']) / 'evals-verification'
    runtime.mkdir(exist_ok=False)
    patch = runtime / 'candidate.patch'
    patch.write_bytes(base64.b64decode(os.environ['SUBMITTED_PATCH'], validate=True))
    private = runtime / 'decision-key.pem'
    private_pem = os.environ.pop('VERIFIER_SIGNING_KEY')
    review = None
    if os.environ.get('TRUSTED_REVIEW'):
        review = runtime / 'review.json'
        review.write_bytes(base64.b64decode(os.environ['TRUSTED_REVIEW'], validate=True))
    # Do not read runtime policy from a dirty checkout. execute() reads the pinned
    # contract; pulling its image can be handled separately by a trusted operator.
    contract_root = ROOT.parent / 'trusted-contract'
    from evals.verifier import git
    import json
    import subprocess
    config = json.loads(git(contract_root, 'show', os.environ['CONTRACT_COMMIT'] + ':contract.json'))
    validate_contract(config)
    if config.get('model_gateway', {}).get('backend') == 'claude-cli':
        import shutil
        if not shutil.which('claude'):
            raise ValueError('Live verification requires a protected runner with an authenticated Claude CLI')
    subprocess.run(['docker', 'pull', config['environment_image']], check=True, env=clean_environment())
    try:
        descriptor = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(private_pem)
        del private_pem
        record = launch(source_repo=str(ROOT.parent / 'trusted-source'), source_ref=os.environ['SOURCE_COMMIT'],
            contract_repo=str(contract_root), contract_ref=os.environ['CONTRACT_COMMIT'],
            patch_path=str(patch), private_key=str(private), output=str(runtime / 'result'),
            request_id=os.environ['VERIFICATION_REQUEST_ID'], review_path=str(review) if review else None)
        # Upload from here only. No raw holdouts, reports, traces or key files.
        public = Path(os.environ['RUNNER_TEMP']) / 'evals-public-decision'
        public.mkdir(exist_ok=False)
        (public / 'decision.json').write_bytes((runtime / 'result' / 'decision.json').read_bytes())
        print('Verifier status: ' + record['status'])
        return int(not record['verification_eligible'])
    finally:
        private.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
