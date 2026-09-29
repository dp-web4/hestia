#!/usr/bin/env python3
"""The extraction-domain ratchet must fire in BOTH directions, and fail closed.

A guard is a claim until it has been fired. This pins three things about
`gate_collapse_meter.py --min-agreed-keys`:

  1. at the measured floor it passes,
  2. one above the measured floor it FAILS -- without this arm the guard could be
     a dead bool that returns 0 on every input and nobody would notice,
  3. when the domain cannot be measured at all it fails CLOSED, because the whole
     point of the line is that the collapse percentage stops being quotable on its
     own. A ratchet that silently skips when its probe breaks is worse than absent:
     it reports green for a number it never computed.
"""
from __future__ import annotations

import io
import sys
import types
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gate_collapse_meter as meter  # noqa: E402
from path_key_vocabulary_probe import gate_key_vocabularies  # noqa: E402


def run(argv):
    """Run the meter with argv, returning (rc, stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    saved = sys.argv
    sys.argv = ["gate_collapse_meter.py"] + argv
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = meter.main()
    finally:
        sys.argv = saved
    return rc, out.getvalue() + err.getvalue()


def main() -> int:
    root = meter.repo_root(Path(__file__).resolve())
    vocab = gate_key_vocabularies(root)
    per_seat = {s: d["keys"] for s, d in vocab.items()}
    agreed = len(set.intersection(*per_seat.values()))
    union = len(set().union(*per_seat.values()))
    failures = []

    # The floor is derived from the tree, never written down here. A test that
    # restated the number would pass against a meter that had stopped measuring.
    rc, text = run(["--quiet", f"--min-agreed-keys={agreed}"])
    if rc != 0:
        failures.append(f"at the measured floor {agreed} the ratchet failed (rc={rc})")
    if f"ratchet key-agree: {agreed} of {union}" not in text:
        failures.append("the compared value is not printed; a threshold guard that shows "
                        "only its verdict cannot be seen drifting toward the limit")

    # The arm that proves the guard is alive.
    rc, text = run(["--quiet", f"--min-agreed-keys={agreed + 1}"])
    if rc == 0:
        failures.append(f"floor {agreed + 1} is above the measured {agreed} and the ratchet "
                        f"still passed -- the guard is inert")
    if "::error::extraction domain diverged" not in text:
        failures.append("failing arm produced no ::error:: annotation")

    # Fail-closed: the probe raises, so the number does not exist.
    stub = types.ModuleType("path_key_vocabulary_probe")

    def boom(_root):
        raise RuntimeError("simulated probe failure")

    stub.gate_key_vocabularies = boom
    saved_mod = sys.modules.get("path_key_vocabulary_probe")
    sys.modules["path_key_vocabulary_probe"] = stub
    try:
        rc, text = run(["--quiet", f"--min-agreed-keys={agreed}"])
    finally:
        if saved_mod is not None:
            sys.modules["path_key_vocabulary_probe"] = saved_mod
        else:
            del sys.modules["path_key_vocabulary_probe"]
    if rc == 0:
        failures.append("an unmeasurable extraction domain passed the ratchet; "
                        "unmeasurable must fail closed")
    if "EXTRACTION DOMAIN: cannot determine" not in text:
        failures.append("the unmeasurable case is silent; it must say so on stdout")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print(f"ok: extraction-domain ratchet fires both ways and fails closed "
          f"(measured {agreed} of {union} agreed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
