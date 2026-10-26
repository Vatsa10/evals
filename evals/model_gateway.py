"""Bounded model-only capability, isolated from graders and application code."""

from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import uuid


def validate(config):
    if (not isinstance(config, dict) or set(config) - {'backend', 'max_model_calls', 'timeout_seconds'}
            or config.get('backend') not in {'claude-cli', 'fixture'}):
        raise ValueError('Model gateway supports only claude-cli or explicitly labeled fixture backends')
    for key, default, maximum in [('max_model_calls', 12, 1000), ('timeout_seconds', 120, 180)]:
        value = config.get(key, default)
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f'Model gateway {key} must be an integer from 1 to {maximum}')


class ModelGateway:
    def __init__(self, config, image):
        validate(config)
        self.config, self.image = config, image
        self.records = []
        self.lock = threading.Lock()
        self.model_ids = set()
        self.version = None
        self.rejected_calls = 0

    def complete(self, prompt, *, scope=None):
        from evals.verifier import bounded_run
        if not isinstance(prompt, str) or not prompt or len(prompt.encode('utf-8')) > 32768:
            raise ValueError('Invalid model prompt')
        with self.lock:
            if len(self.records) >= self.config.get('max_model_calls', 12):
                self.rejected_calls += 1
                raise RuntimeError('Pinned model-call budget exhausted')
            record = {'number': len(self.records) + 1, 'status': 'started', 'prompt': prompt,
                      'scope': scope or {}}
            self.records.append(record)
        started = time.monotonic()
        try:
            if self.config['backend'] == 'fixture':
                reply = {'text': 'fixture-model-response', 'model_ids': ['deterministic-test-double'], 'usage': {}}
            else:
                claude = shutil.which('claude')
                if not claude:
                    raise RuntimeError('The trusted runner needs an authenticated Claude CLI')
                if self.version is None:
                    self.version = bounded_run([claude, '--version'], b'', 15).decode().strip()
                # Tools, slash commands, MCP and hooks are disabled. Prompt text
                # is stdin, never a command or a user-controlled CLI argument.
                argv = [claude, '--print', '--output-format', 'json', '--no-session-persistence',
                        '--tools', '', '--disable-slash-commands', '--strict-mcp-config',
                        '--mcp-config', json.dumps({'mcpServers': {}}),
                        '--settings', json.dumps({'disableAllHooks': True})]
                with tempfile.TemporaryDirectory(prefix='evals-gateway-provider-') as folder:
                    # bounded_run uses a clean environment; HOME preserves the
                    # operator's existing login. No credentials reach the target.
                    raw = bounded_run(argv, prompt.encode('utf-8'), self.config.get('timeout_seconds', 120), cwd=folder)
                envelope = json.loads(raw)
                if isinstance(envelope, list):
                    envelope = next((e for e in reversed(envelope) if isinstance(e, dict) and e.get('type') == 'result'), None)
                if not isinstance(envelope, dict) or envelope.get('is_error') or not isinstance(envelope.get('result'), str):
                    raise RuntimeError('Model provider returned no successful text result')
                if len(envelope['result'].encode('utf-8')) > 65536:
                    raise RuntimeError('Model reply exceeds the 64 KiB limit')
                reply = {'text': envelope['result'], 'model_ids': sorted(envelope.get('modelUsage', {})),
                         'usage': envelope.get('usage', {})}
            self.model_ids.update(reply['model_ids'])
            record.update(status='completed', response=reply)
            return reply
        except Exception as exc:
            record.update(status='error', error=type(exc).__name__, error_detail=str(exc))
            raise
        finally:
            record['duration_ms'] = round((time.monotonic() - started) * 1000, 3)

    def summary(self):
        usage = {key: sum(r.get('response', {}).get('usage', {}).get(key, 0)
                          for r in self.records
                          if type(r.get('response', {}).get('usage', {}).get(key, 0)) is int)
                 for key in ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')}
        return {'backend': self.config['backend'], 'live': self.config['backend'] != 'fixture',
                'transport': 'docker-tmpfs-mailbox', 'model_calls': len(self.records),
                'completed': sum(r['status'] == 'completed' for r in self.records),
                'errors': sum(r['status'] == 'error' for r in self.records),
                'rejected_calls': self.rejected_calls,
                'max_model_calls': self.config.get('max_model_calls', 12),
                'model_ids': sorted(self.model_ids), 'provider_cli_version': self.version, 'usage': usage}

    @contextmanager
    def channel(self, *, scope=None):
        from evals.verifier import clean_environment
        docker = shutil.which('docker')
        if not docker:
            raise ValueError('Docker is required for the model gateway')
        name = 'evals-gateway-' + uuid.uuid4().hex
        volume = name + '-mailbox'
        process, thread = None, None
        ready, stopped = threading.Event(), threading.Event()
        failures, completed = [], []
        def command(*args):
            result = subprocess.run([docker, *args], capture_output=True, env=clean_environment(), timeout=30)
            if result.returncode:
                raise RuntimeError('Docker model-gateway setup failed')
            return result
        try:
            command('volume', 'create', '--driver=local', '--opt=type=tmpfs', '--opt=device=tmpfs',
                    '--opt=o=size=2m,nodev,nosuid,noexec,mode=1777', volume)
            relay = Path(__file__).with_name('gateway_relay.py').resolve()
            argv = [docker, 'run', '--rm', '--pull=never', '--name', name, '-i', '--network=none',
                    '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                    '--pids-limit=16', '--memory=64m', '--cpus=0.5', '--log-driver=none',
                    '--mount', f'type=volume,source={volume},target=/model-gateway',
                    '--mount', f'type=bind,source={relay},target=/relay.py,readonly',
                    '--entrypoint=/usr/bin/env', self.image, '-i', 'PATH=/usr/local/bin:/usr/bin:/bin',
                    'HOME=/tmp', 'python', '-I', '-B', '/relay.py']
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, env=clean_environment())
            def serve():
                try:
                    while not stopped.is_set():
                        raw = process.stdout.readline(65537)
                        if not raw or len(raw) > 65536:
                            raise RuntimeError('Model relay stopped or exceeded its event limit')
                        event = json.loads(raw)
                        if event.get('event') == 'ready':
                            ready.set()
                        elif event.get('event') == 'request':
                            try:
                                reply = dict(self.complete(event['prompt'], scope=scope), id=event['id'])
                                completed.append(event['id'])
                            except Exception:
                                reply = {'id': event['id'], 'error': 'Trusted model gateway failed; inspect verifier-private evidence'}
                            process.stdin.write(json.dumps(reply, allow_nan=False).encode() + b'\n')
                            process.stdin.flush()
                        else:
                            raise RuntimeError('Invalid model relay request')
                except Exception as exc:
                    if not stopped.is_set():
                        failures.append(type(exc).__name__)
                    ready.set()
            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            if not ready.wait(15) or failures:
                raise RuntimeError('Model relay did not become ready')
            yield {'volume': volume, 'completed': completed, 'failures': failures}
        finally:
            stopped.set()
            subprocess.run([docker, 'rm', '-f', name], capture_output=True, timeout=30,
                           env=clean_environment(), check=False)
            if process:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if thread:
                    thread.join(timeout=self.config.get('timeout_seconds', 120) + 25)
                    if thread.is_alive():
                        raise RuntimeError('Model gateway did not stop within its provider deadline')
                process.stdin.close()
                process.stdout.close()
            subprocess.run([docker, 'volume', 'rm', '-f', volume], capture_output=True, timeout=30,
                           env=clean_environment(), check=False)
