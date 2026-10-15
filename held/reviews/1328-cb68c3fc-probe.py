"""Review reproduction; reconstructs held code in memory, never installs it."""
import hashlib, pathlib, re, subprocess, sys, types, json
REPO = str(pathlib.Path(sys.argv[sys.argv.index('--repo') + 1]).resolve()) if '--repo' in sys.argv else str(pathlib.Path(__file__).resolve().parents[2])
DIGEST = 'cb68c3fc11b06de5dffcf7620ce4683027a5ffaedb32f6ce0e3b38aed61c6ddc'
def git(spec):
    return subprocess.check_output(['git', 'show', spec], cwd=REPO).decode()
patch = git('8b242ba9:held/' + DIGEST + '.patch')
assert hashlib.sha256(patch.encode()).hexdigest() == DIGEST
rebuilt = {}
for part in patch.split('diff --git ')[1:]:
    lines = part.splitlines(keepends=True)
    path = lines[0].split()[0][2:]
    old = git('2d79644f:' + path).splitlines(keepends=True)
    result, pos, i = [], 0, 3
    while i < len(lines):
        h = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', lines[i])
        assert h, lines[i]
        start = int(h[1]) - 1
        result.extend(old[pos:start]); pos = start; i += 1
        oc = nc = 0
        while i < len(lines) and not lines[i].startswith('@@ '):
            line = lines[i]; i += 1
            if line[0] in ' -':
                assert old[pos] == line[1:], (path, pos, old[pos], line)
                pos += 1; oc += 1
            if line[0] in ' +':
                result.append(line[1:]); nc += 1
        assert oc == int(h[2] or 1) and nc == int(h[4] or 1)
    result.extend(old[pos:]); rebuilt[path] = ''.join(result)
print('Verified digest and reconstructed', len(rebuilt), 'files in memory')
# Check the generated mirror and the entire manifest pin graph without installing it.
sys.path.insert(0, REPO + '/tools')
import hooks_gt
mirror = rebuilt['hooks-gt/_shared/hestia_gate_core.py'].encode()
assert hooks_gt.strip_header(mirror) == rebuilt['plugins/_shared/hestia_gate_core.py'].encode()
assert hooks_gt.canonical_digest(mirror) == hooks_gt.header_value(mirror)
shared_manifest = json.loads(rebuilt['hooks-gt/_shared/manifest.json'])
for path, source in rebuilt.items():
    if path.endswith('/manifest.json'):
        manifest = json.loads(source)
        assert hooks_gt._version(manifest) == manifest['gt_version']
        if manifest.get('engine'):
            assert manifest['engine'] == hooks_gt._engine_pin(shared_manifest)
        for row in manifest['files']:
            target = str(pathlib.PurePosixPath(path).parent / row['path'])
            contents = rebuilt[target] if target in rebuilt else git('2d79644f:' + target)
            assert hooks_gt.canonical_digest(contents.encode()) == row['sha256']
print('Mirror, five manifest versions, file digests and engine pins: PASS')
def module(name, code, filename):
    m = types.ModuleType(name); m.__file__ = filename; sys.modules[name] = m
    exec(compile(code, filename, 'exec'), m.__dict__)
    return m
corepath = 'plugins/_shared/hestia_gate_core.py'
G = module('review_core', rebuilt[corepath], REPO + '/' + corepath)
M = module('review_main', git('2d79644f:' + corepath), REPO + '/' + corepath)
bpath = 'tools/shell_scope_reach_battery_test.py'
battery = rebuilt[bpath]
start = battery.index('_spec = '); end = battery.index('FAILS: ', start)
battery = battery[:start] + 'G = sys.modules["review_core"]\n\n' + battery[end:]
root = REPO + '/scratchpad/codex-review-26008-fixtures'
battery = battery.replace('os.path.expanduser("~/.cache/hestia-shell-scope-battery")', repr(root))
B = module('review_battery', battery, REPO + '/' + bpath)
fx = B.Fixture()
if '--battery' in sys.argv:
    B.run(fx)
    print('Battery passes', B.PASSES, 'fails', B.FAILS)
    assert not B.FAILS
scopes = ['granted', 'path:' + fx.out]
controls = [
    ('wget --spider --no-spider -q http://h/fresh.txt', False),
    ('http --download -o ' + fx.cwd + '/named http://h/fresh.txt', False),
    ('curl -sS http://h/fresh.txt', True),
    ('curl -sS -o ' + fx.cwd + '/named http://h/fresh.txt', True),
    ('http -b http://h/fresh.txt', True),
    ('curl --remote-nam -sS http://h/fresh.txt', False),
    ('curl --remote-name-a -sS http://h/fresh.txt', False),
]
for tail, expected in controls:
    cmd = 'cd ' + fx.out + ' && ' + tail
    main = M.command_scope_reach(cmd, scopes, fx.ws, fx.cwd, home_markers=(fx.marker,))
    patched = fx.reach(cmd, scopes=scopes)
    assert main[0] is False and patched[0] is False, (tail, main, patched)
print('Prior refusals and withdrawn URL controls: PASS')

import shlex
# O is exactly granted; its children are not. For the template tests only,
# grant the literal template O/out#1, not the actual output paths O/out1 and O/out2.
write_cases = [
    ['-q', '-sS', '--write-out', '%output{fresh.txt}marker'],
    ['-q', '-sS', '-w', '%output{fresh.txt}marker'],
    ['-q', '-sS', '-w%output{fresh.txt}marker'],
]
template_cases = [
    ['-q', '-sS', '-o', 'out#1'],
    ['-q', '-sS', '--output', 'out#1'],
]
for flags in write_cases + template_cases:
    is_template = flags in template_cases
    ss = scopes + (['path:' + fx.out + '/out#1'] if is_template else [])
    url = 'http://h/[1-2]' if is_template else 'http://h/fresh.txt'
    cmd = 'cd ' + shlex.quote(fx.out) + ' && ' + shlex.join(['curl', *flags, url])
    main = M.command_scope_reach(cmd, ss, fx.ws, fx.cwd, home_markers=(fx.marker,))
    patched = fx.reach(cmd, scopes=ss)
    assert main[0] is False and patched[0] is False, (flags, main, patched)
    for name in (['out1', 'out2'] if is_template else ['fresh.txt']):
        assert fx.reach('touch ' + shlex.quote(fx.out + '/' + name), scopes=ss)[0] is False
    print('WITHDRAWN main=refuse held=refuse actual-output-controls=refuse:', flags)
if '--real' in sys.argv:
    import http.server, threading
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b'review marker\n')
        def log_message(self, *args): pass
    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    print(subprocess.check_output(['curl', '--version'], text=True).splitlines()[0])
    try:
        for flags in write_cases + template_cases:
            is_template = flags in template_cases
            url = 'http://127.0.0.1:' + str(server.server_port) + ('/[1-2]' if is_template else '/fresh.txt')
            names = ['out1', 'out2'] if is_template else ['fresh.txt']
            targets = [pathlib.Path(fx.out) / name for name in names]
            assert all(not t.exists() for t in targets)
            result = subprocess.run(['curl', *flags, url], cwd=fx.out, capture_output=True, timeout=10)
            assert result.returncode == 0, result.stderr
            expected = b'review marker\n' if is_template else b'marker'
            assert all(t.read_bytes() == expected for t in targets)
            assert not (pathlib.Path(fx.out) / 'out#1').exists()
            print('REAL', flags, 'exit=0 wrote', names, 'contents verified')
            for t in targets: t.unlink()
    finally:
        server.shutdown(); server.server_close()

if '--main-battery' in sys.argv:
    B.G = M; B.PASSES = 0; B.FAILS = []
    B.run(B.Fixture())
    assert len(B.FAILS) == 16, B.FAILS
    assert all(n.startswith('allow-outside-cwd:1314-') or n in {
        'deny-outside-cwd:1314-control-file-url',
        'deny-outside-cwd:1314-control-file-url-localhost',
        'deny-outside-cwd:1314-control-file-url-option',
        'deny-outside-cwd:1314-control-file-url-query',
        'deny-outside-cwd:1314-control-file-url-percent'} for n in B.FAILS), B.FAILS
    print('Main comparison:', B.PASSES, 'pass;', len(B.FAILS), 'expected differences')
    B.G = G
if '--contract-stage' in sys.argv:
    import tempfile
    stage = pathlib.Path(tempfile.mkdtemp(prefix='codex-1328-cb68-contract-'))
    for name, path in [('core.py', corepath), ('contract.py', 'tools/one_gate_decide_contract_test.py')]:
        (stage / name).write_text(rebuilt[path])
    print('Contract staging:', stage)
