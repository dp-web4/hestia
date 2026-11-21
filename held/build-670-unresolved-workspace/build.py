#!/usr/bin/env python3
"""Build the held patch for hestia #670: workspace resolution and absolute scope paths.

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
    src = once(src, """# ── Workspace + scope resolution ─────────────────────────────────────────────────────────
def detect_workspace""", """# ── Workspace + scope resolution ─────────────────────────────────────────────────────────
UNRESOLVED_WORKSPACE = "hestia:unresolved-workspace"


def detect_workspace""")
    src = once(src, """    d = os.getcwd()
    for _ in range(8):
        if os.path.isfile(os.path.join(d, ".hestia-workspace")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.getcwd()
""", """    d = os.getcwd()
    for _ in range(8):
        if os.path.isfile(os.path.join(d, ".hestia-workspace")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return UNRESOLVED_WORKSPACE
""")
    src = once(src, """    # Gate 1b — MRH scope. A repo-named MCP call is scoped on the NAME it carries (its
""", """    if ws == UNRESOLVED_WORKSPACE:
        return _deny(
            "mrh.command",
            "cannot judge scope: no workspace is configured. Set HESTIA_WORKSPACE to the actual "
            "workspace root, or place .hestia-workspace in that root or an ancestor of the launch "
            "cwd. An unlocated workspace grants nothing and cannot be a denial domain.",
            innate=True,
        )

    # Gate 1b — MRH scope. A repo-named MCP call is scoped on the NAME it carries (its
""")
    return once(src, r'''    for after in scan.split(workspace)[1:]:
        # Resolve the whole token before reading a segment off it (kimi #940 B7). Taking the
        # head lexically let `cat <ws>/repo-a/../repo-b/secret` pass on `repo-a` while
        # resolving into an ungranted repo — path_in_scope's B5 one function over. A command's
        # text is member-controlled end to end, so this one needs no harness to cooperate.
        tok = re.split(r"""[\s"'`);&|<>]""", after.lstrip("/"), 1)[0]
        if patterns and _only_pattern_text(workspace + after[:len(after) - len(after.lstrip("/"))] + tok,
                                           patterns, judged_words):
            continue
        resolved = os.path.normpath(f"{ws}/{tok}").replace("\\", "/")
        if resolved != ws and not resolved.startswith(ws + "/"):
            # Traversed out of the workspace: judged WHERE IT LANDS, by the outside rule (pass 3),
            # so a grant the operator makes for the landing path is honoured however it is
            # spelled. Before 2026-10-05 this refused unconditionally, which made a granted
            # outside path unreachable through a `<ws>/../…` spelling — a grant that could never
            # be spent, re-escalating forever.
            refused = _outside_reach_refused(resolved, scopes, workspace, cwd, egress, home_markers)
            if refused is None:
                continue
            return False, (tok or "<workspace root>"), refused[1]
        # EGRESS FIRST, for every token: a symlink must not launder a forbidden target past a grant.
        hidden = _symlink_target_forbidden(resolved, egress)
        if hidden is not None:
            return False, hidden, hidden
        seg = resolved[len(ws):].lstrip("/").split("/", 1)[0]
        if seg not in repo_scopes and not _within_path_grant(resolved, scopes, workspace):
            refused = _symlinked_reach_verdict(resolved, seg, repo_scopes, scopes, workspace)
            if refused is None:
                continue
            return (False,) + refused
''', r'''    try:
        absolute = _outside_candidates(scan, cwd or os.getcwd())
    except _Unmodelled:
        absolute = []
    for spelling, kind, _globbed in absolute:
        if kind != "abs":
            continue
        resolved = os.path.normpath(spelling).replace("\\", "/")
        if resolved != ws and not resolved.startswith(ws + "/"):
            continue
        if patterns and _only_pattern_text(resolved, patterns, judged_words):
            continue
        # EGRESS FIRST, for every token: a symlink must not launder a forbidden target past a grant.
        hidden = _symlink_target_forbidden(resolved, egress)
        if hidden is not None:
            return False, hidden, hidden
        seg = resolved[len(ws):].lstrip("/").split("/", 1)[0]
        if seg not in repo_scopes and not _within_path_grant(resolved, scopes, workspace):
            refused = _symlinked_reach_verdict(resolved, seg, repo_scopes, scopes, workspace)
            if refused is None:
                continue
            return (False,) + refused
''')


def patch_test(src):
    src = once(src, """import json
""", """import dataclasses
import json
""")
    src = once(src, """def test_path_and_command_scope():
""", r'''def test_workspace_detection_is_explicit_and_unresolved_denies():
    ws = _workspace()
    nested = os.path.join(ws, "nested")
    os.makedirs(nested)
    key = "HESTIA_TEST_WORKSPACE"
    previous_env, previous_cwd = os.environ.get(key), os.getcwd()
    try:
        os.environ.pop(key, None)
        os.chdir(nested)
        prof = dataclasses.replace(_profile(ws, []), workspace_env=key)
        check("no-env-no-marker-is-explicitly-unresolved",
              G.detect_workspace(prof) == G.UNRESOLVED_WORKSPACE, G.detect_workspace(prof))
        target = os.path.join(ws, "ungranted", "README.md")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("x\n")
        verdict = G.evaluate(G.NormalizedEvent(tool="Read", paths=[target], cwd=nested), prof)
        check("unresolved-workspace-denies-instead-of-using-cwd",
              verdict.blocks and verdict.rule == "mrh.command" and verdict.innate, verdict)
        check("unresolved-denial-names-the-configuration-remedy",
              "HESTIA_WORKSPACE" in verdict.reason and ".hestia-workspace" in verdict.reason,
              verdict.reason)
        os.environ[key] = ws
        check("valid-env-workspace-still-wins", G.detect_workspace(prof) == ws,
              G.detect_workspace(prof))
        os.environ[key] = os.path.join(ws, "deleted")
        marker = os.path.join(ws, ".hestia-workspace")
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write("# test marker\n")
        check("marker-resolves-from-a-child-cwd", G.detect_workspace(prof) == ws,
              G.detect_workspace(prof))
        os.unlink(marker)
        check("stale-env-without-marker-is-unresolved",
              G.detect_workspace(prof) == G.UNRESOLVED_WORKSPACE, G.detect_workspace(prof))
    finally:
        os.chdir(previous_cwd)
        if previous_env is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous_env


def test_absolute_scope_paths_do_not_depend_on_process_cwd():
    ws = _workspace()
    for repo in ("granted", "ungranted"):
        os.makedirs(os.path.join(ws, repo), exist_ok=True)
        with open(os.path.join(ws, repo, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("x\n")
    prof = _profile(ws, ["repo:granted"])
    for cwd in (ws, os.path.join(ws, "tools"), _workspace()):
        ok, offending = G.command_in_scope(f"cat {ws}/ungranted/README.md", ["granted"], ws, cwd)
        check(f"absolute-ungranted-path-denies-at-any-cwd: {cwd}", not ok and offending,
              (ok, offending))
        ok, offending = G.command_in_scope(f"cat {ws}/granted/README.md", ["granted"], ws, cwd)
        check(f"granted-control-allows-at-any-cwd: {cwd}", ok, (ok, offending))
    ok, offending = G.command_in_scope("cat ungranted/README.md", ["granted"], ws, ws)
    check("bare-ungranted-token-denies-at-root", not ok and offending, (ok, offending))
    sibling = ws + "-sibling"
    os.makedirs(sibling, exist_ok=True)
    with open(os.path.join(sibling, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("x\n")
    ok, offending = G.command_in_scope(f"cat {sibling}/README.md", ["granted"], ws, ws)
    check("workspace-prefix-sibling-is-not-inside", not ok and offending, (ok, offending))


def test_path_and_command_scope():
''')
    src = once(src, """    "test_path_and_command_scope",
""", """    "test_path_and_command_scope",
    "test_workspace_detection_is_explicit_and_unresolved_denies",
    "test_absolute_scope_paths_do_not_depend_on_process_cwd",
""")
    return once(src, """    test_path_and_command_scope()
""", """    test_path_and_command_scope()
    test_workspace_detection_is_explicit_and_unresolved_denies()
    test_absolute_scope_paths_do_not_depend_on_process_cwd()
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
