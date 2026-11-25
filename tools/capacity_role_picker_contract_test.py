#!/usr/bin/env python3
"""A seat's capacity role is a closed set, so the dashboard offers a picker -- and the picker's
list IS the law's list (agent-lifecycle PRD R5).

`HESTIA_ROLE` is what a seat connects AS. `reputation.rs::normalize_constellation_role` matches it
against exactly five strings and normalises anything else to `member`, the fail-closed floor. That
is right for the gate and invisible to the operator: `role:constellation:interactive_dev` (one
underscore) saves cleanly, renders as configured, and the seat is silently a `member`.

Pinned here:
  * the dashboard's CAPACITY_ROLES equals reputation.rs::KNOWN_CONSTELLATION_ROLES, in order --
    read from the Rust source, so a role added to the law without the picker goes red;
  * a stored value OUTSIDE the set is kept and labelled, never silently replaced -- opening a seat
    must not change it, and the operator must see that the daemon is not using it;
  * the seat to configure is PICKED, not typed (a typed seat id mints a seat file for a typo);
  * an agent's role view links to its seat.

Run: python3 tools/capacity_role_picker_contract_test.py     (exit 1 on failure)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "core/src/server/dashboard/index.html").read_text()
LAW = (ROOT / "core/src/reputation.rs").read_text()
FAILS: list[str] = []


def check(name: str, got, want=True) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def law_roles() -> list[str]:
    m = re.search(r"pub const KNOWN_CONSTELLATION_ROLES: &\[&str\] = &\[(.*?)\];", LAW, re.S)
    return re.findall(r'"([^"]+)"', m.group(1)) if m else []


def pure_block() -> str:
    a = UI.index("  const CAPACITY_ROLES = [")
    return UI[a:UI.index("  function cfgValueCell(r) {", a)]


def run(expr: str, arg) -> object:
    prog = pure_block() + f"\nconst A = JSON.parse(process.argv[1]); process.stdout.write(JSON.stringify({expr}));"
    r = subprocess.run(["node", "-e", prog, json.dumps(arg)], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        FAILS.append(f"node failed: {r.stderr.strip()[-300:]}")
        return None
    return json.loads(r.stdout)


def source_contract() -> None:
    law = law_roles()
    check("the law's role list was found in reputation.rs", len(law) >= 5)
    ui = re.findall(r"'(role:constellation:[a-z-]+)'", pure_block().split("];", 1)[0])
    check("the picker's list IS the law's list, in order", ui, law)
    check("the seat to configure is picked, not typed",
          '<select class="pol-input member-pick" id="cfg-new-id"' in UI and '<input class="pol-input" id="cfg-new-id"' not in UI)
    check("an agent's role view links to its seat", 'data-open-seat="${escapeHtml(selectedOrch)}"' in UI)
    check("opening a seat from an agent loads the seat list first",
          bool(re.search(r"async function openSeatFor\(member\) \{.*?await cfgLoadList\(\);.*?cfgOpen\(member,", UI, re.S)))
    check("HESTIA_ROLE rows render the picker; other rows stay free text",
          "if (String(r.key).trim() !== 'HESTIA_ROLE')" in UI)


def behaviour() -> None:
    law = law_roles()
    opts = run("capacityRoleOptions(A)", "role:constellation:reviewer") or []
    check("a known role: exactly the law's five, that one selected",
          ([o["value"] for o in opts], [o["value"] for o in opts if o["selected"]]), (law, ["role:constellation:reviewer"]))

    typo = "role:constellation:interactive_dev"
    opts = run("capacityRoleOptions(A)", typo) or []
    check("an UNKNOWN stored value is kept, first and selected -- opening a seat must not change it",
          (opts[0]["value"], opts[0]["selected"], len(opts)) if opts else None, (typo, True, 6))
    check("...and says what the daemon actually does with it", 'treats this seat as "member"' in (opts[0]["label"] if opts else ""))
    check("...and nothing else is selected", sum(o["selected"] for o in opts), 1)

    for empty in ("", None):
        opts = run("capacityRoleOptions(A)", empty) or []
        check(f"no value ({empty!r}): a placeholder, not a silently chosen role",
              (opts[0]["value"], opts[0]["selected"], sum(o["selected"] for o in opts)) if opts else None, ("", True, 1))
    approval_behaviour()


def cfg_save_behavior(data):
    start = UI.index("  async function cfgSave() {")
    end = UI.index("  // From an agent to its seat.", start)
    block = UI[start:end]
    js = """
const sent = [], confirms = [];
const data = DATA;
let cfgRows = data.previous ? [{ key: 'HESTIA_ROLE', value: data.previous }] : [];
const cfgStored = { role: data.previous || '', note: data.stored_note || '' };
// as the real one does: the draft REPLACES cfgRows, so cfgRows no longer holds the stored role
const cfgReadRows = () => (cfgRows = data.next ? [{ key: 'HESTIA_ROLE', value: data.next }] : []);
const cfgSelected = 'claude-code';
const confirm = message => { confirms.push(message); return data.ack !== false; };
const els = {};
const $ = id => els[id] || (els[id] = {
  value: id === 'cfg-note' ? (data.note || '') : '', hidden: true,
  textContent: '', innerHTML: '', disabled: false,
});
const cfgEsc = String;
const apiFetch = async (path, options) => {
  sent.push({ path, body: JSON.parse(options.body) });
  return { ok: true, json: async () => ({ member: 'claude-code', artifact: '/tmp/x',
    intentEntryHash: 'abcdef', verdict: [] }) };
};
const cfgOpen = async () => {};
const cfgLoadList = async () => {};
BLOCK
(async () => {
  await cfgSave();
  console.log(JSON.stringify({ sent, confirms, err: $('cfg-err').textContent }));
})();
""".replace("DATA", json.dumps(data)).replace("BLOCK", block)
    result = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        FAILS.append(f"cfgSave node failed: {result.stderr.strip()[-500:]}")
        return {}
    return json.loads(result.stdout)


def approval_behaviour() -> None:
    cancelled = cfg_save_behavior({"previous": "member", "next": "reviewer", "ack": False})
    check("a role change is confirmed before any save",
          cancelled["confirms"] and cancelled["sent"] == [])
    missing = cfg_save_behavior({"previous": "member", "next": "reviewer"})
    check("a role change without a reason never reaches the daemon",
          missing["sent"] == [] and "reason (note) is required" in missing["err"])
    approved = cfg_save_behavior({"previous": "member", "next": "reviewer", "note": "review duty"})
    check("a reasoned role change sends the note as its auditable reason",
          approved["sent"] and approved["sent"][0]["body"]["config"]["note"] == "review duty")
    stale = cfg_save_behavior({"previous": "member", "next": "reviewer",
                               "note": "initial setup", "stored_note": "initial setup"})
    check("the stored note (the editor opens with it) is not a reason for a new role change",
          stale["sent"] == [] and "reason (note) is required" in stale["err"])
    unchanged = cfg_save_behavior({"previous": "member", "next": "member"})
    check("a no-op role save does not manufacture an acknowledgement",
          unchanged["confirms"] == [] and bool(unchanged["sent"]))


def test_capacity_role_picker_contract() -> None:
    """pytest's entry: the same checks, and a failure it can see."""
    FAILS.clear()
    source_contract()
    if shutil.which("node"):
        behaviour()
    assert not FAILS, "\n".join(FAILS)


def main() -> int:
    try:
        test_capacity_role_picker_contract()
    except AssertionError:
        pass
    if not shutil.which("node"):
        print("SKIPPED: behaviour -- no node on PATH (the source contract above still ran)")
    for f in FAILS:
        print("FAIL", f)
    print(f"capacity role picker contract: {'FAIL' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
