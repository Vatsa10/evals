"""Consume a private test kit using the independently installed trusted engine."""

import json
from pathlib import Path
import re
import subprocess

from evals import __version__
from evals.artifacts import read_json, write_json
from evals.verifier import clean_environment, git, launch, sha, validate_contract, verify_decision


def run(kit, output, private_key, public_key, request_id, review=None):
    kit, output = Path(kit).resolve(), Path(output).resolve()
    plan = read_json(kit / 'plan.json')
    if plan.get('schema_version') != 1 or plan['engine_version'] != __version__:
        raise ValueError('Install the exact reviewed engine version before running this kit')
    if plan['model'] not in {'live', 'fixture'}:
        raise ValueError('Kit must explicitly declare live inference or a model fixture')
    required = {'source.bundle', 'grading-contract.bundle', 'candidate.patch',
                'verifier-requirements.lock', 'review-template.json'}
    if set(plan['files']) != required:
        raise ValueError('Kit must contain exactly the declared data files, never executable helper code')
    for name, expected in plan['files'].items():
        if Path(name).name != name or sha((kit / name).read_bytes()) != expected:
            raise ValueError('Remote kit file mismatch: ' + name)
    for key in ('source_ref', 'contract_ref', 'engine_commit'):
        if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', plan[key]):
            raise ValueError('Remote kit requires full pinned commits')
    if not Path(private_key).is_file() or not Path(public_key).is_file():
        raise ValueError('Provision the signing key pair on this trusted machine first')
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, bundle in [('source', 'source.bundle'), ('contract', 'grading-contract.bundle')]:
        git(output, 'clone', '--quiet', '--no-checkout', str(kit / bundle), str(output / name))
    config = json.loads(git(output / 'contract', 'show', plan['contract_ref'] + ':contract.json'))
    validate_contract(config)
    if config['environment_image'] != plan['environment_image']:
        raise ValueError('Kit image differs from the pinned grading contract')
    if (config.get('model_gateway', {}).get('backend') == 'claude-cli') != (plan['model'] == 'live'):
        raise ValueError('Kit model provenance differs from its pinned contract')
    subprocess.run(['docker', 'pull', config['environment_image']], check=True, env=clean_environment())
    record = launch(source_repo=str(output / 'source'), source_ref=plan['source_ref'],
        contract_repo=str(output / 'contract'), contract_ref=plan['contract_ref'],
        patch_path=str(kit / 'candidate.patch'), private_key=str(Path(private_key).resolve()),
        output=str(output / 'result'), request_id=request_id,
        review_path=str(Path(review).resolve()) if review else None)
    verified = verify_decision(read_json(output / 'result' / 'decision.json'), public_key,
        patch=kit / 'candidate.patch', source_ref=plan['source_ref'], contract_ref=plan['contract_ref'], request_id=request_id,
        require_live_model=plan['model'] == 'live')
    summary = {'status': verified['status'], 'signature_verified': True,
               'verification_eligible': record['verification_eligible'], 'model_gateway': record.get('model_gateway'),
               'count_invariants_match': record.get('count_invariants_match'),
               'execution': 'standalone_runner_command', 'account_isolation': 'operator_provisioned_not_attested'}
    write_json(output / 'summary.json', summary)
    return summary
