"""Small copyable target-side client. No provider credentials or network access.

Only one request may be active per target. Threads are serialized here; multiple
processes must coordinate mailbox access. The external verifier owns its lifetime.
"""

import json
import os
from pathlib import Path
import threading
import time
import uuid

_lock = threading.Lock()


def complete(prompt, timeout=150):
    if not isinstance(prompt, str) or not prompt or len(prompt.encode('utf-8')) > 32768:
        raise ValueError('Model prompt must be a nonempty string within 32 KiB')
    directory = Path(os.environ.get('EVALS_MODEL_MAILBOX', '/model-gateway'))
    identity = uuid.uuid4().hex
    with _lock:
        temporary = directory / (identity + '.request')
        temporary.write_text(json.dumps({'id': identity, 'prompt': prompt}), encoding='utf-8')
        temporary.replace(directory / 'request.json')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                reply = json.loads((directory / 'response.json').read_text(encoding='utf-8'))
            except FileNotFoundError:
                time.sleep(0.02)
                continue
            if reply.get('id') != identity:
                time.sleep(0.02)
                continue
            if 'error' in reply:
                raise RuntimeError(reply['error'])
            if not isinstance(reply.get('text'), str):
                raise RuntimeError('Model gateway returned an invalid reply')
            return reply
    raise TimeoutError('Model gateway did not reply within the target deadline')
