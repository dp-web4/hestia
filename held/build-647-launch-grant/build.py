#!/usr/bin/env python3
"""Build the held patch for hestia #647: an explicit external launch dir is in scope.

argv: <hestia worktree at the base> <out dir>
"""
import difflib
import hashlib
import pathlib
import re
import subprocess
import sys

WT, OUT = (pathlib.Path(a).resolve() for a in sys.argv[1:3])
sys.dont_write_bytecode = True
CORE = "plugins/_shared/hestia_gate_core.py"
TEST = "plugins/_shared/test_gate_core.py"
GT = "hooks-gt/_shared/hestia_gate_core.py"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new):
    assert text.count(old) == 1, ("anchor not exactly once", old[:80], text.count(old))
    return text.replace(old, new)


def patch_core(src):
    return once(src, r'''def launch_cwd_repo(profile: HarnessProfile, workspace: str) -> list:
    """The repo the member is launched in is always in scope (dp 2026-07-21: 'whatever cwd we
    launch it in') — a per-launch dynamic grant on top of the static allowlist, so a
    task-specific launch dir is reachable for that session without widening the standing
    grant. This is the precedent `hestia_request_scope` generalises."""
    env = os.environ.get(profile.launch_cwd_env) if profile.launch_cwd_env else None
    cwd = (env or os.getcwd()).replace("\\", "/")
    if workspace in cwd:
        rest = cwd.split(workspace, 1)[1].lstrip("/")
        seg = rest.split("/", 1)[0] if rest else ""
        return [seg] if seg else []
    return []
''', r'''def _launch_repo_segment(candidate: str, workspace: str) -> list:
    candidate = os.path.realpath(os.path.expanduser(candidate)).replace("\\", "/").rstrip("/") or "/"
    ws = os.path.realpath(os.path.expanduser(workspace)).replace("\\", "/").rstrip("/") or "/"
    prefix = ws if ws == "/" else ws + "/"
    if candidate.startswith(prefix):
        rest = candidate[len(prefix):].lstrip("/")
        return [rest.split("/", 1)[0]] if rest else []
    return []


def launch_cwd_repo(profile: HarnessProfile, workspace: str) -> list:
    """The launch directory is in scope, as a per-launch dynamic grant.

    Inside the workspace that is the first repo segment, as before. An ABSOLUTE existing directory
    supplied through the profile's declared launch variable may instead be outside the workspace:
    it gets a recursive `path:` grant for that directory alone. A relative path, root, a missing or
    non-directory target, a workspace ancestor, or an external cwd with no declaration grants nothing.
    """
    env = os.environ.get(profile.launch_cwd_env) if profile.launch_cwd_env else None
    if env:
        expanded = os.path.expanduser(env).replace("\\", "/")
        if not expanded.startswith("/"):
            return []
        candidate = os.path.realpath(expanded).replace("\\", "/").rstrip("/") or "/"
        ws = os.path.realpath(os.path.expanduser(workspace)).replace("\\", "/").rstrip("/") or "/"
        if candidate == "/" or not os.path.isdir(candidate):
            return []
        if candidate == ws or ws.startswith(candidate + "/"):
            return []
        inside = _launch_repo_segment(candidate, ws)
        if inside:
            return inside
        return ["path:" + candidate + "/**"]
    return _launch_repo_segment(os.getcwd(), workspace)
''')


def patch_test(src):
    src = once(src, """import json
""", """import dataclasses
import json
""")
    src = once(src, """def test_path_and_command_scope():
""", r'''def test_an_explicit_external_launch_dir_is_the_launch_grant():
    """#647: a per-fire worktree is not under the workspace, but its declared launch dir is
    still the one place this session may reach. No other external path is widened."""
    ws, launched, sibling = _workspace(), _workspace(), _workspace()
    key = "HESTIA_TEST_LAUNCH_CWD"
    previous = os.environ.get(key)
    target = os.path.join(launched, "notes.md")
    other = os.path.join(sibling, "other.md")
    for path in (target, other):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x\n")
    try:
        os.environ[key] = launched
        prof = dataclasses.replace(_profile(ws, []), launch_cwd_env=key)
        expected = "path:" + os.path.realpath(launched).replace("\\", "/").rstrip("/") + "/**"
        check("external-launch-grant-is-exact-recursive-path",
              G.launch_cwd_repo(prof, ws) == [expected], G.launch_cwd_repo(prof, ws))
        allowed = G.evaluate(G.NormalizedEvent(tool="Read", paths=[target], cwd=launched), prof, ws)
        check("external-launch-file-allows", allowed.decision == "allow", allowed)
        denied = G.evaluate(G.NormalizedEvent(tool="Read", paths=[other], cwd=launched), prof, ws)
        check("external-sibling-still-denies", denied.blocks and denied.rule == "mrh.path", denied)

        os.environ[key] = os.path.dirname(ws)
        check("workspace-ancestor-is-not-a-launch-grant", G.launch_cwd_repo(prof, ws) == [],
              G.launch_cwd_repo(prof, ws))
        os.environ[key] = "relative-launch-dir"
        check("relative-launch-dir-is-not-a-grant", G.launch_cwd_repo(prof, ws) == [],
              G.launch_cwd_repo(prof, ws))
        os.environ[key] = "relative/" + ws
        check("relative-path-containing-workspace-is-not-a-grant", G.launch_cwd_repo(prof, ws) == [],
              G.launch_cwd_repo(prof, ws))
        os.environ[key] = os.path.join(launched, "nope", "deeper")
        check("missing-launch-dir-is-not-a-grant", G.launch_cwd_repo(prof, ws) == [],
              G.launch_cwd_repo(prof, ws))
        os.environ[key] = target
        check("regular-file-launch-target-is-not-a-grant", G.launch_cwd_repo(prof, ws) == [],
              G.launch_cwd_repo(prof, ws))
        os.environ[key] = os.path.abspath(os.sep)
        check("filesystem-root-is-not-a-launch-grant", G.launch_cwd_repo(prof, ws) == [],
              G.launch_cwd_repo(prof, ws))
        launch_alias = os.path.join(sibling, "launch-alias")
        os.symlink(launched, launch_alias, target_is_directory=True)
        os.environ[key] = launch_alias
        check("launch-symlink-resolves-to-the-exact-directory",
              G.launch_cwd_repo(prof, ws) == [expected], G.launch_cwd_repo(prof, ws))
        ancestor_alias = os.path.join(sibling, "ancestor-alias")
        os.symlink(os.path.dirname(ws), ancestor_alias, target_is_directory=True)
        os.environ[key] = ancestor_alias
        check("workspace-ancestor-symlink-is-not-a-grant", G.launch_cwd_repo(prof, ws) == [],
              G.launch_cwd_repo(prof, ws))
        os.makedirs(os.path.join(ws, "granted"), exist_ok=True)
        os.environ[key] = os.path.join(ws, "granted")
        check("in-workspace-launch-keeps-repo-grant", G.launch_cwd_repo(prof, ws) == ["granted"],
              G.launch_cwd_repo(prof, ws))
        os.environ.pop(key)
        denied = G.evaluate(G.NormalizedEvent(tool="Read", paths=[target], cwd=launched), prof, ws)
        check("external-cwd-without-declaration-still-denies",
              denied.blocks and denied.rule == "mrh.path", denied)
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def test_legacy_launch_fallback_uses_path_boundaries():
    ws = _workspace()
    prof = dataclasses.replace(_profile(ws, []), launch_cwd_env="")
    real_getcwd = G.os.getcwd
    try:
        G.os.getcwd = lambda: os.path.join(os.sep, "evil", ws.lstrip(os.sep), "SAGE", "y")
        check("fallback-rejects-a-workspace-substring-outside-its-root",
              G.launch_cwd_repo(prof, ws) == [], G.launch_cwd_repo(prof, ws))
        G.os.getcwd = lambda: ws + "-other/x"
        check("fallback-rejects-a-sibling-with-the-same-prefix",
              G.launch_cwd_repo(prof, ws) == [], G.launch_cwd_repo(prof, ws))
        G.os.getcwd = lambda: os.path.join(ws, "granted", "nested")
        check("fallback-keeps-a-real-workspace-descendant",
              G.launch_cwd_repo(prof, ws) == ["granted"], G.launch_cwd_repo(prof, ws))
    finally:
        G.os.getcwd = real_getcwd


def test_path_and_command_scope():
''')
    src = once(src, """    "test_path_and_command_scope",
""", """    "test_path_and_command_scope",
    "test_an_explicit_external_launch_dir_is_the_launch_grant",
    "test_legacy_launch_fallback_uses_path_boundaries",
""")
    return once(src, """    test_path_and_command_scope()
""", """    test_path_and_command_scope()
    test_an_explicit_external_launch_dir_is_the_launch_grant()
    test_legacy_launch_fallback_uses_path_boundaries()
""")


def diff(path, old, new):
    hdr = f"diff --git a/{path} b/{path}\n"
    return hdr + "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"))


def hunks(section):
    out, cur = [], None
    for line in section.splitlines(keepends=True)[1:]:
        if line.startswith("@@ "):
            m = re.match(r"@@ -(\d+)(?:,(\d+))?", line)
            cur = {"start": int(m.group(1)) - 1, "old": [], "new": []}
            out.append(cur)
        elif cur is not None and not line.strip():
            cur["old"].append(line)
            cur["new"].append(line)
        elif cur is not None and line[:1] in " +-" and not line.startswith(("--- ", "+++ ")):
            if line[0] in " -":
                cur["old"].append(line[1:])
            if line[0] in " +":
                cur["new"].append(line[1:])
    return out


def strict_apply(old_text, section):
    lines = old_text.splitlines(keepends=True)
    out, pos = [], 0
    for h in hunks(section):
        start = max(h["start"] if h["old"] else h["start"] + 1, 0)
        out.extend(lines[pos:start])
        assert lines[start:start + len(h["old"])] == h["old"], ("strict", start)
        out.extend(h["new"])
        pos = start + len(h["old"])
    out.extend(lines[pos:])
    return "".join(out)


def sections(text):
    return {sec.splitlines()[0].split(" b/", 1)[1]: sec for sec in text.split("diff --git ")[1:]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    core = patch_core(blob(CORE))
    test_new = patch_test(blob(TEST))
    (OUT / "hestia_gate_core.py").write_text(core, encoding="utf-8")
    (OUT / "test_gate_core.py").write_text(test_new, encoding="utf-8")
    runtime = OUT / "runtime" / "plugins"
    shared_out = runtime / "_shared"
    shared_out.mkdir(parents=True, exist_ok=True)
    (shared_out / "hestia_gate_core.py").write_text(core, encoding="utf-8")
    (shared_out / "test_gate_core.py").write_text(test_new, encoding="utf-8")
    for seat in ("claude-code", "codex", "kimi", "gemini", "_template"):
        link = runtime / seat
        if not link.exists():
            link.symlink_to(WT / "plugins" / seat, target_is_directory=True)

    sys.path.insert(0, str(WT / "tools"))
    import hooks_gt
    assert hooks_gt.check(WT) == [], hooks_gt.check(WT)
    src_abs = WT / CORE
    real_read = pathlib.Path.read_bytes

    def served(self):
        return core.encode() if self.resolve() == src_abs else real_read(self)

    pathlib.Path.read_bytes = served
    try:
        gt_out = OUT / "gt.part"
        n = hooks_gt.emit_patch(WT, gt_out)
        tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    print(f"hooks_gt emitted {n} files")

    body = diff(CORE, blob(CORE), core) + gt_out.read_text(encoding="utf-8") + diff(TEST, blob(TEST), test_new)
    body = re.sub(r"(?m)^ $", "", body)
    gt_out.unlink()
    sha = hashlib.sha256(body.encode()).hexdigest()
    (OUT / f"{sha}.patch").write_text(body, encoding="utf-8")
    for path, sec in sections(body).items():
        got = strict_apply(blob(path), sec)
        want = core if path == CORE else test_new if path == TEST else tree[path].decode()
        assert got == want, f"verify: {path}"
        print(f"  ok  {path}")
    assert hooks_gt.strip_header(tree[GT]) == core.encode()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT).decode().strip()
    print(f"base {head}\npatch {OUT / (sha + '.patch')}\nsha256 {sha}")


main()
