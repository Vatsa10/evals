"""Optional Ed25519 decision signatures; public keys must be trusted out of band."""

import base64
import hashlib
import json
import os
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def primitives():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
        from cryptography.hazmat.primitives import serialization
    except ImportError as exc:
        raise ValueError('Install the verifier extra: pip install "evals-framework[verifier]"') from exc
    return Ed25519PrivateKey, Ed25519PublicKey, serialization


def keygen(private_path, public_path):
    private_path, public_path = Path(private_path), Path(public_path)
    if private_path.resolve() == public_path.resolve() or private_path.exists() or public_path.exists():
        raise ValueError('Key paths must be different and must not already exist')
    private, _, serialization = primitives()
    key = private.generate()
    # 0600 on POSIX. On Windows, provision a restricted ACL on the parent folder.
    with os.fdopen(os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
        stream.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    with os.fdopen(os.open(public_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644), 'wb') as stream:
        stream.write(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                  serialization.PublicFormat.SubjectPublicKeyInfo))


def sign(record, private_path):
    private, _, serialization = primitives()
    key = serialization.load_pem_private_key(Path(private_path).read_bytes(), password=None)
    if not isinstance(key, private):
        raise ValueError('Verifier requires an Ed25519 private key')
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {'record': record, 'signature': {'algorithm': 'Ed25519',
            'key_id': hashlib.sha256(public).hexdigest(),
            'value': base64.b64encode(key.sign(canonical(record))).decode('ascii')}}


def verify(envelope, public_path):
    _, public, serialization = primitives()
    from cryptography.exceptions import InvalidSignature
    key = serialization.load_pem_public_key(Path(public_path).read_bytes())
    if not isinstance(key, public):
        raise ValueError('Verifier requires an Ed25519 public key')
    metadata = envelope['signature']
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if metadata['algorithm'] != 'Ed25519' or metadata['key_id'] != hashlib.sha256(raw).hexdigest():
        raise ValueError('Decision signing identity does not match the trusted public key')
    try:
        key.verify(base64.b64decode(metadata['value'], validate=True), canonical(envelope['record']))
    except (InvalidSignature, ValueError) as exc:
        raise ValueError('Invalid decision signature') from exc
    return envelope['record']
