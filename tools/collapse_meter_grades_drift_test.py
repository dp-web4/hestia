#!/usr/bin/env python3
"""The verbatim/divergent grade must move when the source moves.

`gate_collapse_meter.py` pins DIVERGENT forks tightly (4) and VERBATIM forks loosely,
because a character-for-character copy cannot answer a question two ways. That split is
only safe if the grade is *earned on every run*: the moment someone edits a verbatim copy
it has to re-grade as DIVERGENT and blow the tight pin. A grade that sticks to a name --
or that anything can assert about itself -- would turn the loose pin into a place to hide
a second law.

So this pins the polarity in both directions on synthetic modules. It deliberately does NOT
mutate a real seat gate to test the same thing: writing to `plugins/*/hooks/` is refused by
the gate self-access rule, correctly, and the predicate is what carries the risk anyway.

The end-to-end wiring is pinned by the live tree, where both grades occur at once: gemini
carries 4 divergent scope predicates (independently confirmed by
`scope_fork_differential_test.py`, which finds 6 inputs they answer differently) while
claude-code's 16 shell-classifier copies grade verbatim.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _meter():
    spec = importlib.util.spec_from_file_location(
        "gate_collapse_meter_under_test", ROOT / "tools" / "gate_collapse_meter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ORIGINAL = '''
def _is_read_only(tool, ti):
    cmd = ti.get("command", "")
    return cmd.startswith("grep")
'''

REINDENTED = '''
def _is_read_only(tool, ti):
        cmd = ti.get("command", "")
        return cmd.startswith("grep")
'''

DRIFTED = '''
def _is_read_only(tool, ti):
    cmd = ti.get("command", "")
    return cmd.startswith("grep") or cmd.startswith("rm")
'''


def main() -> int:
    m = _meter()
    failures = []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        shared = td / "shared_mod.py"
        shared.write_text(ORIGINAL)
        shared_fns, _ = m.module_functions(shared)
        shared_sources = {f["name"]: f["source"] for f in shared_fns}

        cases = [
            ("identical copy", ORIGINAL, True),
            ("one changed predicate", DRIFTED, False),
            ("reindented only", REINDENTED, False),
        ]
        for label, body, expected in cases:
            seat = td / "seat_mod.py"
            seat.write_text(body)
            fns, _ = m.module_functions(seat)
            fn = next(f for f in fns if f["name"] == "_is_read_only")
            got = m.is_verbatim(fn, shared_sources)
            ok = got is expected
            print(f"{'ok  ' if ok else 'FAIL'}: {label:<24} verbatim={got} expected={expected}")
            if not ok:
                failures.append(label)

        # A name the shared engine does not own is never verbatim, whatever its text.
        got = m.is_verbatim({"name": "_unowned", "source": ORIGINAL}, shared_sources)
        ok = got is False
        print(f"{'ok  ' if ok else 'FAIL'}: {'name not owned by shared':<24} verbatim={got} expected=False")
        if not ok:
            failures.append("name not owned by shared")

    if failures:
        print(f"FAIL: {len(failures)} grade(s) wrong: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("ok: the grade is recomputed from source and moves in both directions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
