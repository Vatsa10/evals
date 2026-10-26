"""Import the simple OpenAI input/ideal JSONL format without its runtime."""

import hashlib
import json
from pathlib import Path
import re

from evals.adapters import reject_constant
from evals.artifacts import write_json


def import_jsonl(source, *, name, adapter, output, split='dev', version='v1'):
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError('Refusing to overwrite an existing suite')
    for value in (name, split, version):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
            raise ValueError('Name, split and version must use letters, digits, underscores or hyphens')
    if not isinstance(adapter, str) or not adapter:
        raise ValueError('Supply the real application adapter path')
    content = source.read_bytes()
    cases, identities = [], set()
    for number, line in enumerate(content.decode('utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        sample = json.loads(line, parse_constant=reject_constant)
        if not isinstance(sample, dict) or set(sample) - {'input', 'ideal', 'id'} or 'input' not in sample:
            raise ValueError(f'Line {number}: supports input, ideal and optional id only')
        if not isinstance(sample.get('ideal'), str):
            raise ValueError(f'Line {number}: ideal must be a single string; alternatives/model-graded formats need explicit graders')
        identity = sample.get('id', 'sample-' + hashlib.sha256(
            json.dumps(sample, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16])
        if not isinstance(identity, str) or not identity.strip() or identity in identities:
            raise ValueError(f'Line {number}: invalid or duplicate sample identity')
        identities.add(identity)
        cases.append({'id': identity, 'input': sample['input'],
                      'graders': [{'id': 'exact_match', 'type': 'equals', 'expected': sample['ideal']}]})
    if not cases:
        raise ValueError('Dataset has no samples')
    suite = {'schema_version': 1, 'name': f'{name}.{split}.{version}',
             'target': {'type': 'python', 'path': adapter}, 'cases': cases,
             'dataset_source': {'format': 'openai-input-ideal-jsonl', 'sha256': hashlib.sha256(content).hexdigest(),
                                'split': split, 'version': version}}
    write_json(output, suite)
    return suite
