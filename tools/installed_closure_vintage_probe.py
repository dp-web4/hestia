#!/usr/bin/env python3
"""Report which engine this seat's registered hook actually loads, and whether it matches.

Host-state reporting only: reads, hashes, prints. Mutates nothing.

The thing worth measuring is not the shim. Every seat's shim is thin; the engine it
imports is what decides. A seat can carry a current shim over a months-old engine and
every surface that inspects "the hook" reports it healthy. Measured on CBP 2026-08-25:
the shims were current while the engine in use was dated 2026-08-14 and 10.6 KB smaller
than the tracked copy.

WHY THIS FILE WAS REWRITTEN (2026-08-25). The previous version's own docstring claimed it
resolved locations "from the shim's own location at runtime, never from a literal spelled
here" -- and then spelled three: a parents[2] sibling walk (the pre-#590 per-vendor
topology), a codex path carrying a segment the real shim does not have, and a kimi seat
directory under the wrong name. After #590 moved the fleet to one engine under
$HESTIA_HOME, all three were stale, and the two seat paths had never been right.

gpt caught it blocking a branch-rescue that would have reinstated this file verbatim. A
measurement instrument that reports confidently from locations nothing uses is worse than
an absent one, because its "not found" reads as a finding.

The repair is to stop guessing. The member installer writes an authoritative record of
what it installed and where -- every shim path and every engine path, each with a sha256.
This reads THAT. It cannot drift from the installed topology because it holds no opinion
about the topology: if a future layout change moves everything again, this file needs no
edit and cannot silently measure the wrong place.

Exit status is a verdict, not an error:
  0  every recorded file matches what the ledger recorded
  1  something differs -- read the report
  2  could not determine (no ledger, or nothing recorded in it)
"""

from __future__ import annotations

import hashlib
import json
import sys
from os import environ
from pathlib import Path


def ledger_path() -> Path:
    """The install record. Same resolution the daemon uses."""
    explicit = environ.get("HESTIA_CURRENT_BUILD_FILE")
    if explicit:
        return Path(explicit)
    home = environ.get("HESTIA_HOME") or str(Path.home() / ".hestia")
    return Path(home) / "current-build.json"


def digest(path: Path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def check(entries, label: str):
    """Report one recorded group. Returns (checked, mismatched)."""
    checked = mismatched = 0
    for e in entries:
        p = Path(e["path"])
        checked += 1
        actual = digest(p)
        if actual is None:
            print(f"  {label:<8} {e['file']:<34} MISSING on disk  {p}")
            mismatched += 1
        elif actual != e.get("sha256"):
            print(f"  {label:<8} {e['file']:<34} DIFFERS from the ledger")
            print(f"           recorded {str(e.get('sha256'))[:16]}  actual {actual[:16]}")
            mismatched += 1
        else:
            print(f"  {label:<8} {e['file']:<34} matches")
    return checked, mismatched


def main() -> int:
    lp = ledger_path()
    try:
        ledger = json.loads(lp.read_text())
    except Exception as exc:  # noqa: BLE001 - any unreadable ledger is the same verdict
        print(f"cannot determine: no usable install ledger at {lp} ({exc})", file=sys.stderr)
        return 2

    print(f"install ledger : {lp}")
    print(f"  build_id     : {ledger.get('build_id')}")
    print(f"  installed at : {ledger.get('installed_at_iso')}")
    print()

    total = bad = 0
    # The engine first: it is the thing that decides, and the thing that was stale.
    engine = ledger.get("shared_engine") or []
    if engine:
        c, m = check(engine, "engine")
        total += c
        bad += m
    else:
        print("  engine   (not recorded by this ledger -- pre-#583 installer)")

    for member in ledger.get("members", []):
        c, m = check(member.get("files", []), str(member.get("member", "?"))[:8])
        total += c
        bad += m

    print()
    if not total:
        print("cannot determine: the ledger records no files", file=sys.stderr)
        return 2
    print(f"{total} recorded file(s), {bad} not matching what was installed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
