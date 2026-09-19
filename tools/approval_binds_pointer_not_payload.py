#!/usr/bin/env python3
"""When an approval is SPENT, does the record say what bytes it authorised?

#627 established that `act_digest` binds a truncated *rendering* of the act. #929
established that the rendering is on the chain for the hook door (201/201) and lost for
the documented door (6/6), and proposed persisting `act` as the repair. Both measure
whether the ACT STRING can be recovered.

This probe asks the next question, which neither answers: given the act string --
complete, untruncated, exactly as bound -- can a later auditor know WHAT WAS WRITTEN?

For a large class of spends it cannot, and the reason is not truncation or persistence.
The modal governed write on this fleet is `cp <scratch-source> <governed-target>`. The
act string is a POINTER. `act_digest` hashes the pointer; nothing hashes the referent.
The bytes live in a file outside the chain, which the daemon never reads, which the gate
never reads, and which is mutable for the whole 600s claim window
(`APPROVAL_CLAIM_WINDOW_SECS`) after the peer said yes.

Classification is deliberately performed on `stated_attempted_act` -- the capped preview
(#627) -- and not on any richer source, because that string is exactly what an auditor
reading the chain has. A probe that classified the true command would be measuring a
record nobody can read.

  indirect-copy   the act reads a source path; payload is behind a pointer, UNBOUND
  tool-path-only  `Edit -> /path`; the act names only the destination (#616, #600)
  inline-patch    codex's `*** Begin Patch ***`; the payload IS the act string, BOUND
  inline-heredoc  `cat > f <<EOF ...`; payload inline, BOUND
  git / other     not classified

Then, for the indirect class, it resolves each source path against the local filesystem
and reports how many are still readable. That number is the honest answer to "could an
auditor verify this approval today?" -- and it decays to zero, because /tmp does.

Reports the span scanned so no rate can be quoted without its denominator.

Usage:  python3 tools/approval_binds_pointer_not_payload.py [max_entries]
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 60000

_TOOL_PATH = re.compile(r"^(Edit|Write|MultiEdit|NotebookEdit)\s*->")
# A quoted or unquoted heredoc anywhere in the act: the payload travels inside the string.
_HEREDOC = re.compile(r"<<\s*\\?['\"]?\w+")
# A copying verb whose FIRST non-flag operand is the source it will read.
_COPY = re.compile(r"\b(?:cp|mv|install|rsync)\s+(?:-\S+\s+)*(\S+)")
_GIT = re.compile(r"\bgit\s+(?:apply|checkout|restore|commit)\b")


def classify(act: str | None) -> tuple[str, str | None]:
    """(class, source path if the act dereferences one)."""
    s = (act or "").strip()
    if not s:
        return "absent", None
    if s.startswith("*** Begin Patch"):
        return "inline-patch", None
    if _TOOL_PATH.match(s):
        return "tool-path-only", None
    if _HEREDOC.search(s):
        return "inline-heredoc", None
    m = _COPY.search(s)
    if m:
        return "indirect-copy", m.group(1)
    if _GIT.search(s):
        return "git", None
    return "other", None


def main() -> int:
    w = ChainWalker()
    scanned = 0
    first = last = None
    opened: dict[str, dict] = {}
    claimed: dict[str, dict] = {}
    for e in w.walk(max_entries=MAX):
        scanned += 1
        ts = e.get("timestamp")
        if first is None:
            first = ts
        last = ts
        et = e.get("eventType")
        if et == "gate_escalation_opened":
            p = payload(e)
            opened[p.get("escalation_id")] = p
        elif et == "gate_escalation_claimed":
            p = payload(e)
            claimed[p.get("escalation_id")] = p

    classes: Counter = Counter()
    per_seat: dict[str, Counter] = {}
    doors: Counter = Counter()
    truncated = 0
    fate: Counter = Counter()
    for eid, c in claimed.items():
        act = c.get("stated_attempted_act")
        cls, src = classify(act)
        classes[cls] += 1
        o = opened.get(eid) or {}
        per_seat.setdefault(o.get("plugin_id", "?"), Counter())[cls] += 1
        if cls != "indirect-copy":
            continue
        doors[o.get("opened_via")] += 1
        if (act or "").rstrip().endswith(("…", "...")):
            truncated += 1
        if src.startswith("$"):
            fate["source is an unexpanded shell variable"] += 1
        elif os.path.exists(src):
            fate["source still readable on this box"] += 1
        else:
            fate["source gone"] += 1

    total = sum(classes.values())
    print(f"span: {scanned} entries, {last} .. {first}")
    print(f"spent approvals (gate_escalation_claimed): {total}\n")
    bound = {"inline-patch", "inline-heredoc"}
    for k, v in classes.most_common():
        mark = "BOUND  " if k in bound else "unbound"
        print(f"  {mark} {k:16s} {v:4d}  {100*v/total:3.0f}%")
    nb = sum(v for k, v in classes.items() if k not in bound and k != "git")
    print(f"\n  payload NOT recoverable from the record: {nb}/{total} ({100*nb/total:.0f}%)")
    print("\nby seat:")
    for seat, cc in sorted(per_seat.items()):
        b = sum(v for k, v in cc.items() if k in bound)
        print(f"  {seat:12s} payload bound in {b}/{sum(cc.values())}  {dict(cc)}")
    ind = classes["indirect-copy"]
    if ind:
        print(f"\nindirect-copy detail (n={ind}):")
        print(f"  opened_via: {dict(doors)}   <- #929 calls this door 'recoverable'")
        print(f"  act preview visibly truncated (#627): {truncated}")
        for k, v in fate.most_common():
            print(f"  {k:42s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
