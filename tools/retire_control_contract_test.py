#!/usr/bin/env python3
"""The retire control (agent-lifecycle R1): reachable, guarded, reversible, and never a delete.

dp, 2026-09-08, restated 09-19 and 09-21: the trust list carries `claude-code` (5,415 acts),
`Claude-code` (0) and `caude-code` (0) as three agents, *"that i don't see a way of managing."*
Aliasing folds their evidence and leaves them as parties; retiring is the act that stops them
being parties. It is the only control on this screen that removes authority, so what is pinned
here is mostly the ways it must refuse to be easy:

  * reason AND evidence pointer required before anything is sent;
  * a member that has ACTED recently comes back 409 and is only sent again after the operator
    confirms, with the act count shown — the three ids differ by one character and the live one
    is the seat the operator is typing from;
  * a retired id is HIDDEN, not dropped; `show retired` reveals it; and a retired id that is
    still acting stays visible regardless, because hiding a live agent is the dangerous
    direction;
  * reinstate exists, and it must NOT restore the revoked grants.

The pure filter is lifted out and run under node. The rest is pinned at source, in the house
idiom: a control that removes authority is checked for what it must not contain.

Run: python3 tools/retire_control_contract_test.py     (exit 1 on failure)
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
RS = (ROOT / "core/src/server/http.rs").read_text()
RETIREMENT = (ROOT / "core/src/server/retirement.rs").read_text()
FAILS: list[str] = []


def check(name: str, got, want=True) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def block() -> str:
    a = UI.index("  let showRetired = false;")
    return UI[a:UI.index("  const LOOKALIKE_MIN_LEN", a)]


def source_contract() -> None:
    blk = block()
    check("both halves of the account are required before anything is sent",
          blk.count("if (!reason) return;") == 2 and "if (!ref) return;" in blk)
    # Line-based, not a regex over the whole block: the confirm's own message contains ")"
    # characters ("act(s)"), which defeated the first pattern -- and a pattern that cannot match
    # is a check that cannot fail.
    lines = blk.splitlines()
    resend = [i for i, l in enumerate(lines) if "= await send(true)" in l]
    check("the confirmed re-send happens exactly once", len(resend), 1)
    guarded = resend and "if (!confirm(" in lines[resend[0] - 1] and "return;" in lines[resend[0] - 1]
    check("...and only on the line after an explicit confirm that returns on refusal", bool(guarded))
    check("the confirm names the act count, which is what identifies the live id",
          "out.acts_recently" in blk and "acts_recently}" in blk)
    check("confirm_active is never sent on the first attempt", "send(false)" in blk)
    check("reinstate says the grants are not restored", "NOT restored" in blk)
    check("the control says it is not a delete", "Not deletion" in blk)
    # It must not offer to delete anything, here or anywhere near it.
    for verb in ("'DELETE'", '"DELETE"'):
        check(f"no {verb} in the retire block", verb in blk, False)

    # The daemon's half, pinned where the claim lives.
    check("the route refuses without reason and ref",
          "reason and ref are required" in RS)
    # PIN THE USE, NOT THE DECLARATION. The first cut of these two pinned the constant and the
    # response literal, both of which survive the sabotage that matters: pointing the scan at
    # every event type again, and removing the retired lookup. Both slipped through green. The
    # Rust tests catch them either way (`retiring_a_phantom_...`); these now at least point at
    # the lines that decide.
    check("the guard's scan is RESTRICTED to the agent's own act types",
          "scan_recent(Some(cutoff), Some(AGENT_ACT_EVENTS), 50_000" in RS)
    check("...and the types are the ones the operator's own act count is built from",
          'const AGENT_ACT_EVENTS: &[&str] = &["policy_decision", "outcome"];' in RS)
    check("the grant route actually looks the id up in the retired store",
          "if let Some(r) = s.retired_members.get(&plugin_id).cloned() {" in RS)
    check("...and register_new_member does not escape that refusal",
          RS.index("was RETIRED on this seat") < RS.index("let member_known ="))
    check("retirement is witnessed intent-then-commit",
          '"member_retire_intent"' in RS and '"member_retired"' in RS)
    check("the per-seat scope is stated in the record itself", "this seat only" in RS)
    check("the module says what retirement is not", "It is not deletion." in RETIREMENT)


def run(expr: str, arg) -> object:
    blk = block()
    # The pure filter lives in renderHarnessTrust; lift the two lines that decide visibility.
    prog = (
        "const showRetiredArg = JSON.parse(process.argv[1]);\n"
        "const A = showRetiredArg;\n"
        "function visible(allRows, retired, showRetired) {\n"
        "  const retiredSet = new Set(retired);\n"
        "  const rows = allRows.filter(r => !retiredSet.has(r.plugin_id) || showRetired || r.action_count > 0);\n"
        "  return { shown: rows.map(r => r.plugin_id), hidden: allRows.length - rows.length };\n"
        "}\n"
        f"process.stdout.write(JSON.stringify({expr}));"
    )
    r = subprocess.run(["node", "-e", prog, json.dumps(arg)], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        FAILS.append(f"node failed: {r.stderr.strip()[-300:]}")
        return None
    return json.loads(r.stdout)


def behaviour() -> None:
    # The filter's source of truth is the render block; assert the lifted copy is the same line,
    # or this whole arm is testing a paraphrase.
    check("the lifted filter is the dashboard's own line",
          "const rows = allRows.filter(r => !retiredSet.has(r.plugin_id) || showRetired || r.action_count > 0);" in UI)

    dp = [{"plugin_id": "claude-code", "action_count": 5415},
          {"plugin_id": "Claude-code", "action_count": 0},
          {"plugin_id": "caude-code", "action_count": 0}]
    retired = ["Claude-code", "caude-code"]
    got = run("visible(A[0], A[1], false)", [dp, retired])
    check("dp's case: retiring the two phantoms leaves ONE Claude Code",
          got, {"shown": ["claude-code"], "hidden": 2})
    got = run("visible(A[0], A[1], true)", [dp, retired])
    check("show retired: all three, nothing lost", got["shown"], ["claude-code", "Claude-code", "caude-code"])

    # A retired id that is STILL ACTING is shown even when hiding: a live agent is not hidden.
    live = [{"plugin_id": "claude-code", "action_count": 5415}, {"plugin_id": "kimi-code", "action_count": 12}]
    got = run("visible(A[0], A[1], false)", [live, ["kimi-code"]])
    check("a retired id that is still acting stays visible", got, {"shown": ["claude-code", "kimi-code"], "hidden": 0})
    check("nothing retired: nothing hidden", run("visible(A[0], A[1], false)", [dp, []])["hidden"], 0)


def test_retire_control_contract() -> None:
    """pytest's entry: the same checks, and a failure it can see."""
    FAILS.clear()
    source_contract()
    if shutil.which("node"):
        behaviour()
    assert not FAILS, "\n".join(FAILS)


def main() -> int:
    try:
        test_retire_control_contract()
    except AssertionError:
        pass
    if not shutil.which("node"):
        print("SKIPPED: behaviour -- no node on PATH (the source contract above still ran)")
    for f in FAILS:
        print("FAIL", f)
    print(f"retire control contract: {'FAIL' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
