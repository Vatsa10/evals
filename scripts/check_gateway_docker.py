"""Adversarial mailbox checks with real Docker and an explicit model double."""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals.model_gateway import ModelGateway
from evals.verifier import container_target

IMAGE = 'python@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962'


def check():
    with tempfile.TemporaryDirectory(prefix='evals-mailbox-attacks-') as temporary:
        root = Path(temporary).resolve() / 'application'
        root.mkdir(mode=0o755)
        shutil.copyfile(ROOT / 'evals' / 'model_client.py', root / 'model_client.py')
        config = {'environment_image': IMAGE, 'entrypoint': 'adapter.py', 'timeout_seconds': 15}
        results = []
        def run(name, code, *, reject=False, expected_calls=None):
            (root / 'adapter.py').write_text(code, encoding='utf-8')
            gateway = ModelGateway({'backend': 'fixture', 'max_model_calls': 1, 'timeout_seconds': 2}, IMAGE)
            observation = None
            try:
                observation = container_target(config, root, {'input': 'test'}, gateway=gateway)
            except RuntimeError:
                if not reject:
                    raise
            else:
                if reject:
                    raise AssertionError(name + ' was not rejected')
            summary = gateway.summary()
            if expected_calls is not None and summary['model_calls'] != expected_calls:
                raise AssertionError(name + ' unexpectedly invoked the provider')
            results.append({'name': name, 'rejected': reject, 'model_gateway': summary})
            print(name + ': passed', flush=True)
            return observation, summary
        observation, _ = run('legitimate-model-call', 'from model_client import complete\ndef evaluate(r):\n    return {"output":complete("hello")["text"]}\n', expected_calls=1)
        if observation['output'] != 'fixture-model-response':
            raise AssertionError('Gateway positive control failed')
        run('required-call', 'def evaluate(r):\n    return {"output":"fake model reply"}\n', reject=True, expected_calls=0)
        for name, request_code in [
                ('symlink', 'os.symlink("/etc/passwd", "/model-gateway/request.json")'),
                ('fifo', 'os.mkfifo("/model-gateway/request.json")'),
                ('traversal-id', 'Path("/model-gateway/request.json").write_text(json.dumps({"id":"../../key", "prompt":"hello"}))'),
                ('arbitrary-command', 'Path("/model-gateway/request.json").write_text(json.dumps({"id":"0"*32,"prompt":"hello","argv":["sh"]}))')]:
            code = ('import os, json, time\nfrom pathlib import Path\ndef evaluate(r):\n    ' + request_code +
                    '\n    time.sleep(0.5)\n    return {"output":"attempted"}\n')
            run(name, code, reject=True, expected_calls=0)
        observation, summary = run('budget-cap', '''from model_client import complete
def evaluate(r):
    complete("first")
    try:
        complete("extra")
    except RuntimeError:
        return {"output":"blocked"}
    return {"output":"not blocked"}
''', expected_calls=1)
        if observation['output'] != 'blocked' or summary['rejected_calls'] != 1:
            raise AssertionError('Model-call budget was bypassed')
        observation, _ = run('escaped-prompt-at-limit', '''from model_client import complete
def evaluate(r):
    return {"output": complete(chr(0) * 32768)["text"]}
''', expected_calls=1)
        if observation['output'] != 'fixture-model-response':
            raise AssertionError('A valid prompt at the documented byte limit was rejected')
        observation, _ = run('isolation-and-bounded-mailbox', '''from model_client import complete
from pathlib import Path
import os, socket
def evaluate(r):
    complete("legitimate request")
    checks = {"no_contract":not Path("/contract").exists(), "no_socket":not Path("/var/run/docker.sock").exists()}
    try:
        socket.create_connection(("1.1.1.1",80), timeout=0.1)
        checks["no_network"] = False
    except OSError:
        checks["no_network"] = True
    try:
        Path("/model-gateway/response.json").write_text("forged")
        checks["root_owned_reply"] = False
    except OSError:
        checks["root_owned_reply"] = True
    try:
        Path("/model-gateway/response.json").unlink()
        checks["sticky_directory"] = False
    except OSError:
        checks["sticky_directory"] = True
    try:
        with Path("/model-gateway/flood").open("wb") as stream:
            stream.write(b"x" * (3 * 1024 * 1024))
        checks["bounded_tmpfs"] = False
    except OSError:
        checks["bounded_tmpfs"] = True
    return {"output":"probe", "checks":checks}
''', expected_calls=1)
        if not all(observation['checks'].values()):
            raise AssertionError('Mailbox isolation failed: ' + str(observation['checks']))
        return results


if __name__ == '__main__':
    try:
        check()
    except Exception:
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            message = traceback.format_exc().replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
            print('::error title=Mailbox integration failure::' + message)
        raise
