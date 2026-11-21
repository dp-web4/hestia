#!/usr/bin/env python3
"""Build the held patch for hestia #622: a committed deny is an appealable refusal.

argv: <hestia worktree at the base> <out dir>
Writes: single_gate_rev.py, one_gate_decide_contract_test_rev.py, seat_gate_boundary_test_rev.py
and <sha256>.patch.
"""
import difflib
import hashlib
import pathlib
import re
import subprocess
import sys

WT, OUT = (pathlib.Path(a).resolve() for a in sys.argv[1:3])
sys.dont_write_bytecode = True
GATE = "plugins/_shared/hestia_single_gate.py"
TEST = "tools/one_gate_decide_contract_test.py"
SEAT = "plugins/_shared/seat_gate_boundary_test.py"
GT = "hooks-gt/_shared/hestia_single_gate.py"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new):
    assert text.count(old) == 1, ("anchor not exactly once", old[:80], text.count(old))
    return text.replace(old, new)


def patch_gate(src):
    src = once(src, """    receipt_status: str = ""              # the record_decision status of THIS verdict
""", """    receipt_status: str = ""              # the record_decision status of THIS verdict
    deny_hash: Optional[str] = None       # the committed deny row an appeal may name
""")
    src = once(src, """        return replace(denied, evidence_committed=second.committed,
                       receipt_status=second.status)
""", """        return replace(denied, evidence_committed=second.committed,
                       receipt_status=second.status,
                       deny_hash=second.entry_hash if second.committed else None)
""")
    src = once(src, """        return replace(d, evidence_committed=True, receipt_status=receipt.status)
""", """        return replace(d, evidence_committed=True, receipt_status=receipt.status,
                       deny_hash=receipt.entry_hash if d.decision == "deny" else None)
""")
    src = once(src, """    return replace(d, evidence_committed=False, receipt_status=receipt.status,
                   anomaly=d.anomaly or d.decision != "deny")
""", """    return replace(d, evidence_committed=False, receipt_status=receipt.status,
                   anomaly=True)
""")
    src = once(src, '''    the daemon wrote it — that is its steering text — followed by the remedy when it does not
    already carry it."""
''', '''    the daemon wrote it — that is its steering text — followed by the remedy when it does not
    already carry it. An unrecorded deny drops any hash-dependent remedy and says that appeal is
    unavailable."""
''')
    return once(src, """    if remedy and remedy not in text:
        text = f"{text.rstrip('.')}. {remedy}"
    lines.append(text)
    return "\\n".join(lines)
""", """    deny_hash = getattr(decision, "deny_hash", None) if verb == "deny" else None
    if verb == "deny" and not deny_hash and (
            "chain hash" in remedy or "deny_hash" in remedy or "hestia_appeal" in remedy):
        remedy = ""
    if remedy and remedy not in text:
        text = f"{text.rstrip('.')}. {remedy}"
    lines.append(text)
    if deny_hash:
        lines.append(f"DENY {deny_hash} — appeal with this chain hash.")
    elif verb == "deny":
        lines.append("UNRECORDED — appeal unavailable.")
    return "\\n".join(lines)
""")


def patch_test(src):
    src = once(src, """def test_the_key_from_the_raw_event_reaches_every_join(m, g, wc, home):
""", """def test_the_deny_receipt_is_an_appealable_refusal_622(m, g, wc, home):
    def decided(policy):
        stub = Stub(policy)
        try:
            with _Env(m, stub.url, home):
                d, _ = _decide(g, "codex", *_act(IN_SCOPE_EDIT), home)
            return d, g.render(d)
        finally:
            stub.close()

    d, rendered = decided(Policy(query=lambda a: "deny"))
    check("committed-deny-hash", d.decision == "deny" and d.evidence_committed
          and d.deny_hash == "e" * 64, d)
    check("committed-deny-is-appealable",
          f"DENY {'e' * 64} — appeal with this chain hash." in rendered, rendered)
    check("committed-deny-is-not-unrecorded", "UNRECORDED" not in rendered, rendered)

    d, rendered = decided(Policy(query=lambda a: "deny", witness="refuse-all"))
    check("uncommitted-deny-has-no-hash", d.decision == "deny" and not d.evidence_committed
          and d.receipt_status == "refused" and d.deny_hash is None, d)
    check("uncommitted-deny-is-integrity-anomaly", d.anomaly and d.verdict_available, d)
    check("uncommitted-deny-says-appeal-unavailable",
          "UNRECORDED — appeal unavailable." in rendered and "DENY " not in rendered, rendered)
    check("uncommitted-deny-drops-the-hash-dependent-remedy",
          "chain hash" not in rendered and "hestia_appeal" not in rendered, rendered)

    d, rendered = decided(Policy(witness="refuse-allow"))
    check("committed-replacement-deny-hash", d.rule == "gate.evidence_uncommitted"
          and d.evidence_committed and d.deny_hash == "b" * 64, d)
    check("committed-replacement-deny-is-appealable",
          f"DENY {'b' * 64} — appeal with this chain hash." in rendered, rendered)

    d, rendered = decided(Policy(witness="refuse-all"))
    check("uncommitted-replacement-deny-has-no-hash", d.rule == "gate.evidence_uncommitted"
          and not d.evidence_committed and d.receipt_status == "refused" and d.deny_hash is None, d)
    check("uncommitted-replacement-deny-is-integrity-anomaly", d.anomaly, d)
    check("uncommitted-replacement-deny-says-appeal-unavailable",
          "UNRECORDED — appeal unavailable." in rendered and "DENY " not in rendered, rendered)

    d, rendered = decided(Policy())
    check("allow-has-no-deny-hash", d.decision == "allow" and d.deny_hash is None, d)
    check("allow-has-no-appeal-or-unrecorded-line",
          "appeal with this chain hash" not in rendered and "UNRECORDED" not in rendered, rendered)


def test_the_key_from_the_raw_event_reaches_every_join(m, g, wc, home):
""")
    return once(src, """    test_the_key_from_the_raw_event_reaches_every_join,
""", """    test_the_deny_receipt_is_an_appealable_refusal_622,
    test_the_key_from_the_raw_event_reaches_every_join,
""")


def patch_seat(src):
    src = once(src, """            check(f"{seat}-witnessed", any(a.get("event_type") == "gate_self_access"
""", """            check(f"{seat}-denial-is-appealable",
                  f"DENY {'b' * 64} — appeal with this chain hash." in text, text)
            check(f"{seat}-witnessed", any(a.get("event_type") == "gate_self_access"
""")
    return once(src, """        v, text, _ = run(seat, home, native(seat, "Write", {"file_path": gate_file(fx, seat), "content": "x"}))
        check(f"{seat}-gate-write-still-gate-self", v == "deny" and "gate.self_access" in text, text)
""", """        v, text, channel = run(seat, home, native(seat, "Write", {"file_path": gate_file(fx, seat), "content": "x"}))
        check(f"{seat}-gate-write-still-gate-self", v == "deny" and "gate.self_access" in text, text)
        check(f"{seat}-unrecorded-deny-has-no-appeal-hash",
              "UNRECORDED — appeal unavailable." in text and "DENY " not in text
              and "chain hash" not in text and "hestia_appeal" not in text, text)
        check(f"{seat}-unrecorded-deny-is-an-anomaly", channel == "exit2", channel)
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
    gate = patch_gate(blob(GATE))
    test_new = patch_test(blob(TEST))
    seat_new = patch_seat(blob(SEAT))
    for name, text in (("single_gate_rev.py", gate),
                       ("one_gate_decide_contract_test_rev.py", test_new),
                       ("seat_gate_boundary_test_rev.py", seat_new)):
        (OUT / name).write_text(text, encoding="utf-8")

    sys.path.insert(0, str(WT / "tools"))
    import hooks_gt
    assert hooks_gt.check(WT) == [], hooks_gt.check(WT)
    src_abs = WT / GATE
    real_read = pathlib.Path.read_bytes

    def served(self):
        return gate.encode() if self.resolve() == src_abs else real_read(self)

    pathlib.Path.read_bytes = served
    try:
        gt_out = OUT / "gt.part"
        n = hooks_gt.emit_patch(WT, gt_out)
        tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    print(f"hooks_gt emitted {n} files")

    body = (diff(GATE, blob(GATE), gate) + gt_out.read_text(encoding="utf-8")
            + diff(TEST, blob(TEST), test_new) + diff(SEAT, blob(SEAT), seat_new))
    gt_out.unlink()
    sha = hashlib.sha256(body.encode()).hexdigest()
    (OUT / f"{sha}.patch").write_text(body, encoding="utf-8")
    for path, sec in sections(body).items():
        got = strict_apply(blob(path), sec)
        want = gate if path == GATE else test_new if path == TEST else seat_new if path == SEAT else tree[path].decode()
        assert got == want, f"verify: {path}"
        print(f"  ok  {path}")
    assert hooks_gt.strip_header(tree[GT]) == gate.encode()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT).decode().strip()
    print(f"base {head}\npatch {OUT / (sha + '.patch')}\nsha256 {sha}")


main()
