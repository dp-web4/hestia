"""#1281 split 7d51: does the invalid-identity placeholder hide the raw repo string from gate 1a?"""
import sys, types
from pathlib import Path
# argv[1]: a checkout of codex/recursive-repo-scope at 70cfe0d0 (holds the candidate builder)
ROOT = Path(sys.argv[1])
sys.path.insert(0, str(ROOT / "docs/reviews")); sys.path.insert(0, str(ROOT / "plugins/_shared"))
from recursive_repo_scope_candidate import proposed_sources
ch = proposed_sources()
def load(name, rel, src):
    m = types.ModuleType(name); m.__file__ = str(ROOT / rel); sys.modules[name] = m
    exec(compile(src, str(ROOT / rel), "exec"), m.__dict__); return m
for i, label in ((0, "main"), (1, "cand")):
    c = load("hestia_gate_core", "plugins/_shared/hestia_gate_core.py", ch["plugins/_shared/hestia_gate_core.py"][i])
    a = load("hestia_single_gate", "plugins/_shared/hestia_single_gate.py", ch["plugins/_shared/hestia_single_gate.py"][i])
    tok = c.FORBIDDEN_DEFAULT[-1]          # a default innate token, not spelled here
    prof = c.HarnessProfile(member_id="codex", identity_path="unused")
    for scope in (("*",), ("hestia",)):
        pol = c.AgentPolicy(member_id="codex", scope=scope, source="synthetic-vault")
        for ti in ({"repo": tok}, {"repository": "https://github.com/o/" + tok},
                   {"repo": "o/" + tok}, {"owner": "o", "repo": tok},
                   {"repo": "o/" + tok, "repository": "o/hestia"}):
            ev = a.normalized_event(a.GateEvent(tool="mcp__github__get_file_contents", tool_input=ti, cwd="/tmp"))
            v = c.evaluate(ev, prof, "/tmp/nows", pol)
            shown = {k: str(x).replace(tok, "<TOK>") for k, x in ti.items()}
            print(label, scope[0], shown, [r.replace(tok, "<TOK>") for r in ev.repos], v.decision, getattr(v, "rule", ""))
