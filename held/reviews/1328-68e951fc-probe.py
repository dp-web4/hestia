import hashlib, pathlib, re, subprocess, sys, types, json
REPO = str(pathlib.Path(sys.argv[sys.argv.index('--repo') + 1]).resolve()) if '--repo' in sys.argv else str(pathlib.Path(__file__).resolve().parents[2])
DIGEST = '68e951fcab5a4ffa827e918a44cb56743ee8464079a2951b17a9a1edad2610d7'
def git(spec):
    return subprocess.check_output(['git', 'show', spec], cwd=REPO).decode()
patch = git('ba51dc02:held/' + DIGEST + '.patch')
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
root = REPO + '/scratchpad/codex-review-25967-fixtures'
battery = battery.replace('os.path.expanduser("~/.cache/hestia-shell-scope-battery")', repr(root))
B = module('review_battery', battery, REPO + '/' + bpath)
fx = B.Fixture()
if '--battery' in sys.argv:
    B.run(fx)
    print('Battery passes', B.PASSES, 'fails', B.FAILS)
scopes = ['granted', 'path:' + fx.out]
for tail in [
    'wget -q -U -O- http://h/fresh.txt',
    'wget -q --user-agent --spider http://h/fresh.txt',
    'wget -qO- http://h/fresh.txt',
    'curl -sSO http://h/fresh.txt',
    'curl -sS http://h/fresh.txt',
]:
    cmd = 'cd ' + fx.out + ' && ' + tail
    print(json.dumps({'command':tail, 'main':M.command_scope_reach(cmd, scopes, fx.ws, fx.cwd, home_markers=(fx.marker,)), 'patch':fx.reach(cmd, scopes=scopes)}))
if '--real' in sys.argv:
    import http.server, threading
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b'review marker\n')
        def log_message(self, *args): pass
    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = 'http://127.0.0.1:' + str(server.server_port) + '/fresh.txt'
    for flags in [['-q', '-U', '-O-'], ['-q', '--user-agent', '--spider']]:
        target = pathlib.Path(fx.out) / 'fresh.txt'
        p = subprocess.run(['wget', *flags, url], cwd=fx.out, capture_output=True, timeout=10)
        print('REAL', flags, 'rc', p.returncode, 'wrote', target.exists(), 'bytes', target.read_bytes() if target.exists() else None)
        if target.exists(): target.unlink()
    server.shutdown(); server.server_close()
