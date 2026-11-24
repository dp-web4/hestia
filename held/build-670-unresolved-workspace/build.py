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
MECHANISM = "plugins/_shared/hestia_gate_mechanism.py"
MECH_TEST = "plugins/_shared/hestia_gate_mechanism_test.py"
PUBLIC_TEST = "tools/public_boundary_test.py"
SOURCES = (CORE, MECHANISM)
GT = {CORE: "hooks-gt/_shared/hestia_gate_core.py",
      MECHANISM: "hooks-gt/_shared/hestia_gate_mechanism.py"}


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
    src = once(src, '''    A public gate cannot infer an operator's repository names or home layout. Installers
    should always set ``HESTIA_WORKSPACE``. A ``.hestia-workspace`` marker is the portable
    fallback; absent either signal, cwd is returned and sibling-repository grants remain
    inert rather than widening from a guess.
    """
''', '''    A public gate cannot infer an operator's repository names or home layout. Installers
    should always set ``HESTIA_WORKSPACE``. A ``.hestia-workspace`` marker is the portable
    fallback; absent either signal, ``UNRESOLVED_WORKSPACE`` is returned and every bounded
    tool call refuses rather than guessing from the hook cwd.
    """
''')
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
''', r'''    for after in scan.split(workspace)[1:]:
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

    try:
        absolute = _outside_candidates(scan, cwd or os.getcwd())
    except _Unmodelled:
        absolute = []
    for spelling, kind, _globbed in absolute:
        if kind != "abs":
            continue
        resolved = os.path.normpath(spelling).replace("\\", "/")
        if resolved != ws and not resolved.startswith(ws + "/"):
            continue
        if patterns and _only_pattern_text(spelling, patterns, judged_words):
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


def patch_mechanism(src):
    return once(src, """    `detect_workspace` (env `HESTIA_WORKSPACE` when it names a real directory, else the
    marker-based cwd climb, else the core's documented default), so live and standing
    grants cannot diverge from the boundary the core's scope model actually enforces.
""", """    `detect_workspace` (env `HESTIA_WORKSPACE` when it names a real directory, else the
    marker-based cwd climb, else UNRESOLVED_WORKSPACE), so live and standing grants cannot
    diverge from the boundary the core's scope model actually enforces. An unconfigured
    bounded snapshot maps no repo-name grant.
""")


def patch_mechanism_test(src):
    src = once(src, """def test_workspace_mapping_discovers_root_without_env():
    \"\"\"Env absent: the core's marker-based cwd climb finds the workspace, and a standing
    repo-root grant still admits — the portability arm the machine-specific fallback
    failed.\"\"\"
    ws = _fake_workspace()
""", """def test_workspace_mapping_discovers_root_without_env():
    \"\"\"Env absent: the core's marker-based cwd climb finds the workspace, and a standing
    repo-root grant still admits — the portability arm the machine-specific fallback
    failed.\"\"\"
    ws = _fake_workspace()
    with open(os.path.join(ws, ".hestia-workspace"), "w", encoding="utf-8") as marker:
        marker.write("# discovery fixture\\n")
""")
    src = once(src, """def test_workspace_mapping_invalid_env_falls_back_to_discovery():
    \"\"\"An env var naming a NONEXISTENT dir must not poison the mapping: the core's
    detect_workspace ignores it (isdir check) and discovery still admits the grant.\"\"\"
    ws = _fake_workspace()
""", """def test_workspace_mapping_unresolved_without_marker():
    ws = _fake_workspace()
    old_env = os.environ.pop("HESTIA_WORKSPACE", None)
    old_cwd = os.getcwd()
    os.chdir(ws)
    try:
        check("unmarked_workspace_is_explicitly_unresolved",
              m._workspace_root() == "hestia:unresolved-workspace", m._workspace_root())
    finally:
        os.chdir(old_cwd)
        if old_env is not None:
            os.environ["HESTIA_WORKSPACE"] = old_env


def test_workspace_mapping_invalid_env_falls_back_to_discovery():
    \"\"\"An env var naming a NONEXISTENT dir must not poison the mapping: the core's
    detect_workspace ignores it (isdir check) and discovery still admits the grant.\"\"\"
    ws = _fake_workspace()
    with open(os.path.join(ws, ".hestia-workspace"), "w", encoding="utf-8") as marker:
        marker.write("# invalid-env discovery fixture\\n")
""")
    return once(src, """    test_workspace_mapping_invalid_env_falls_back_to_discovery,
""", """    test_workspace_mapping_unresolved_without_marker,
    test_workspace_mapping_invalid_env_falls_back_to_discovery,
""")


def patch_public_test(src):
    return once(src, """        check("no name-based discovery", detect_workspace(profile) == str(nested))
""", """        check("no-name-based-discovery-is-unresolved",
              detect_workspace(profile) == "hestia:unresolved-workspace")
""")


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
    parent = os.path.dirname(ws)
    leaf = os.path.basename(ws)
    for label, command in (
            ("parent-dot-segment", f"cat {parent}/./{leaf}/ungranted/README.md"),
            ("parent-dotdot-segment", f"cat {parent}/x/../{leaf}/ungranted/README.md"),
            ("parent-double-slash", f"cat {parent}//{leaf}/ungranted/README.md"),
            ("pattern-is-data-file-is-reach",
             f"grep -e {ws}/ungranted/README.md {parent}/./{leaf}/ungranted/README.md")):
        ok, offending = G.command_in_scope(command, ["granted"], ws, ws)
        check(f"normalized-absolute-pass-denies-{label}", not ok and offending, (ok, offending))
    ok, offending = G.command_in_scope(f"cat {parent}/./{leaf}/granted/README.md", ["granted"], ws, ws)
    check("normalized-absolute-pass-allows-granted-control", ok, (ok, offending))
    for label, command in (
            ("sed-write", f"sed 'w {ws}/ungranted/README.md' {ws}/granted/README.md"),
            ("pythonpath-import", f"PYTHONPATH={ws}/ungranted python3 -c 'import mod'"),
            ("data-operand", f"echo {ws}/ungranted/README.md")):
        ok, offending = G.command_in_scope(command, ["granted"], ws, ws)
        check(f"legacy-workspace-floor-still-denies-{label}", not ok and offending, (ok, offending))
    for label, command in (
            ("unclosed-quote", f"cat {ws}/ungranted/README.md \"oops"),
            ("substitution", f"cat {ws}/ungranted/$(echo x).txt")):
        ok, offending = G.command_in_scope(command, ["path:" + G.UNENUMERATED_TARGET], ws, ws)
        check(f"unenumerated-lift-does-not-widen-{label}", not ok and offending, (ok, offending))


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
    revised = {CORE: patch_core(blob(CORE)), TEST: patch_test(blob(TEST)),
               MECHANISM: patch_mechanism(blob(MECHANISM)),
               MECH_TEST: patch_mechanism_test(blob(MECH_TEST)),
               PUBLIC_TEST: patch_public_test(blob(PUBLIC_TEST))}
    for path, text in revised.items():
        (OUT / pathlib.Path(path).name).write_text(text, encoding="utf-8")
    runtime = OUT / "runtime" / "plugins"
    shared_out = runtime / "_shared"
    shared_out.mkdir(parents=True, exist_ok=True)
    (shared_out / "hestia_gate_core.py").write_text(revised[CORE], encoding="utf-8")
    (shared_out / "test_gate_core.py").write_text(revised[TEST], encoding="utf-8")
    for seat in ("claude-code", "codex", "kimi", "gemini", "_template"):
        link = runtime / seat
        if not link.exists():
            link.symlink_to(WT / "plugins" / seat, target_is_directory=True)

    sys.path.insert(0, str(WT / "tools"))
    import hooks_gt
    assert hooks_gt.check(WT) == [], hooks_gt.check(WT)
    src_abs = {WT / path: revised[path] for path in SOURCES}
    real_read = pathlib.Path.read_bytes

    def served(self):
        if self.resolve() in src_abs:
            return src_abs[self.resolve()].encode()
        return real_read(self)

    pathlib.Path.read_bytes = served
    try:
        gt_out = OUT / "gt.part"
        n = hooks_gt.emit_patch(WT, gt_out)
        tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    print(f"hooks_gt emitted {n} files")

    body = "".join(diff(path, blob(path), revised[path]) for path in revised)
    body += gt_out.read_text(encoding="utf-8")
    body = re.sub(r"(?m)^ $", "", body)
    gt_out.unlink()
    sha = hashlib.sha256(body.encode()).hexdigest()
    (OUT / f"{sha}.patch").write_text(body, encoding="utf-8")
    for path, sec in sections(body).items():
        got = strict_apply(blob(path), sec)
        want = revised[path] if path in revised else tree[path].decode()
        assert got == want, f"verify: {path}"
        print(f"  ok  {path}")
    for path, gt_path in GT.items():
        assert hooks_gt.strip_header(tree[gt_path]) == revised[path].encode()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT).decode().strip()
    print(f"base {head}\npatch {OUT / (sha + '.patch')}\nsha256 {sha}")


main()
