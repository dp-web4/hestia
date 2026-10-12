"""Offline regression for recursive path grants on repository-named MCP calls.

Run with --held to compile the digest-pinned candidate IN MEMORY. The production
gate files are never written, imported into a live gate, installed or published.
Default tests the unmodified source and must fail the three positive regressions.
--core-suite additionally runs the existing offline core suite against that module.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import runpy
import sys
import tempfile
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "plugins/_shared/hestia_gate_core.py"
HELD = ROOT / "held/lineage/9b236b54a92757e3ee3d36a3a08fe8f5f4a3aefa8bd58851852fdf54268b8fd8.patch"


def candidate(text):
    raw = HELD.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == HELD.stem, "held patch digest changed"
    lines = raw.decode().splitlines(keepends=True)
    assert lines[:3] == [
        "diff --git a/plugins/_shared/hestia_gate_core.py b/plugins/_shared/hestia_gate_core.py\n",
        "--- a/plugins/_shared/hestia_gate_core.py\n",
        "+++ b/plugins/_shared/hestia_gate_core.py\n",
    ]
    old = text.splitlines(keepends=True)
    result, at, i = [], 0, 3
    while i < len(lines):
        match = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@\n", lines[i])
        assert match, lines[i]
        start, count = int(match[1]) - 1, int(match[2] or 1)
        result.extend(old[at:start])
        at = start
        consumed, emitted = 0, 0
        i += 1
        while i < len(lines) and not lines[i].startswith("@@"):
            line = lines[i]
            if line[0] in " -":
                assert old[at] == line[1:], "patch preimage differs"
                consumed += 1
                at += 1
            if line[0] in " +":
                result.append(line[1:])
                emitted += 1
            assert line[0] in " +-"
            i += 1
        assert consumed == count and emitted == int(match[4] or 1)
    result.extend(old[at:])
    return "".join(result)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--held", action="store_true")
    ap.add_argument("--core-suite", action="store_true")
    args = ap.parse_args()
    source = SOURCE.read_text()
    g = types.ModuleType("hestia_gate_core")
    g.__file__ = str(SOURCE)
    sys.modules[g.__name__] = g
    exec(compile(candidate(source) if args.held else source, str(SOURCE), "exec"), g.__dict__)
    failed, total = [], 0

    def check(label, observed, expected):
        nonlocal total
        total += 1
        okay = observed == expected
        print(f"{'PASS' if okay else 'FAIL'} {label}: {observed!r}")
        if not okay:
            failed.append(label)

    with tempfile.TemporaryDirectory(prefix="repo-scope-regression-") as tmp:
        ws = Path(tmp) / "workspace"
        repo = ws / "sample"
        (repo / ".git").mkdir(parents=True)
        (ws / "plain-directory").mkdir()
        (ws / "worktree").mkdir()
        (ws / "worktree/.git").write_text("gitdir: synthetic-marker-only\n")
        outside = Path(tmp) / "outside"
        (outside / ".git").mkdir(parents=True)
        (ws / "escaped").symlink_to(outside, target_is_directory=True)
        (ws / "alias").symlink_to(repo, target_is_directory=True)
        (ws / "blocked-private/.git").mkdir(parents=True)
        profile = g.HarnessProfile(member_id="codex", identity_path="unused",
                                   launch_cwd_env="TEST_SCOPE_LAUNCH")

        def verdict(scopes, name="sample", paths=None):
            pol = g.AgentPolicy(member_id="codex", scope=tuple(scopes), source="synthetic-vault")
            event = g.NormalizedEvent(tool="mcp__fixture__github", repos=[name], paths=paths or [])
            return g.evaluate(event, profile, str(ws), pol).decision

        # Avoid importing the review process's own launch grant or environment policy.
        with patch.dict(os.environ, {"TEST_SCOPE_LAUNCH": str(Path(tmp) / "elsewhere"),
                                     "HESTIA_FORBIDDEN_EXTRA": "blocked-private"}):
            broad = [f"path:{ws}/**"]
            check("local file already covered by explicit recursive grant",
                  g._within_path_grant(str(repo / "README.md"), broad, str(ws)), True)
            check("recursive workspace permits repository event", verdict(broad), "allow")
            check("recursive repo path permits repository event",
                  verdict([f"path:{repo}/**"]), "allow")
            check("explicit repository grant preserved", verdict(["sample"]), "allow")
            check("no grants", verdict([]), "deny")
            check("exact workspace does not become recursive", verdict([f"path:{ws}"]), "deny")
            check("exact repo does not grant repository contents", verdict([f"path:{repo}"]), "deny")
            check("file grant does not front for repo", verdict([f"path:{repo}/README.md"]), "deny")
            check("recursive child does not front for repo", verdict([f"path:{repo}/src/**"]), "deny")
            check("sibling prefix is not containment", verdict([f"path:{ws}-other/**"]), "deny")
            check("temp-directory ambient access is not repo authority", verdict([]), "deny")
            check("missing checkout", verdict(broad, "missing"), "deny")
            check("ordinary directory is not a checkout", verdict(broad, "plain-directory"), "deny")
            check("checkout with git-file marker", verdict(broad, "worktree"), "allow")
            check("symlink escape", verdict(broad, "escaped"), "deny")
            check("internal alias cannot rename repository identity", verdict(broad, "alias"), "deny")
            check("explicit forbidden name dominates reach", verdict(broad, "blocked-private"), "deny")
            check("secret relative content remains forbidden", verdict(broad, paths=[".env"]), "deny")
            for name in ["..", ".", "../outside", "/outside", "sample/child", "sample\\child", "sample%2fchild", ""]:
                check(f"malformed name {name!r}", verdict(broad, name), "deny")
            expired = g.resolve_agent_policy(profile, vault_reader=lambda _: {
                "in_scope": broad, "generation": 1, "snapshot_expires_at": 1,
                "expires_at": 1,
            })
            check("expired snapshot has no reach", expired.scope, ())
            event = g.NormalizedEvent(tool="mcp__fixture__github", repos=["sample", "missing"])
            policy = g.AgentPolicy(member_id="codex", scope=tuple(broad))
            check("every repository in event must be covered",
                  g.evaluate(event, profile, str(ws), policy).decision, "deny")
    print(f"{total - len(failed)}/{total} passed; mode={'held in memory' if args.held else 'main'}")
    if args.core_suite:
        # The existing suite imports this same module from sys.modules.
        # Relocate ONLY its hardcoded fixture cache into the writable checkout;
        # do not change HOME or grant the test workspace unconditional /tmp reach.
        scratch = ROOT / "scratchpad"
        scratch.mkdir(exist_ok=True)
        expand = os.path.expanduser
        with tempfile.TemporaryDirectory(prefix="repo-core-suite-", dir=scratch) as fixture:
            def relocated(path):
                return fixture if path == "~/.cache/hestia-gate-core-tests" else expand(path)
            with patch("os.path.expanduser", relocated):
                runpy.run_path(str(ROOT / "plugins/_shared/test_gate_core.py"), run_name="__main__")
    return bool(failed)


if __name__ == "__main__":
    sys.exit(main())
