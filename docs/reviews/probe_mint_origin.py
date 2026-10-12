"""Mint probe against held c0219817: can in-scope writes alone add remote reach?"""
import os, sys, tempfile
from pathlib import Path
from unittest.mock import patch
sys.argv = [sys.argv[0]]
import recursive_repo_origin_probe as P
from recursive_repo_scope_candidate import proposed_sources


def run(held):
    ch = proposed_sources()
    sys.path.insert(0, str(P.ROOT / "plugins/_shared"))
    g = P.load_module("hestia_gate_core", P.ROOT / "plugins/_shared/hestia_gate_core.py", ch["plugins/_shared/hestia_gate_core.py"][held])
    a = P.load_module("hestia_single_gate", P.ROOT / "plugins/_shared/hestia_single_gate.py", ch["plugins/_shared/hestia_single_gate.py"][held])
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "workspace"
        ws.mkdir()
        prof = g.HarnessProfile(member_id="codex", identity_path="unused", launch_cwd_env="TEST_SCOPE_LAUNCH")

        def v(scopes, ident):
            pol = g.AgentPolicy(member_id="codex", scope=tuple(scopes), source="synthetic-vault")
            ev = a.normalized_event(a.GateEvent(tool="mcp__fixture__github", tool_input={"repository_full_name": ident}))
            return g.evaluate(ev, prof, str(ws), pol).decision

        broad = [f"path:{ws}/**"]
        out = []
        with patch.dict(os.environ, {"TEST_SCOPE_LAUNCH": str(Path(tmp) / "elsewhere")}):
            # 1-2: mint a checkout with plain file writes inside path:ws/** (no git binary)
            out.append(v(broad, "victim/minted"))
            d = ws / "minted" / ".git"
            (d / "objects").mkdir(parents=True)
            (d / "refs").mkdir()
            (d / "HEAD").write_text("ref: refs/heads/main\n")
            (d / "config").write_text('[core]\n\trepositoryformatversion = 0\n\tbare = false\n'
                                      '[remote "origin"]\n\turl = https://github.com/victim/minted.git\n')
            out.append(v(broad, "victim/minted"))
            # 3-4: retarget an explicitly granted checkout's origin to a foreign owner
            r = ws / "sample"
            r.mkdir()
            P.git(r, "init", "-q")
            P.git(r, "config", "remote.origin.url", "https://github.com/example/sample.git")
            out.append(v(["sample"], "victim/sample"))
            cfg = r / ".git" / "config"
            cfg.write_text(cfg.read_text().replace("example/sample", "victim/sample"))
            out.append(v(["sample"], "victim/sample"))
    return tuple(out)


print("baseline:     ", run(0))
print("held c0219817:", run(1))
