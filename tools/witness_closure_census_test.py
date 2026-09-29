#!/usr/bin/env python3
"""tools/witness_closure_census.py counts what the finding counted, and its gate can fail.

Fixture rows mirror the sink's real shape (subject_lct / action_id / reason / timestamp)."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("wcc", HERE / "witness_closure_census.py")
wcc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wcc)

FAILURES: list[str] = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILURES.append(name)


def row(subj, aid, reason, ts):
    return json.dumps({"subject_lct": subj, "action_id": aid, "reason": reason, "timestamp": ts,
                       "action_type": "tool_execution", "t3_delta": {}})


A, B = "lct:web4:member:aaa", "lct:web4:member:bbb"
ROWS = [
    row(A, "a1", "gate:warn [x] reason", "2026-09-08T10:00:00Z"),
    row(A, "a1", "outcome:success", "2026-09-08T10:00:01Z"),
    row(A, "a2", "gate:warn", "2026-09-08T23:59:59Z"),
    row(A, "a2", "outcome:failure", "2026-09-09T00:00:02Z"),     # closed across the window edge
    row(A, "a0", "gate:warn", "2026-09-01T00:00:00Z"),           # before the window
    row(B, "b1", "gate:warn", "2026-09-08T10:00:00Z"),
    row(B, "cold-1", "outcome:success", "2026-09-08T10:00:01Z"),  # an outcome on ANOTHER id: cold
    row(B, "b2", "gate:deny", "2026-09-08T10:00:00Z"),            # a deny never executes
    "{not json",
    json.dumps(["not", "a", "row"]),
]


def main() -> int:
    res = wcc.census(ROWS, since="2026-09-07", until="2026-09-09")
    check("closed counts same-id outcomes, across the window edge",
          res[A]["warned"] == 2 and res[A]["closed"] == 2, json.dumps(res[A]))
    check("a warn before the window is not counted", "a0" not in res[A]["unclosed_sample"])
    check("an outcome under a DIFFERENT id does not close the warn (the cold-record defect)",
          res[B]["warned"] == 1 and res[B]["closed"] == 0 and res[B]["unclosed_sample"] == ["b1"],
          json.dumps(res[B]))
    check("a deny is not in the sample", res[B]["warned"] == 1)
    check("malformed rows are skipped, not fatal", True)
    with tempfile.TemporaryDirectory() as d:
        sink = Path(d) / "deltas.jsonl"
        sink.write_text("\n".join(ROWS) + "\n")
        rc = wcc.main(["--sink", str(sink), "--since", "2026-09-07", "--min-rate", "0.95",
                       "--min-warns", "1", "--label", f"{B}=kimi-code"])
        check("the gate FAILS when a member with enough warns is below the rate", rc == 1, rc)
        rc = wcc.main(["--sink", str(sink), "--since", "2026-09-07", "--min-rate", "0.95",
                       "--min-warns", "5"])
        check("a thin sample is not a verdict", rc == 0, rc)
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
