"""Apply the held patch to main's bytes in memory; compare with the builder's tested source; extra egress rows."""
import sys, re, types, hashlib
from pathlib import Path
ROOT = Path(sys.argv[1]); HELD = next((ROOT/"held").glob("c7ed5f75*.patch"))
text = HELD.read_text(); assert hashlib.sha256(HELD.read_bytes()).hexdigest() == HELD.stem
files = {}
for chunk in re.split(r"(?m)^diff --git ", text)[1:]:
    path = re.search(r"(?m)^\+\+\+ b/(.+)$", chunk)[1]
    old = (ROOT/path).read_text().splitlines(keepends=True); out = []; i = 0
    for h in re.finditer(r"(?ms)^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@.*?\n(.*?)(?=^@@ |\Z)", chunk):
        start = int(h[1]) - 1; out += old[i:start]; i = start
        for ln in h[2].splitlines(keepends=True):
            tag, body = ln[0], ln[1:]
            if tag in " -": assert old[i] == body, (path, i); i += 1
            if tag in " +": out.append(body)
    files[path] = "".join(out + old[i:])
sys.path.insert(0, str(ROOT/"docs/reviews")); sys.path.insert(0, str(ROOT/"plugins/_shared"))
from recursive_repo_scope_candidate import proposed_sources
ch = proposed_sources()
for p, s in files.items(): print("applied==tested", p, s == ch[p][1])
def load(name, rel, src):
    m = types.ModuleType(name); m.__file__ = str(ROOT/rel); sys.modules[name] = m
    exec(compile(src, str(ROOT/rel), "exec"), m.__dict__); return m
for label, srcs in (("main", {p: ch[p][0] for p in files}), ("held", files)):
    c = load("hestia_gate_core", "plugins/_shared/hestia_gate_core.py", srcs["plugins/_shared/hestia_gate_core.py"])
    a = load("hestia_single_gate", "plugins/_shared/hestia_single_gate.py", srcs["plugins/_shared/hestia_single_gate.py"])
    tok = c.FORBIDDEN_DEFAULT[-1]; prof = c.HarnessProfile(member_id="codex", identity_path="unused")
    for scope in ("*", "hestia"):
        pol = c.AgentPolicy(member_id="codex", scope=(scope,), source="synthetic-vault")
        for ti in ({"repo": [tok]}, {"owner": tok, "repo": "hestia"}, {"owner": {"x": tok}, "repo": "hestia"},
                   {"owner": tok}, {"repo": "hestia", "repository": None, "repo_full_name": tok},
                   {"repo": " o/" + tok + " "}, {"repo": "o/hestia\n" + tok}, {"repository": "", "repo": tok},
                   {"repo": "o/hestia"}, {"owner": "o", "repo": "HESTIA"}):
            ev = a.normalized_event(a.GateEvent(tool="mcp__github__get_file_contents", tool_input=ti, cwd="/tmp"))
            v = c.evaluate(ev, prof, "/tmp/nows", pol)
            s = lambda x: str(x).replace(tok, "<TOK>")
            print(label, scope, s(ti), s(ev.repos), v.decision, getattr(v, "rule", ""))
