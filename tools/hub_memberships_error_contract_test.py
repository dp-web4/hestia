#!/usr/bin/env python3
"""Hub memberships card contract (#351 / PR #1558): a failed `/api/hub/memberships` read shows
the daemon's reason, not a bare "could not read hub list".

A corrupt stored hub list is refused with 424 and a body whose `error` names the vault key and the
break-glass step. The status card already rendered `d.error`; the memberships card dropped it, so
the one card that lists hubs hid the recovery step. Source-level, in the house idiom
(discover_pane_contract_test.py): the check names the construct it pins.

Run: python3 tools/hub_memberships_error_contract_test.py     (exit 1 on failure)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "core/src/server/dashboard/index.html").read_text()
FAILS: list[str] = []


def check(name: str, got, want=True) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def memberships_catch() -> str:
    a = UI.index("async function hubMemberships()")
    b = UI.index("const sup = d.supported", a)
    block = UI[a:b]
    return block[block.index("} catch (e) {"):]


def main() -> int:
    catch = memberships_catch()
    check("the catch renders the thrown reason (e.message)", "e.message" in catch)
    check("the reason is set as text, not HTML", "textContent" in catch)
    check("no bare fixed string with the reason dropped",
          "'<div class=\"empty\">could not read hub list</div>'" in catch, False)
    check("a non-ok response still throws d.error into the catch",
          "if (!r.ok) throw new Error(d.error" in UI[UI.index("async function hubMemberships()"):], True)
    for f in FAILS:
        print("FAIL", f)
    print(f"{'FAILED' if FAILS else 'ok'}: hub memberships error contract ({len(FAILS)} failures)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
