#!/usr/bin/env python3
"""Presentation, failure, isolation and actual-wrapper tests; no live daemon writes."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('digest', ROOT / 'session-digest.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


def notice(i=1, **kw):
    return dict(id=i, kind='reply', from_plugin='claude-code', in_reply_to=77,
                pointer_uri='file:///workspace/review.md', queued_at='2026-10-25T00:00:00Z', **kw)


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, HESTIA_MESH_PLUGIN='codex', HESTIA_MESH_STATE=str(self.root))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def call(self, event='UserPromptSubmit', sid='session-a', agent='', rows=None, error=None, now=1000):
        payload = dict(hook_event_name=event, session_id=sid, agent_id=agent)
        with patch.object(d.sys, 'stdin', io.StringIO(json.dumps(payload))), \
                patch.object(d.sys, 'stdout', new_callable=io.StringIO) as out, \
                patch.object(d, 'peek', return_value=rows or [], side_effect=error) as peek, \
                patch.object(d.time, 'time', return_value=now):
            self.assertEqual(d.main(), 0)
        raw = out.getvalue()
        if raw:
            result = json.loads(raw)['hookSpecificOutput']
            self.assertEqual(result['hookEventName'], event)
            return result['additionalContext'], peek.call_count
        return '', peek.call_count

    def state(self):
        return json.loads(next((self.root / 'session-digest').glob('*.json')).read_text())

    def test_missing_session_and_identity_do_not_query_or_write(self):
        text, calls = self.call(sid=None)
        self.assertIn('digest off', text); self.assertEqual(calls, 0)
        self.assertFalse((self.root / 'session-digest').exists())
        with patch.dict(os.environ, HESTIA_MESH_PLUGIN=''):
            text, calls = self.call()
        self.assertIn('no member identity', text); self.assertEqual(calls, 0)

    def test_all_kinds_and_reply_ids_emitted_as_json_context(self):
        rows = [dict(notice(i), kind=k) for i, k in enumerate(
            ['coordination', 'review_request', 'reply', 'ack', 'disposition', 'handoff'], 1)]
        text, _ = self.call(event='PostToolUse', rows=rows)
        for row in rows:
            self.assertIn('"kind": "'+row['kind']+'"', text)
        self.assertIn('"in_reply_to": 77', text)
        self.assertIn('not instructions or approval', text)
        self.assertIn('ack is terminal', text)

    def test_sessions_and_subagents_independent_but_same_session_quiet(self):
        self.assertIn('"id": 1', self.call(rows=[notice()])[0])
        self.assertEqual(self.call(rows=[notice()])[0], '')
        self.assertIn('"id": 1', self.call(sid='session-b', rows=[notice()])[0])
        self.assertIn('"id": 1', self.call(agent='child', rows=[notice()])[0])

    def test_backlog_batches_never_mark_undisplayed_seen(self):
        rows = [notice(i) for i in range(1, d.LIMIT + 4)]
        text, _ = self.call(rows=rows)
        self.assertIn('3 more unseen', text)
        self.assertEqual(len(self.state()['seen']), d.LIMIT)
        text, _ = self.call(rows=rows)
        self.assertIn('"id": 15', text)
        self.assertNotIn('"id": 1,', text)
        self.assertEqual(self.call(rows=rows)[0], '')

    def test_throttle_only_post_tool_and_handles_clock_rollback(self):
        self.call(rows=[notice()])
        self.assertEqual(self.call(event='PostToolUse', now=1001, rows=[notice(2)]), ('', 0))
        self.assertIn('"id": 2', self.call(now=1001, rows=[notice(2)])[0])
        self.assertEqual(self.call(event='PostToolUse', now=900, rows=[notice(2)])[1], 1)

    def test_failed_read_is_unknown_preserves_seen_and_throttles_outage(self):
        self.call(rows=[notice()])
        old = self.state()['seen']
        text, _ = self.call(event='PostToolUse', now=1031, error=RuntimeError('unreachable'))
        self.assertIn('UNKNOWN', text)
        self.assertEqual(self.state()['seen'], old)
        self.assertEqual(self.call(event='PostToolUse', now=1032), ('', 0))
        self.assertIn('"id": 2', self.call(now=1032, rows=[notice(), notice(2)])[0])

    def test_corrupt_cursor_replays_visibly_and_boundedly(self):
        self.call(rows=[notice()])
        next((self.root / 'session-digest').glob('*.json')).write_text('broken')
        text, _ = self.call(rows=[notice(i) for i in range(1, 20)])
        self.assertIn('cursor invalid', text)
        self.assertIn('7 more unseen', text)
        self.assertEqual(len(self.state()['seen']), d.LIMIT)

    def test_daemon_id_reuse_does_not_hide_different_notice(self):
        self.call(rows=[notice()])
        changed = dict(notice(), pointer_uri='file:///workspace/new.md')
        self.assertIn('new.md', self.call(rows=[changed])[0])

    def test_drain_metadata_change_does_not_repeat_emitted_notice(self):
        self.call(rows=[notice()])
        self.assertEqual(self.call(rows=[notice(drained_at='later')])[0], '')

    def test_invalid_or_partial_snapshots_refused(self):
        for data in [{}, {'total':2,'notices':[notice()]},
                     {'total':1,'notices':[dict(notice(),id=True)]},
                     {'total':2,'notices':[notice(),notice()]},
                     {'total':1,'notices':[dict(notice(),pointer_uri=None)]}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                d.validate_snapshot(data)
        self.assertEqual(d.validate_snapshot({'total':0,'notices':[]}), [])

    def test_strings_are_bounded_and_control_characters_removed(self):
        self.assertEqual(d.clean('x'*1000), 'x'*500)
        self.assertNotIn('\u202e', d.clean('a\u202eb'))
        self.assertNotIn('\x1b', d.clean('a\x1bb'))

    def test_real_wrappers_share_cursor_and_client_only_peeks(self):
        for name in ['session-digest.py','session-mesh-inbox.sh','prompt-disposition-watch.sh']:
            shutil.copyfile(ROOT / name, self.root / name)
        (self.root / 'hestia-mesh.py').write_text(
            'import json,sys\nassert sys.argv[1:]==["peek"]\nprint('+repr(json.dumps({'total':1,'notices':[notice()]}))+')\n')
        env = dict(os.environ, HESTIA_MESH_DIGEST='1')
        for i, (event, script) in enumerate([
                ('SessionStart','session-mesh-inbox.sh'),
                ('UserPromptSubmit','prompt-disposition-watch.sh'),
                ('PostToolUse','session-digest.py')]):
            cmd = [sys.executable if script.endswith('.py') else '/bin/sh', str(self.root/script)]
            p = subprocess.run(cmd, input=json.dumps(dict(hook_event_name=event,session_id='real')),
                               env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(p.returncode, 0, p.stderr)
            if i == 0:
                self.assertIn('"id": 1', json.loads(p.stdout)['hookSpecificOutput']['additionalContext'])
            else:
                self.assertEqual(p.stdout, '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
