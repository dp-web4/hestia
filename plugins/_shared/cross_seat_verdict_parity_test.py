#!/usr/bin/env python3
"""Cross-seat VERDICT parity — do the seats reach the same answer by the same process?

The sibling `cross_harness_closure_test.py` proves the three shims are WIRED to one
closure module, and it passes. This file asks the next question, and the answer is no:
given a governance marker hit, the seats do NOT classify the same command the same way.

`hestia_shell_classifier` (`_READ_ONLY_HEADS`, `_is_read_only`) is imported by the
claude-code shim ALONE — it appears in no shared module and in no other seat's hook. At
the gate-self-access decision (the `_self_hit` branch of the claude-code shim),
claude-code decides read-vs-write with that private classifier; kimi and codex decide it
with the shared closure's own classification. Measured 2026-09-04, the two disagree on
4 of 8 cases, in BOTH directions:

  * claude-code is MORE PERMISSIVE where its corpus fixed a false positive (FP12's
    control-flow strip: `for`, `if`). Those fixes live in the private classifier, so no
    other seat has them.
  * claude-code is MORE RESTRICTIVE on the false positives its corpus has not yet fixed
    (FP15 awk pipe, FP17 command substitution — pinned open in the claude-code
    false-refusal corpus). The shared closure permits both, so kimi and codex are not
    subject to them.

Consequence, stated plainly: a refusal is not a property of the act. It is a property of
the act AND the seat. The same command, the same governance path, the same daemon state,
yields "allowed and witnessed" on one seat and "refused and escalated" on another. That
makes cross-seat corroboration of a gate verdict unsound — the peer is not re-running
your experiment, it is running a different one — and it means the false-refusal corpus
measures one seat's experience while reading as the fleet's.

PINNED, NOT EXPECTED-TO-FAIL. This follows the corpus idiom in
`plugins/claude-code/tests/gate_false_refusal_test.py`: a test that asserts a defect
EXISTS is green while the defect is open and goes RED the day it closes. Every row below
declares the verdict each side reaches TODAY, and the test fails if either side moves:

  * a divergent row flipping to agreement  -> RED. Good news. Delete the row (and the
    second test) and say so in the commit; the pin retires itself.
  * an agreeing control flipping to differ -> RED. Bad news, and the loudest possible
    signal: the seats have drifted somewhere new.

An earlier draft of this file asserted the opposite sign — fail-while-broken — which
would have shipped a permanently red job. CI runs this from the repo root under bare
python3 (tools/ci_discovery.py `bare`), so a file here that cannot go green cannot land.

Every gate path here is built with os.path.join and never spelled contiguously — the same
FP8 constraint the false-refusal corpus documents for its own source.

Paths (env-overridable, defaults resolve in-repo relative to this file):
  HGC_PLUGINS — dir holding the per-seat plugin dirs
  HGC_SHARED  — dir holding the shared modules

Run:  python3 cross_seat_verdict_parity_test.py
"""
import importlib.util
import os
import sys

_HOOK = "pre_" + "tool_" + "use.py"   # named as data (two parts), never a write destination

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.getenv("HGC_PLUGINS") or os.path.dirname(HERE)
SHARED = os.getenv("HGC_SHARED") or HERE

# Reviewed fixture, not a runtime authority fallback — the same note the sibling
# cross-harness test carries. #742/#747 make the seats resolve governing modules only from
# an explicit HESTIA_SHARED_DIR or an installed $HESTIA_HOME/shared; this names the exact
# shared tree under test rather than depending on ambient sys.path.
if not os.getenv("HESTIA_SHARED_DIR"):
    os.putenv("HESTIA_SHARED_DIR", SHARED)
    os.environ["HESTIA_SHARED_DIR"] = SHARED
sys.path.insert(0, SHARED)
import hestia_governance_closure as GC  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CLAUDE_HOOK = os.path.join(PLUGINS, "claude-code", "hooks", _HOOK)
CLAUDE = _load("_seat_claude", CLAUDE_HOOK)

G = CLAUDE_HOOK   # a real governance marker path, used only as command TEXT


def _claude(cmd):
    """The verdict the claude-code seat reaches at its gate-self-access branch."""
    return "read" if CLAUDE._is_read_only("Bash", {"command": cmd}) else "write"


def _peer(cmd):
    """The verdict a seat with no private classifier reaches — kimi and codex."""
    v = GC.classify("Bash", {"command": cmd})
    return str(getattr(v, "classification", v)).lower()


# (name, command, claude_verdict, peer_verdict, why)
# The two verdict columns are the PIN: they are what was measured on 2026-09-04, and any
# movement on either side turns this file red.
CASES = [
    ("plain_read", f"grep -c def {G}", "read", "read",
     "control: a bare read must agree or nothing below is evidence"),
    ("real_write_control", f"sed -i s/a/b/ {G}", "write", "write",
     "control: a real write must agree, or a seat denying everything greens for free"),
    ("sed_range_print", f"sed -n '1,5p' {G}", "read", "read",
     "corpus _FALSE_REFUSALS row; agrees today"),
    ("assignment_prefix", f"G={G}; grep -c def \"$G\"", "read", "read",
     "FP13's fix; agrees today"),
    ("for_loop_read", f"for f in a b; do grep -c def {G}; done", "read", "write",
     "FP12's fix, claude-code ONLY — the peer path never got the control-flow strip"),
    ("if_then_read", f"if grep -q def {G}; then echo y; fi", "read", "write",
     "FP12's fix, second construct; same divergence"),
    ("awk_pipe", f"ls -la {G} | awk '{{print $1}}'", "write", "read",
     "FP15, pinned OPEN on claude-code — not a defect on the peers, which permit it"),
    ("substitution_read", f"n=$(grep -c def {G}); echo $n", "write", "read",
     "FP17, pinned OPEN on claude-code — peers permit it; three escalations 2026-09-03"),
]


def test_seat_verdicts_match_the_pin():
    """Green while the seats disagree exactly as recorded; red the moment either moves."""
    moved = []
    for name, cmd, want_c, want_p, why in CASES:
        got_c, got_p = _claude(cmd), _peer(cmd)
        if (got_c, got_p) != (want_c, want_p):
            moved.append((name, want_c, want_p, got_c, got_p, why))
    assert not moved, "seat classification moved away from the pin:\n" + "\n".join(
        f"  {n}: pinned claude={wc}/peers={wp}, now claude={gc}/peers={gp}\n      {w}"
        for n, wc, wp, gc, gp, w in moved)


def test_the_divergence_is_still_real():
    """The headline claim, asserted directly: some rows still differ by seat.

    Separate from the row-by-row pin on purpose. That one goes red on ANY movement,
    including movement that makes things worse. This one goes red only on the GOOD
    outcome — the seats agreeing — so the commit that closes the defect is forced to
    delete a test whose name says what was achieved.
    """
    differ = {n for n, _, wc, wp, _ in CASES if wc != wp}
    assert differ, "no divergent rows left; if the seats share one classifier, delete this test"
    for name, cmd, _, _, _ in CASES:
        if name in differ:
            assert _claude(cmd) != _peer(cmd), (
                f"{name} now AGREES across seats. If the seats were unified, delete this "
                f"test and the row; do not re-pin it.")


def main():
    print("cross-seat verdict parity — claude-code private classifier vs shared closure")
    print(f"  claude shim : {CLAUDE_HOOK}")
    print(f"  shared      : {SHARED}\n")
    width = max(len(n) for n, _, _, _, _ in CASES)
    rc = 0
    for name, cmd, want_c, want_p, _ in CASES:
        got_c, got_p = _claude(cmd), _peer(cmd)
        pinned = "DIFF" if want_c != want_p else "same"
        mark = "ok   " if (got_c, got_p) == (want_c, want_p) else "MOVED"
        print(f"  {mark} {pinned}  {name:<{width}}  claude={got_c:<5} peers={got_p:<5}")
    print()
    for t in (test_seat_verdicts_match_the_pin, test_the_divergence_is_still_real):
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            rc = 1
            print(f"  FAIL  {t.__name__}\n{e}")
    print()
    if rc:
        print("RED — a seat's classification moved. Read the failure above: agreement is "
              "the good outcome and retires the pin; new divergence is drift.")
        return rc
    n_diff = sum(1 for _, _, wc, wp, _ in CASES if wc != wp)
    print(f"OK — pin holds: {n_diff}/{len(CASES)} identical commands still get different "
          f"verdicts by seat. A refusal is a property of the act AND the seat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
