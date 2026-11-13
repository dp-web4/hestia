#!/usr/bin/env python3
"""#540: every escalation census imports one terminal and attempt vocabulary."""
from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import chain_walk  # noqa: E402
import factor_attribution_census as factor  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILS.append(name)


def load_grounds():
    spec = importlib.util.spec_from_file_location("grounds_outcomes_test", HERE / "grounds_vs_acts.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_retired_without_a_daemon():
    class EmptyWalker:
        def walk(self, max_entries):
            return iter(())

    with patch.object(chain_walk, "ChainWalker", EmptyWalker), patch.object(sys, "argv", ["retired"]):
        return runpy.run_path(str(HERE / "retired_before_review.py"))


def main():
    expected_terminal = {
        "gate_escalation_decided",
        "gate_escalation_expired",
        "gate_escalation_withdrawn",
    }
    check("terminal is decided, expired or withdrawn",
          set(chain_walk.ESCALATION_TERMINAL_EVENTS) == expected_terminal,
          chain_walk.ESCALATION_TERMINAL_EVENTS)
    check("corroborated and claimed are not terminal",
          not {"gate_escalation_corroborated", "gate_escalation_claimed"}
          & set(chain_walk.ESCALATION_TERMINAL_EVENTS))
    check("the ask denominator is opened UNION refused",
          set(chain_walk.ESCALATION_ATTEMPT_EVENTS)
          == {"gate_escalation_opened", "gate_escalation_refused"},
          chain_walk.ESCALATION_ATTEMPT_EVENTS)
    check("factor attribution imports the one terminal set",
          factor.TERMINAL is chain_walk.ESCALATION_TERMINAL_EVENTS)
    grounds = load_grounds()
    check("grounds-vs-acts imports the one terminal set",
          grounds.TERMINAL_EVENTS is chain_walk.ESCALATION_TERMINAL_EVENTS)
    retired = load_retired_without_a_daemon()
    check("retired-before-review imports the one terminal set",
          retired["TERMINAL"] is chain_walk.ESCALATION_TERMINAL_EVENTS)
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {FAILS}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
