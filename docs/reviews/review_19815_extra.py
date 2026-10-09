from review_19815 import *
import tempfile, time
from unittest.mock import patch as mock_patch
import hestia_governance_closure as closure
import hestia_single_gate as gate

hg = types.ModuleType('review_hooks_gt')
hg.__file__ = str(ROOT / 'tools/hooks_gt.py')
exec(compile(blob('tools/hooks_gt.py'), hg.__file__, 'exec'), hg.__dict__)
def data(path):
    return patched.get(path, blob(path))
manifests = {}
rows = 0
for unit in ('_shared', 'claude-code', 'codex', 'gemini', 'kimi'):
    m = json.loads(data(f'hooks-gt/{unit}/manifest.json'))
    manifests[unit] = m
    assert hg._version(m) == m['gt_version']
    for row in m['files']:
        content = data(f'hooks-gt/{unit}/' + row['path'])
        assert hg.canonical_digest(content) == row['sha256']
        assert hg.strip_header(content) == data(row['source'])
        if not row['path'].endswith('.json'):
            assert hg.header_value(content) == row['sha256']
        rows += 1
for unit, m in manifests.items():
    if unit == '_shared':
        continue
    assert m['engine']['gt_version'] == manifests['_shared']['gt_version']
    assert m['engine']['files'] == [{k: row[k] for k in ('path', 'sha256')} for row in manifests['_shared']['files']]
print('Verified 5 manifest versions,', rows, 'published rows, all source parity and 4 engine pins')

with tempfile.TemporaryDirectory(prefix='review19815-') as home:
    legacy = str(Path(home) / 'legacy' / 'entry')
    Path(legacy).mkdir(parents=True)
    entry = legacy + '/before_tool.py'
    Path(entry).touch()
    reg = gate.RegisteredSurface(entry, (legacy,), (entry,), (entry,))
    ordinary = home + '/plugins/_shared/ordinary.txt'
    commands = [
        f'touch {ordinary} {entry}',
        f'touch {ordinary} {legacy}/before_*',
        f'cd {legacy} && touch before_tool.py',
        f'touch {ordinary} {entry} "$TARGET"',
    ]
    for command in commands:
        event = gate.GateEvent('Bash', {'command': command}, cwd='/')
        inv = gate._Invocation(event, gate.GateProfile(member_id='gemini', identity_path=None),
                               'enforce', time.monotonic()+10, None, registered=reg, role='member')
        with mock_patch.object(gate.mechanism, 'claim_self_write', return_value=('approved','stub',None,None)) as claim:
            gate._governance_closure(inv)
        assert claim.call_count == 1
        kw = claim.call_args.kwargs
        assert gate.REGISTERED_ENTRY_MARKER in kw['resolved_targets'], kw
        assert kw['resolved_targets_complete'] == ('$TARGET' not in command), kw
    print('4 independent claim-boundary probes passed: mixed declared/registered, wildcard, cd, unresolved')
    event = gate.GateEvent('Bash', {'command': f'touch {ordinary} {entry}'}, cwd='/')
    assert gate._closure_write_set(event, reg.closure()) == ([ordinary, entry], True)
    glob = legacy + '/before_*'
    event = gate.GateEvent('Bash', {'command': f'touch {glob}'}, cwd='/')
    assert gate._closure_write_set(event, reg.closure()) == ([glob], True)
    with mock_patch.dict(os.environ, {'HOME': home}):
        v = closure.write_verdicts('Write', {'file_path': 'before_tool.py'}, cwd='~/legacy/entry', closure=reg.closure())[0]
        assert v.landing == entry
        assert isinstance(v.resolved, tuple)
    print('3 independent ordering and home-relative-cwd probes passed')

    original = gate._reaches_registered_entry
    # Reintroduce the merge mistake: the consumer receives the tuple instead of landing.
    source = patched['plugins/_shared/hestia_single_gate.py'].decode()
    assert source.count('getattr(rv, "landing", None)') == 1
    mutant = types.ModuleType('review_mutant')
    mutant.__file__ = str(ROOT / 'plugins/_shared/hestia_single_gate.py')
    sys.modules[mutant.__name__] = mutant
    exec(compile(source.replace('getattr(rv, "landing", None)', 'getattr(rv, "resolved", None)'), mutant.__file__, 'exec'), mutant.__dict__)
    event = gate.GateEvent('Write', {'file_path': entry}, cwd='/')
    inv = types.SimpleNamespace(event=event, registered=reg)
    assert gate._closure_verdict(inv).marker == gate.REGISTERED_ENTRY_MARKER
    assert mutant._closure_verdict(inv).marker != gate.REGISTERED_ENTRY_MARKER
    print('Mutation control detects registered-entry tuple/landing regression')
