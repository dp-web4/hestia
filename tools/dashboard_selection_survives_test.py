#!/usr/bin/env python3
"""An agent selection survives the poll unless the agent is GONE (dp, 2026-09-25).

dp: "chain display does not seem to be filtered by agent when a specific agent is selected —
it shows all regardless of selection". renderOrchBar runs on every tick, BEFORE renderFeed, and
dropped `selectedOrch` whenever the selected agent was not `connected`. `connected` means
active in the window OR a detected running process, and a seat that runs as mesh wakes is
usually neither. So a selection lasted one poll, and the witness chain rendered "All".

This pins the predicate by name and EXECUTES it (node) on the case that failed live: an
agent that is present but not connected. It also shows the old predicate would have dropped
that selection, so the test fails on the defect and not merely on its spelling.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

ui = Path('core/src/server/dashboard/index.html').read_text(encoding='utf-8')
failures = []

def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' -- {detail}' if detail and not ok else ''))
    if not ok:
        failures.append(name)

check('the tick clears a selection only through selectionStillOffered',
      'if (selectedOrch && !selectionStillOffered(data, selectedOrch)) selectedOrch = null;' in ui)
check('no selection is cleared on connectivity or engagement',
      not re.search(r'selectedOrch\s*&&\s*!orchs\.some\(o\s*=>\s*o\.(connected|engaged)', ui))

m = re.search(r'function selectionStillOffered\(data, id\) \{.*?\n  \}\n', ui, re.S)
check('selectionStillOffered is defined', m is not None)

node = shutil.which('node')
check('node is available to execute the predicate', node is not None)
if m and node:
    fixtures = {
        'quiet': {'orchestrators': [{'id': 'kimi-code', 'connected': False}]},
        'live': {'orchestrators': [{'id': 'kimi-code', 'connected': True}]},
        'grant_only': {'orchestrators': [], 'instance_grants': [{'plugin_id': 'codex'}]},
        'gone': {'orchestrators': [{'id': 'claude-code', 'connected': True}]},
    }
    js = m.group(0) + (
        "const f = " + json.dumps(fixtures) + ";\n"
        "const old = (d, id) => (d.orchestrators || []).some(o => o.connected && o.id === id);\n"
        "console.log(JSON.stringify({\n"
        "  quiet: selectionStillOffered(f.quiet, 'kimi-code'),\n"
        "  live: selectionStillOffered(f.live, 'kimi-code'),\n"
        "  grant_only: selectionStillOffered(f.grant_only, 'codex'),\n"
        "  gone: selectionStillOffered(f.gone, 'kimi-code'),\n"
        "  old_quiet: old(f.quiet, 'kimi-code'),\n"
        "}));\n")
    r = subprocess.run([node, '-e', js], capture_output=True, text=True)
    check('predicate executes', r.returncode == 0, r.stderr.strip()[:300])
    if r.returncode == 0:
        got = json.loads(r.stdout)
        check('a present-but-not-connected agent stays selected', got['quiet'] is True)
        check('a connected agent stays selected', got['live'] is True)
        check('a member offered only as a grant holder stays selected', got['grant_only'] is True)
        check('an agent no bar offers is dropped', got['gone'] is False)
        check('the OLD predicate dropped the quiet agent (the live defect)', got['old_quiet'] is False)

if failures:
    raise SystemExit('dashboard selection contract failed: ' + ', '.join(failures))
print('dashboard selection contract: PASS')
