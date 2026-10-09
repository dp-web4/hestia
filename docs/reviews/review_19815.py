import hashlib, importlib.abc, importlib.util, json, os, re, subprocess, sys, types, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEAD = 'b1efbdfab792e79a071091d90896411d1342b529'
PATCH = 'held/88c5095c90a5b555d313bd52f319a6f20d9cc2c0d970eb9547a1182b39d618bb.patch'
sys.dont_write_bytecode = True

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])

def blob(path):
    p = subprocess.run(['git', '-C', str(ROOT), 'show', HEAD + ':' + path], capture_output=True)
    return p.stdout if p.returncode == 0 else b''

patch = blob(PATCH)
assert hashlib.sha256(patch).hexdigest() == Path(PATCH).stem
patched = {}
for section in patch.decode().split('diff --git ')[1:]:
    lines = section.splitlines(True)
    path = lines[0].rstrip().split(' b/')[1]
    old = blob(path).decode().splitlines(True)
    out, pos, i = [], 0, 1
    while i < len(lines):
        line = lines[i]
        if not line.startswith('@@ '):
            i += 1
            continue
        match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        start, oldn, newstart, newn = [int(v) if v is not None else 1 for v in match.groups()]
        start = max(0, start - 1)
        assert start >= pos
        out.extend(old[pos:start]); pos = start
        assert len(out) == max(0, newstart - 1)
        consumed = produced = 0
        i += 1
        while i < len(lines) and not lines[i].startswith('@@ '):
            line = lines[i]
            assert line[0] in ' +-'
            if line[0] in ' -':
                assert old[pos] == line[1:], (path, pos)
                pos += 1; consumed += 1
            if line[0] in ' +':
                out.append(line[1:]); produced += 1
            i += 1
        assert (consumed, produced) == (oldn, newn), path
    out.extend(old[pos:])
    patched[path] = ''.join(out).encode()
assert len(patched) == 14
for path in ('plugins', 'hooks-gt'):
    assert git('rev-parse', HEAD + ':' + path) == git('rev-parse', '716ae2d1:' + path)
print('Patch digest, all hunk counts/context, 14-file set and base subtrees verified')

class Loader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if '.' in fullname:
            return None
        rel = 'plugins/_shared/' + fullname + '.py'
        data = patched.get(rel, blob(rel))
        if data:
            spec = importlib.util.spec_from_loader(fullname, self)
            spec.loader_state = (rel, data)
            return spec
    def create_module(self, spec):
        return None
    def exec_module(self, mod):
        rel, data = mod.__spec__.loader_state
        mod.__file__ = str(ROOT / rel)
        exec(compile(data, mod.__file__, 'exec'), mod.__dict__)
sys.meta_path.insert(0, Loader())

def run(rel, data=None):
    print('RUN', rel, flush=True)
    name = '__main__'
    mod = types.ModuleType(name)
    mod.__file__ = str(ROOT / rel)
    previous = sys.modules[name]
    sys.modules[name] = mod
    try:
        exec(compile(data or patched.get(rel, blob(rel)), mod.__file__, 'exec'), mod.__dict__)
    except SystemExit as exc:
        assert exc.code in (None, 0), (rel, exc.code)
    finally:
        sys.modules[name] = previous

if __name__ == '__main__':
    for path in git('ls-tree', '-r', '--name-only', HEAD, 'plugins').decode().splitlines():
        if path.endswith('/expects.json'):
            assert (ROOT/path).read_bytes() == blob(path), path
    run('plugins/_shared/member_install_surface_test.py')
    run('plugins/_shared/registered_surface_test.py')
    run('plugins/_shared/hestia_governance_closure_test.py')
    run('docs/reviews/restack-1247-build/probe_codex.py')
