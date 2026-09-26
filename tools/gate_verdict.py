#!/usr/bin/env python3
"""Has the daemon judged THESE gate bytes, and what did it say?

The reader for `$HESTIA_HOME/status/gate-integrity.json`, which the daemon writes on every
integrity pass (core/src/server/gate_watch.rs: at startup, then on the maintenance tick).
dp, 2026-09-21, option 1 on #1085: the daemon verifies its own gates; the installer reads.

THE VERDICT IS BOUND TO BYTES, NOT TO TIME. The status file lists the SHA-256 the daemon
found for each gate. A verdict applies only if every listed gate still hashes to what the
daemon judged: then it is a verdict about exactly the bytes on disk, however long ago it was
made. If any gate changed since, the daemon has not looked at these bytes yet, and the answer
is PENDING — never the stale verdict about bytes that are gone.

WHAT THIS CANNOT SEE. The file is a readable projection, not the authority: anyone who can
write HESTIA_HOME can edit it, exactly as they can edit a gate. Each finding names the chain
row that opened it, so the claim can be checked against the witness chain. And a gate wired
AFTER the daemon's last pass is not in the file at all; the next pass will add it.

Exit codes: 0 VERIFIED, 2 PENDING (not judged yet), 3 FINDINGS/MODIFIED, 4 UNKNOWN
(the daemon could not establish the gate set), 5 NO STATUS (no file: an older daemon, or one
that has not started).

Usage:
    gate_verdict.py --home "$HESTIA_HOME" [--wait SECONDS] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

STATUS_FILE = "status/gate-integrity.json"   # gate_watch::STATUS_FILE
EXIT = {"VERIFIED": 0, "PENDING": 2, "FINDINGS": 3, "MODIFIED": 3, "UNKNOWN": 4, "NO_STATUS": 5}


def _sha256(path: str) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def assess(home: Path) -> dict:
    """One reading. Returns {"verdict", "reason", "checked_at", "gates": [...]}."""
    path = home / STATUS_FILE
    try:
        doc = json.loads(path.read_text())
    except FileNotFoundError:
        return {"verdict": "NO_STATUS", "reason": f"{path} does not exist — the daemon predates "
                "gate_watch, or has not run a pass since it started", "gates": []}
    except (OSError, json.JSONDecodeError) as e:
        return {"verdict": "NO_STATUS", "reason": f"{path} is unreadable: {e}", "gates": []}

    gates = doc.get("gates") or []
    stale = []
    for g in gates:
        judged = g.get("found_sha256")
        if not judged or g.get("gate", "").startswith("("):
            continue   # missing/unreadable/coverage rows judged no bytes; nothing to compare
        now = _sha256(g["gate"])
        if now != judged:
            stale.append({"gate": g["gate"], "judged": judged, "on_disk": now})
    if stale:
        return {"verdict": "PENDING", "checked_at": doc.get("checked_at"), "gates": gates,
                "stale": stale,
                "reason": f"{len(stale)} gate(s) changed since the daemon's last pass; it has "
                          "not judged these bytes yet (passes run at startup and on the "
                          "maintenance tick)"}
    status = doc.get("status", "UNKNOWN")
    if doc.get("witness_failures"):
        # The pass ran but its chain rows did not all land; the file must not read as witnessed.
        return {"verdict": status, "checked_at": doc.get("checked_at"), "gates": gates,
                "reason": f"{doc['witness_failures']} chain row(s) from that pass did NOT land"}
    return {"verdict": status if status in EXIT else "UNKNOWN", "checked_at": doc.get("checked_at"),
            "gates": gates, "reason": ""}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--home", required=True, help="HESTIA_HOME (no default: never guess whose)")
    ap.add_argument("--wait", type=int, default=0,
                    help="seconds to keep re-reading while PENDING or NO_STATUS")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    deadline = time.monotonic() + max(0, a.wait)
    while True:
        r = assess(Path(a.home))
        if r["verdict"] not in ("PENDING", "NO_STATUS") or time.monotonic() >= deadline:
            break
        time.sleep(5)
    if a.json:
        print(json.dumps(r, indent=2))
    else:
        print(f"gate integrity: {r['verdict']}" + (f" — {r['reason']}" if r.get("reason") else ""))
        for g in r.get("gates", []):
            if g.get("status") != "verified":
                row = g.get("open_finding_chain_hash")
                print(f"  {g.get('status'):<11} {g.get('gate')}" + (f"  (chain {row[:16]})" if row else ""))
    return EXIT.get(r["verdict"], 4)


if __name__ == "__main__":
    sys.exit(main())
