"""Run private pytest assertions against a JSON/RPC target capability only."""

import json
from pathlib import Path
import subprocess
import sys
import threading

from evals.artifacts import read_json
from evals.engine import validate_observation


def validate_config(config):
    from evals.verifier import safe_path
    if not isinstance(config, dict) or set(config) != {'public_tests', 'holdout_tests', 'manifest', 'timeout_seconds'}:
        raise ValueError('pytest requires public_tests, holdout_tests, manifest and timeout_seconds')
    for key in ('public_tests', 'holdout_tests'):
        if not isinstance(config[key], list) or not config[key] or len(set(config[key])) != len(config[key]):
            raise ValueError('pytest test paths must be nonempty unique lists')
        for path in config[key]:
            safe_path(path)
    if set(config['public_tests']) & set(config['holdout_tests']):
        raise ValueError('pytest public and holdout paths must be different')
    safe_path(config['manifest'])
    if type(config['timeout_seconds']) is not int or not 1 <= config['timeout_seconds'] <= 3600:
        raise ValueError('pytest timeout_seconds must be between 1 and 3600')


def load_manifest(root, config):
    validate_config(config)
    manifest = read_json(root / config['manifest'])
    if not isinstance(manifest, dict) or set(manifest) != {'public', 'holdout'}:
        raise ValueError('pytest manifest must specify public and holdout inventories')
    for spec in manifest.values():
        if not isinstance(spec, dict) or set(spec) != {'nodeids', 'skipped', 'xfail', 'xpassed', 'deselected', 'target_calls'}:
            raise ValueError('pytest inventory requires nodeids, outcome counts and exact target_calls')
        if (not isinstance(spec['nodeids'], list) or not spec['nodeids'] or
                any(not isinstance(n, str) or not n for n in spec['nodeids']) or
                len(set(spec['nodeids'])) != len(spec['nodeids'])):
            raise ValueError('pytest node IDs must be unique nonempty strings')
        if any(type(spec[key]) is not int or spec[key] != 0 for key in ('skipped', 'xfail', 'xpassed', 'deselected')):
            raise ValueError('The strict pytest profile permits no skipped, xfail, xpass or deselected tests')
        if type(spec['target_calls']) is not int or not 1 <= spec['target_calls'] <= 10000:
            raise ValueError('pytest inventory requires a positive exact target-call count')
    return manifest


def run_tests(root, config, split, target):
    from evals.verifier import clean_environment
    environment = dict(clean_environment(), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    empty_name = '.evals-verifier-pytest.ini'
    if (root / empty_name).exists():
        raise ValueError('Reserved verifier pytest configuration path already exists')
    (root / empty_name).write_text('[pytest]\n', encoding='utf-8')
    worker = Path(__file__).with_name('pytest_worker.py').resolve()
    process = subprocess.Popen([sys.executable, '-I', str(worker)], cwd=root, env=environment,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    errors, observations = bytearray(), []
    def drain():
        while chunk := process.stderr.read(4096):
            if len(errors) + len(chunk) > 2 * 1024 * 1024:
                process.kill()
                break
            errors.extend(chunk)
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    watchdog = threading.Timer(config['timeout_seconds'], process.kill)
    watchdog.daemon = True
    watchdog.start()
    result = None
    try:
        process.stdin.write(json.dumps({'root': str(root), 'tests': config[split + '_tests'],
                                        'empty_config': empty_name}).encode() + b'\n')
        process.stdin.flush()
        while True:
            raw = process.stdout.readline(1048577)
            if not raw:
                break
            if len(raw) > 1048576:
                raise RuntimeError('pytest protocol event exceeds the size limit')
            event = json.loads(raw)
            if event.get('event') == 'target':
                try:
                    observation = target({'input': event['input'], 'context': event.get('context'),
                                          'case_id': 'pytest:' + event['node_id'], 'trial': 1})
                    validate_observation(observation)
                    observations.append(observation)
                    reply = {'observation': observation}
                except Exception as exc:
                    observations.append({'error': type(exc).__name__})
                    reply = {'error': 'Isolated target failed; inspect verifier-private evidence'}
                process.stdin.write(json.dumps(reply, allow_nan=False).encode() + b'\n')
                process.stdin.flush()
            elif event.get('event') == 'result' and result is None:
                result = event
            else:
                raise RuntimeError('Unexpected pytest protocol event')
        process.wait(timeout=10)
        if process.returncode or result is None:
            raise RuntimeError('Trusted pytest process failed or timed out')
        result.update(target_calls=len(observations), observations=observations,
                      stderr=errors.decode('utf-8', errors='replace'))
        return result
    finally:
        watchdog.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()
        reader.join(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
        (root / empty_name).unlink(missing_ok=True)


def invariants(result, expected):
    counts = result['summary']
    return (not result['forbidden_markers'] and sorted(result['nodeids']) == sorted(expected['nodeids']) and
            len(result['nodeids']) == len(set(result['nodeids'])) == counts['collected'] and
            counts['skipped'] == expected['skipped'] and counts['xfail'] == expected['xfail'] and
            counts['xpassed'] == expected['xpassed'] and len(result['deselected']) == expected['deselected'] and
            result['target_calls'] == expected['target_calls'] and
            sum(counts[k] for k in ('passed', 'failed', 'error', 'skipped', 'xfail', 'xpassed')) == counts['collected'])
