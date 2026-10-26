"""Trusted pytest process. Application code is never imported here."""

from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

import pytest

protocol = sys.stdout


def emit(value):
    protocol.write(json.dumps(value, allow_nan=False) + '\n')
    protocol.flush()


class Plugin:
    def __init__(self):
        self.nodeids, self.deselected, self.collection_errors = [], [], []
        self.forbidden_markers = []
        self.outcomes = {}

    @pytest.fixture
    def evals_target(self, request):
        def target(input, context=None):
            emit({'event': 'target', 'input': input, 'context': context, 'node_id': request.node.nodeid})
            raw = sys.stdin.readline(1048577)
            if not raw or len(raw) > 1048576:
                raise RuntimeError('Verifier target channel stopped')
            reply = json.loads(raw)
            if 'error' in reply:
                raise RuntimeError(reply['error'])
            return reply['observation']
        return target

    def pytest_collection_finish(self, session):
        self.nodeids = [item.nodeid for item in session.items]
        self.forbidden_markers = [item.nodeid for item in session.items
                                  if any(m.name in {'skip', 'skipif', 'xfail'} for m in item.iter_markers())]

    def pytest_deselected(self, items):
        self.deselected.extend(item.nodeid for item in items)

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_errors.append(report.nodeid)

    def pytest_runtest_logreport(self, report):
        if report.failed:
            self.outcomes[report.nodeid] = 'failed' if report.when == 'call' else 'error'
        elif getattr(report, 'wasxfail', None) is not None:
            self.outcomes[report.nodeid] = 'xfail' if report.skipped else 'xpassed'
        elif report.skipped:
            self.outcomes[report.nodeid] = 'skipped'
        elif report.when == 'call' and self.outcomes.get(report.nodeid) != 'error':
            self.outcomes[report.nodeid] = 'passed'


def main():
    config = json.loads(sys.stdin.readline())
    root = Path(config['root']).resolve()
    # Only the pinned grading directory is importable, never application paths.
    sys.path.insert(0, str(root))
    empty = root / config['empty_config']
    plugin = Plugin()
    argv = ['-q', '-s', '--noconftest', '--import-mode=importlib', '-p', 'no:cacheprovider',
            '-p', 'no:doctest', '-c', str(empty), '--rootdir', str(root), '--', *config['tests']]
    with redirect_stdout(sys.stderr):
        code = int(pytest.main(argv, plugins=[plugin]))
    counts = {status: sum(value == status for value in plugin.outcomes.values())
              for status in ('passed', 'failed', 'error', 'skipped', 'xfail', 'xpassed')}
    counts['error'] += len(plugin.collection_errors) + int(code not in {0, 1})
    emit({'event': 'result', 'nodeids': plugin.nodeids, 'deselected': plugin.deselected,
          'outcomes': plugin.outcomes, 'exit_code': code, 'pytest_version': pytest.__version__,
          'forbidden_markers': plugin.forbidden_markers,
          'summary': {'collected': len(plugin.nodeids), **counts}})


if __name__ == '__main__':
    main()
