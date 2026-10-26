"""Network-disabled mailbox relay. Only its bounded tmpfs volume is shared.

The provider is NOT in this container. Fixed JSON events travel to the trusted
supervisor over Docker's stdin/stdout. Symlinks resolve only inside this
credential-free, network-disabled container, never on the supervisor host.
"""

import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

LIMIT = 262144  # 32 KiB prompt plus worst-case JSON escaping and framing.


def emit(value):
    print(json.dumps(value, allow_nan=False), flush=True)


def read_request(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > LIMIT:
            raise ValueError('Invalid mailbox request file')
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Mailbox request exceeds size limit')
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) != {'id', 'prompt'} or
            not isinstance(value['id'], str) or not re.fullmatch('[0-9a-f]{32}', value['id']) or
            not isinstance(value['prompt'], str) or not value['prompt'] or
            len(value['prompt'].encode('utf-8')) > 32768):
        raise ValueError('Invalid model request schema')
    return value


def main():
    directory = Path('/model-gateway')
    # Root owns this sticky directory. The target UID cannot chmod it or replace
    # root-owned replies; the relay has no capabilities, credentials or network.
    os.chmod(directory, 0o1777)
    seen = set()
    emit({'event': 'ready'})
    while True:
        path = directory / 'request.json'
        try:
            value = read_request(path)
        except FileNotFoundError:
            time.sleep(0.02)
            continue
        except (OSError, ValueError, TypeError):
            emit({'event': 'invalid_request'})
            return 1
        path.unlink()
        if value['id'] in seen or len(seen) >= 100:
            emit({'event': 'invalid_request'})
            return 1
        seen.add(value['id'])
        emit({'event': 'request', **value})
        raw = sys.stdin.buffer.readline(524289)
        if not raw or len(raw) > 524288:
            return 1
        reply = json.loads(raw)
        if reply.get('id') != value['id']:
            return 1
        temporary = directory / (uuid.uuid4().hex + '.reply')
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(reply, stream, allow_nan=False)
        temporary.replace(directory / 'response.json')


if __name__ == '__main__':
    raise SystemExit(main())
