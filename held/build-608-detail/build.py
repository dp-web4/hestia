#!/usr/bin/env python3
"""Build the held patch for hestia #608: refusal detail names the actual rule.

argv: <hestia worktree at the base> <out dir>
Writes: mechanism_rev.py, single_gate_rev.py, seat_gate_boundary_test_rev.py and <sha256>.patch.
"""
import difflib
import hashlib
import pathlib
import re
import subprocess
import sys

WT, OUT = (pathlib.Path(a).resolve() for a in sys.argv[1:3])
sys.dont_write_bytecode = True
MECH = "plugins/_shared/hestia_gate_mechanism.py"
GATE = "plugins/_shared/hestia_single_gate.py"
TEST = "plugins/_shared/seat_gate_boundary_test.py"
GT_MECH = "hooks-gt/_shared/hestia_gate_mechanism.py"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new):
    assert text.count(old) == 1, ("anchor not exactly once", old[:80], text.count(old))
    return text.replace(old, new)


def patch_mechanism(src):
    src = once(src, """                     resolved_targets_complete=True):
""", """                     resolved_targets_complete=True, refusal_rule=None):
""")
    return once(src, """        "detail": ("Auto-opened by the gate on a refused write; the member stated no rationale "
                   "because it did not choose to escalate. Approving authorises this one write."),
""", """        "detail": ("Auto-opened by the gate on a refused act"
                   + (f" ({refusal_rule})" if refusal_rule else "")
                   + "; the member stated no rationale because it did not choose to escalate. "
                   + "Approving authorises this one write."),
""")


def patch_gate(src):
    return once(src, """            resolved_targets=write_set[0], resolved_targets_complete=write_set[1])
""", """            resolved_targets=write_set[0], resolved_targets_complete=write_set[1],
            refusal_rule=cv.rule)
""")


def patch_test(src):
    src = once(src, """ALL = [
""", """def test_stated_detail_names_the_actual_refusal_rule_608():
    def arm(seat, fx):
        stub = Stub()
        try:
            home = fx.home(seat, stub.url)
            target = gate_file(fx, seat)
            v, text, _ = run(seat, home, native(seat, "Write", {"file_path": target, "content": "x"}))
            check(f"{seat}-denied", v == "deny", text)
            claims = stub.args("hestia_gate_escalation_claim")
            detail = claims and claims[0].get("detail", "")
            check(f"{seat}-real-write-rule", "governance-closure-write" in detail, detail)
            check(f"{seat}-not-asserted-a-write", "refused write" not in detail, detail)

            mark = len(stub.calls)
            command = f"bash -c 'cat {target}'"
            v2, text2, _ = run(seat, home, native(seat, "Bash", {"command": command}, n=2))
            check(f"{seat}-read-loop-denied", v2 == "deny", text2)
            followup = [a for n, a in stub.calls[mark:] if n == "hestia_gate_escalation_claim"]
            detail2 = followup and followup[0].get("detail", "")
            check(f"{seat}-read-fp-rule", "governance-closure-out-of-grammar" in detail2, detail2)
            check(f"{seat}-read-fp-not-asserted-a-write", "refused write" not in detail2, detail2)
        finally:
            stub.close()
    _each_seat(arm)


ALL = [
""")
    return once(src, """    test_gate_file_shell_write_refused,
""", """    test_gate_file_shell_write_refused,
    test_stated_detail_names_the_actual_refusal_rule_608,
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
    mechanism = patch_mechanism(blob(MECH))
    gate = patch_gate(blob(GATE))
    test_new = patch_test(blob(TEST))
    for name, text in (("mechanism_rev.py", mechanism), ("single_gate_rev.py", gate),
                       ("seat_gate_boundary_test_rev.py", test_new)):
        (OUT / name).write_text(text, encoding="utf-8")

    sys.path.insert(0, str(WT / "tools"))
    import hooks_gt
    assert hooks_gt.check(WT) == [], hooks_gt.check(WT)
    sources = {WT / MECH: mechanism, WT / GATE: gate}
    real_read = pathlib.Path.read_bytes

    def served(self):
        source = sources.get(self.resolve())
        return source.encode() if source is not None else real_read(self)

    pathlib.Path.read_bytes = served
    try:
        gt_out = OUT / "gt.part"
        n = hooks_gt.emit_patch(WT, gt_out)
        tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    print(f"hooks_gt emitted {n} files")

    body = (diff(MECH, blob(MECH), mechanism) + diff(GATE, blob(GATE), gate)
            + gt_out.read_text(encoding="utf-8") + diff(TEST, blob(TEST), test_new))
    gt_out.unlink()
    sha = hashlib.sha256(body.encode()).hexdigest()
    (OUT / f"{sha}.patch").write_text(body, encoding="utf-8")
    for path, sec in sections(body).items():
        got = strict_apply(blob(path), sec)
        want = (mechanism if path == MECH else gate if path == GATE
                else test_new if path == TEST else tree[path].decode())
        assert got == want, f"verify: {path}"
        print(f"  ok  {path}")
    assert hooks_gt.strip_header(tree[GT_MECH]) == mechanism.encode()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT).decode().strip()
    print(f"base {head}\npatch {OUT / (sha + '.patch')}\nsha256 {sha}")


main()
