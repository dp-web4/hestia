#!/usr/bin/env python3
"""Build the held patch for hestia #656: escalation detail carries the act's cwd.

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
CLOSURE = "plugins/_shared/hestia_governance_closure.py"
MECHANISM = "plugins/_shared/hestia_gate_mechanism.py"
GATE = "plugins/_shared/hestia_single_gate.py"
SEAT = "plugins/_shared/seat_gate_boundary_test.py"
SOURCES = (CLOSURE, MECHANISM, GATE)
GT = {CLOSURE: "hooks-gt/_shared/hestia_governance_closure.py",
      MECHANISM: "hooks-gt/_shared/hestia_gate_mechanism.py",
      GATE: "hooks-gt/_shared/hestia_single_gate.py"}


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new):
    assert text.count(old) == 1, ("anchor not exactly once", old[:80], text.count(old))
    return text.replace(old, new)


def patch_closure(src):
    src = once(src, """    "resolve_location",
""", """    "resolve_location",
    "effective_cwd",
""")
    src = once(src, """def _bash_write_targets(command: str) -> list:
""", """def _bash_write_targets(command: str, *, with_cwd: bool = False) -> list:
""")
    return once(src, r'''    if deferred_oog:
        raise _OutOfGrammar()
    return targets


# ── Classification''', r'''    if deferred_oog:
        raise _OutOfGrammar()
    return (targets, eff) if with_cwd else targets


def effective_cwd(tool_name: str, tool_input: Any, cwd: Optional[str] = None) -> Optional[str]:
    """The act's cwd after literal `cd` commands, or the supplied harness cwd when unknown.

    This uses the same walk as write-target resolution, so location evidence and the write's
    resolved targets cannot disagree. It never raises and never widens authority.
    """
    if tool_name not in ("Bash", "Shell") or not isinstance(tool_input, dict):
        return cwd
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return cwd
    try:
        _, effective = _bash_write_targets(command, with_cwd=True)
    except Exception:  # noqa: BLE001 — unknown evidence falls back to the harness's cwd
        return cwd
    return resolve_location(effective, cwd) if effective else cwd


# ── Classification''')


def patch_mechanism(src):
    src = once(src, """                     resolved_targets_complete=True):
""", """                     resolved_targets_complete=True, event_cwd=None):
""")
    src = once(src, r'''    key: they are derived from the same act. Old daemons ignore the key; callers that omit
    it price exactly as before."""
    claim_args = {
''', r'''    key: they are derived from the same act. Old daemons ignore the key; callers that omit
    it price exactly as before. `event_cwd` rides the existing free-text detail, so a reviewer
    can locate a path-relative act without a schema migration (#656).
    """
    location = ""
    if isinstance(event_cwd, str) and event_cwd.strip():
        location = f" Event cwd: {os.path.realpath(os.path.expanduser(event_cwd))}"
    claim_args = {
''')
    return once(src, """        "detail": ("Auto-opened by the gate on a refused write; the member stated no rationale "
                   "because it did not choose to escalate. Approving authorises this one write."),
""", """        "detail": ("Auto-opened by the gate on a refused write; the member stated no rationale "
                   "because it did not choose to escalate. Approving authorises this one write."
                   + location),
""")


def patch_gate(src):
    return once(src, """            resolved_targets=write_set[0], resolved_targets_complete=write_set[1])
""", """            resolved_targets=write_set[0], resolved_targets_complete=write_set[1],
            event_cwd=closure.effective_cwd(ev.tool, ev.tool_input, ev.cwd or os.getcwd()))
""")


def patch_seat(src):
    src = once(src, """            home = fx.home(seat, stub.url)
            v, text, _ = run(seat, home, native(seat, "Write", {"file_path": gate_file(fx, seat), "content": "x"}))
            check(f"{seat}-denied", v == "deny", text)
""", """            home = fx.home(seat, stub.url)
            ev = native(seat, "Write", {"file_path": gate_file(fx, seat), "content": "x"})
            ev["cwd"] = fx.repo
            v, text, _ = run(seat, home, ev)
            check(f"{seat}-denied", v == "deny", text)
""")
    src = once(src, """            check(f"{seat}-claim-carries-resolved-target",
""", """            check(f"{seat}-claim-carries-event-cwd",
                  claims and claims[0].get("detail", "").endswith(f"Event cwd: {fx.repo}"), claims)
            check(f"{seat}-claim-carries-resolved-target",
""")
    return once(src, """                    claims and want in (claims[0].get("resolved_targets") or []),
                      (want, claims and claims[0].get("resolved_targets")))
""", """                    claims and want in (claims[0].get("resolved_targets") or []),
                      (want, claims and claims[0].get("resolved_targets")))
            expected_cwd = os.path.realpath(dest if label in ("relative-write", "cd-then-touch") else fx.repo)
            check(f"{seat}-{label}-claim-carries-effective-cwd",
                  claims and claims[0].get("detail", "").endswith(
                      f"Event cwd: {expected_cwd}"), claims)
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
    revised = {CLOSURE: patch_closure(blob(CLOSURE)),
               MECHANISM: patch_mechanism(blob(MECHANISM)),
               GATE: patch_gate(blob(GATE)),
               SEAT: patch_seat(blob(SEAT))}
    for path, text in revised.items():
        (OUT / pathlib.Path(path).name).write_text(text, encoding="utf-8")

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

    body = "".join(diff(path, blob(path), revised[path]) for path in SOURCES)
    body += gt_out.read_text(encoding="utf-8") + diff(SEAT, blob(SEAT), revised[SEAT])
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
