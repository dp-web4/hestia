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

WHERE THE CONTROL LIVES, AND WHY IT MOVED (dp, 2026-09-25): *"i would rather move that
functionality into govern->discover specifically, rather than have it prominently in the live
monitoring channel."* The trust list is a screen people glance at; the act that revokes an
agent's authority is not a glanceable one. It now sits in govern -> discover, the lifecycle pane,
in a group Discover had to grow in order to hold it: the ids hestia records as members that
nothing on this machine accounts for. That group IS the phantom class, so the control and the
rows it exists for finally share a screen -- and the trust list keeps saying that a row is
retired, because a monitoring view that silently omitted one would be lying about the machine.

Both halves are pinned below: the controls are absent from the trust render and present on the
Discover rows. A move that only half landed would leave the act in two places, which is how it
got reviewed in the wrong place to begin with.

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


def trust_render() -> str:
    """The live monitoring channel: the harness trust list's own render."""
    a = UI.index("  function renderHarnessTrust(")
    return UI[a:UI.index("  // Drill from the harness aggregate", a)]


def discover_render() -> str:
    a = UI.index("  function discoverRender(model)")
    return UI[a:UI.index("  let discoverBusy = false;", a)]


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

    # THE MOVE, pinned from both ends. Either half alone would pass while the act sat in two
    # places -- the state that put a grant-revoking button in a glanceable view in the first cut.
    tr, disc = trust_render(), discover_render()
    for control in ("data-retire=", "data-reinstate=", "trust-show-retired", "trust-hide-retired"):
        check(f"the live trust list no longer carries {control}", control in tr, False)
    check("...and it still SAYS a row is retired -- hiding that would misreport the machine",
          "<strong>retired</strong> on this seat" in tr)
    check("...and points at where the act went, rather than leaving a dead end",
          tr.count("govern → discover"), 2)
    check("discover carries retire", "data-retire=" in disc)
    check("discover carries reinstate", "data-reinstate=" in disc)
    check("the toggle moved with them", "disc-show-retired" in disc and "disc-hide-retired" in disc)

    # EVERY LIST, NOT TWO (dp, 2026-09-25: a retired `caude-code` "still shows up as a
    # registered harness in the witness and other displays"). The agents bar is fixed on the
    # daemon side (http.rs `a_retired_phantom_leaves_the_agents_bar_too`); the member pickers
    # here. Retired ids leave every picker except the two MERGE pickers, where folding a
    # phantom into the real id stays possible and the option says RETIRED.
    keepers = re.findall(r'<select[^>]*data-keep-retired="1"[^>]*>', UI)
    check("exactly the two merge pickers keep retired ids",
          sorted(re.search(r'id="([^"]+)"', k).group(1) for k in keepers), ["ali-alias", "ali-of"])
    check("every other picker drops them",
          "ids.filter(([id]) => !retiredNow.has(id))" in UI and "sel.dataset.keepRetired" in UI)
    check("...and where one is kept, it says so", "if (m.retired) bits.unshift('RETIRED');" in UI)
    check("the toggle drives the pane that now owns the hiding",
          "showRetired = t.id === 'disc-show-retired';" in blk and "discoverLoad();" in blk)
    check("retire is offered on the phantom class only, not on an installed agent's row",
          disc.count("data-retire=") == 1 and "g.key !== 'unaccounted' ? ''" in disc)

    # The daemon's half, pinned where each claim lives. The Rust suite exercises every one of
    # these; the pins here point at the lines that decide, not at declarations or literals --
    # the first cut pinned a constant and a response literal, both of which survived the
    # sabotage that mattered.
    check("the route refuses without reason and ref", "reason and ref are required" in RS)
    check("the guard's scan is RESTRICTED to the agent's own act types",
          "scan_recent(Some(cutoff), Some(AGENT_ACT_EVENTS), 50_000" in RS)
    check("...the types the operator's own act count is built from",
          'const AGENT_ACT_EVENTS: &[&str] = &["policy_decision", "outcome"];' in RS)
    # The guard must not fail open (cbp, PR #1100, finding 4): unmeasurable is a refusal.
    check("an unreadable chain is Err, never zero", "-> Result<usize, String> {" in RS and ".map_err(|e| e.to_string())" in RS)
    check("...and the guard names it", '"unmeasurable": true' in RS)
    # ONE refusal, FOUR doors (finding 1: the first cut guarded only scope_grant, and reassign's
    # `to` -- one keystroke from `claude-code` -- handed a retired id a grant).
    for via in ("an operator grant", "a decided request", "promotion of a live grant", "a reassign"):
        check(f"authority is refused to a retired id via {via}", f'"{via}")' in RS and "refuse_if_retired(&s, &" in RS)
    check("reassign checks RETIRED before UNKNOWN: retirement leaves the id in the registry",
          RS.index('refuse_if_retired(&s, &to, "a reassign")') < RS.index("if s.member_registry.get(&to).is_none() {"))
    check("the grant route's retired refusal comes before its unknown-member check",
          RS.index('refuse_if_retired(&s, &plugin_id, "an operator grant")') < RS.index("let member_known ="))
    check("retirement is witnessed intent-then-commit",
          '"member_retire_intent"' in RS and '"member_retired"' in RS)
    check("the per-seat scope is stated in the record itself", "this seat only" in RS)
    # Live grants go with the standing ones (finding 2), and memory is swapped the moment each
    # save succeeds so it is never looser than the vault (finding 3).
    ST = (ROOT / "core/src/server/state.rs").read_text()
    body = ST[ST.index("pub fn commit_retirement"):ST.index("/// Append a chain entry under the sovereign LCT.")]
    check("live grants are revoked in the same act", "r.revoked = Some(ScopeRevocation {" in body)
    # .find, not .index: a sabotage that REMOVES the swap must be a named failure, not a
    # traceback that hides every other finding (this check first died on exactly that).
    swap, save = body.find("self.standing_scope = scope;"), body.find("crate::server::retirement::save(")
    check("the standing store is swapped into memory at all", swap >= 0)
    check("...and BEFORE the retirement is saved", swap >= 0 and save >= 0 and swap < save)
    check("a half-landed commit is named as such", "HALF landed" in body)
    # A retired id that connects is witnessed (finding 5: documented before it existed).
    HANDLER = (ROOT / "core/src/server/handler.rs").read_text()
    check("a retired id connecting is witnessed", '"retired_member_connected"' in HANDLER)
    check("the module says what retirement is not", "It is not deletion." in RETIREMENT)

# The two filters that now decide visibility, one per view. The trust list's is unconditional
# (it no longer has a toggle); Discover's is the pure model, lifted whole.
TRUST_FILTER = ("  const rows = allRows.filter(r => !retiredSet.has(r.plugin_id) "
                "|| r.action_count > 0 || connected.has(r.plugin_id));")


def run(expr: str, arg) -> object:
    prog = (
        "const A = JSON.parse(process.argv[1]);\n"
        "function visible(allRows, retired, connectedIds) {\n"
        "  const retiredSet = new Set(retired); const connected = new Set(connectedIds || []);\n"
        f"{TRUST_FILTER}\n"
        "  return { shown: rows.map(r => r.plugin_id), hidden: allRows.length - rows.length };\n"
        "}\n"
        f"process.stdout.write(JSON.stringify({expr}));"
    )
    r = subprocess.run(["node", "-e", prog, json.dumps(arg)], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        FAILS.append(f"node failed: {r.stderr.strip()[-300:]}")
        return None
    return json.loads(r.stdout)


DP_ROWS = [{"plugin_id": "claude-code", "action_count": 5415},
           {"plugin_id": "Claude-code", "action_count": 0},
           {"plugin_id": "caude-code", "action_count": 0}]


def behaviour() -> None:
    # The filter's source of truth is the render; assert the lifted copy is the same line, or
    # this whole arm is testing a paraphrase.
    check("the lifted filter is the dashboard's own line", TRUST_FILTER in UI)

    retired = ["Claude-code", "caude-code"]
    got = run("visible(A[0], A[1])", [DP_ROWS, retired])
    check("dp's case: retiring the two phantoms leaves ONE Claude Code in the monitoring view",
          got, {"shown": ["claude-code"], "hidden": 2})

    # A retired id that is STILL ACTING is shown: a live agent is not hidden, and there is no
    # longer a toggle here that could hide it either.
    live = [{"plugin_id": "claude-code", "action_count": 5415}, {"plugin_id": "kimi-code", "action_count": 12}]
    got = run("visible(A[0], A[1])", [live, ["kimi-code"]])
    check("a retired id that is still acting stays visible", got, {"shown": ["claude-code", "kimi-code"], "hidden": 0})
    check("nothing retired: nothing hidden", run("visible(A[0], A[1])", [DP_ROWS, []])["hidden"], 0)
    # A retired id that is CONNECTED (never acted) stays visible: it is news, not something to hide.
    got = run("visible(A[0], A[1], A[2])", [DP_ROWS, retired, ["caude-code"]])
    check("a retired id that is connected right now stays visible", got, {"shown": ["claude-code", "caude-code"], "hidden": 1})


def reachability() -> None:
    """THE MOVE'S ONE REAL RISK: the phantoms become unreachable. The trust list could hide them
    before, but it could also retire them. Discover could always show agents -- but only ones
    found ON DISK, which a phantom by definition is not. A straight move would have left dp's two
    ids with no screen that both shows them and can act on them. So the group Discover grew is
    pinned here, from THIS test, as the thing that makes the move safe rather than as a feature."""
    pure_src = UI[UI.index("const DISCOVER_GROUPS"):UI.index("function discoverRender(")]
    prog = pure_src + ("\nconst A = JSON.parse(process.argv[1]);"
                       "\nprocess.stdout.write(JSON.stringify(discoverModel(A[0], A[1], A[2], A[3])));")

    def model(report, members, retired=(), show=False):
        r = subprocess.run(["node", "-e", prog, json.dumps([report, members, list(retired), show])],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            FAILS.append(f"node failed: {r.stderr.strip()[-300:]}")
            return {"groups": []}
        return json.loads(r.stdout)

    # This machine's real shape: the inventory names one governed harness; the registry holds three.
    report = {"status": "OK", "governed": ["claude"], "gaps": {},
              "detail": [{"agent": "claude", "plugin": "claude-code", "installed": True, "atlas": {},
                          "configs_read": [], "findings": []}]}
    both = ["Claude-code", "caude-code"]
    m = model(report, DP_ROWS)
    orphans = [r for g in m["groups"] for r in g["rows"] if g["key"] == "unaccounted"]
    check("dp's two phantoms are REACHABLE in the pane that now owns retire",
          [r["governanceId"] for r in orphans], ["Claude-code", "caude-code"])
    check("...and the live id is not among them, so the dangerous one is not offered up",
          "claude-code" not in [r["governanceId"] for r in orphans])
    check("...and they lead the pane, because they are the reason to open it",
          m["groups"][0]["key"], "unaccounted")
    check("retiring both empties the group, and the hidden count survives so the toggle remains",
          (any(g["key"] == "unaccounted" for g in model(report, DP_ROWS, both).get("groups", [])),
           model(report, DP_ROWS, both)["hiddenRetired"]), (False, 2))
    check("show retired brings them back, marked, which is what offers reinstate",
          [(r["governanceId"], r["retired"]) for g in model(report, DP_ROWS, both, True)["groups"]
           for r in g["rows"] if g["key"] == "unaccounted"],
          [("Claude-code", True), ("caude-code", True)])
    # The failure that would strand them quietly: the inventory walk dies and the pane renders
    # empty. The registry half comes from the snapshot, so it must survive that.
    m = model({"status": "UNKNOWN", "reason": "could not reach the inventory (boom)"}, DP_ROWS)
    check("the inventory unreachable: the orphans are STILL listed and still actionable",
          [r["governanceId"] for g in m["groups"] for r in g["rows"] if g["key"] == "unaccounted"],
          ["claude-code", "Claude-code", "caude-code"])


def test_retire_control_contract() -> None:
    """pytest's entry: the same checks, and a failure it can see."""
    FAILS.clear()
    source_contract()
    if shutil.which("node"):
        behaviour()
        reachability()
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
