#!/usr/bin/env python3
"""Render real watcher/fire snippets: drain markers are not read receipts."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MESH = Path(__file__).resolve().parents[1]
ROWS = [
    {'id': 1, 'kind': 'review_request', 'from_plugin': 'codex', 'to_plugin': 'claude-code',
     'pointer_uri': 'file:///one', 'drained_at': None},
    {'id': 2, 'kind': 'review_request', 'from_plugin': 'codex', 'to_plugin': 'claude-code',
     'pointer_uri': 'file:///two', 'drained_at': '2026-10-30T12:00:00Z'},
    {'id': 3, 'kind': 'review_request', 'from_plugin': 'codex', 'to_plugin': 'claude-code',
     'pointer_uri': 'file:///three'},
    {'id': 4, 'kind': 'review_request', 'from_plugin': 'codex', 'to_plugin': 'claude-code',
     'pointer_uri': 'file:///four', 'drained_at': 42},
    {'id': 5, 'kind': 'review_request', 'from_plugin': 'codex', 'to_plugin': 'claude-code',
     'pointer_uri': 'file:///five', 'drained_at': ''},
    {'id': 6, 'kind': 'review_request', 'from_plugin': 'codex', 'to_plugin': 'claude-code',
     'pointer_uri': 'file:///six', 'drained_at': 'not-a-timestamp'},
    {'id': 7, 'kind': 'review_request', 'from_plugin': 'codex', 'to_plugin': 'claude-code',
     'pointer_uri': 'file:///seven', 'drained_at': '2026-10-30T12:00:00.123456789+00:00'},
    {'id': 8, 'kind': 'review_request', 'from_plugin': 'codex', 'to_plugin': 'claude-code',
     'pointer_uri': 'file:///eight', 'drained_at': '2026-02-31T12:00:00Z'},
]
EXPECTED = {1: 'drain mark absent; read status unknown', 2: 'drain mark present; read status unknown',
            3: 'drain mark unknown; read status unknown', 4: 'drain mark unknown; read status unknown',
            5: 'drain mark unknown; read status unknown', 6: 'drain mark unknown; read status unknown',
            7: 'drain mark present; read status unknown', 8: 'drain mark unknown; read status unknown'}


def assert_rows(test, output):
    for number, expected in EXPECTED.items():
        lines = [line for line in output.splitlines() if f'id={number} ' in line]
        test.assertEqual(len(lines), 1, output)
        test.assertIn(expected, lines[0])
    test.assertNotIn('NEVER PICKED UP', output)
    test.assertNotIn('never picked up', output)
    test.assertNotIn('delivered, unanswered', output)


class DrainEvidenceTest(unittest.TestCase):
    def test_watcher_announce_uses_consume_evidence_only(self):
        source = (MESH / 'hestia-watch-member.sh').read_text()
        start = source.index("  printf '%s' \"$OUT\" | python3 -c '\n", source.index('announce_unanswered()'))
        start = source.index('\n', start) + 1
        end = source.index("\n' || true", start)
        process = subprocess.run([sys.executable, '-c', source[start:end]],
                                 input=json.dumps({'i_owe': [], 'owed_to_me': ROWS}),
                                 capture_output=True, text=True, check=True)
        assert_rows(self, process.stdout)

    def test_all_fire_templates_render_consume_evidence_only(self):
        scripts = sorted(MESH.glob('fire-*.sh'))
        self.assertGreaterEqual(len(scripts), 3)
        with tempfile.TemporaryDirectory() as directory:
            primer = Path(directory) / 'primer.json'
            primer.write_text(json.dumps({'unanswered': {'i_owe': [], 'owed_to_me': ROWS}}))
            for script in scripts:
                with self.subTest(script=script.name):
                    source = script.read_text()
                    marker = 'DEBT=$(python3 - "$PRIMER" <<\'PY\'\n'
                    start = source.index(marker) + len(marker)
                    end = source.index('\nPY\n)', start)
                    process = subprocess.run([sys.executable, '-c', source[start:end], str(primer)],
                                             capture_output=True, text=True, check=True)
                    assert_rows(self, process.stdout)
                    self.assertIn('A watcher may perform those reads', process.stdout)
                    self.assertNotIn('A member drains once at the top of a wake', process.stdout)


if __name__ == '__main__':
    unittest.main()
