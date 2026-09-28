#!/usr/bin/env python3
"""Discover pane contract (agent-lifecycle PRD R2): it is present, it is READ-ONLY, and it never
renders "could not look" as "nothing there".

Source-level where the claim is about what EXISTS or is ABSENT, in the house idiom
(runtime_config_operator_surface_test.py): each check names the construct it pins. Behavioural
where the claim is about what the pane DOES: `discoverModel` and `discoverRow` are pure -- report
in, view-model out, no DOM -- so they are lifted out of the dashboard and run under node.

WHAT USED TO BE PINNED HERE, AND WHY IT CHANGED (dp, 2026-09-25). The first cut pinned this pane
as READ-ONLY by absence: the Discover block must contain no request but one GET. The reason was
drift -- an operator act arriving as a convenient button on the screen that already lists the
agents, which no test of present behaviour would notice.

RETIRE HAS NOW ARRIVED HERE DELIBERATELY, because dp asked for it: it was in the live trust list,
which is a monitoring view people glance at, and a control that revokes authority does not belong
there. So the absence-pin would now have to be either deleted or kept as a lie -- and kept, it
would be a lie that still PASSES, because `retireAgent`/`reinstateAgent` are lexically outside
this block. A pin that cannot fail is worse than no pin.

It is replaced by an enumeration, which is the same guard stated positively: the pane's own
fetch is still exactly one GET, and the only write-capable controls it renders are the two named,
separately-reviewed operator acts -- so a THIRD one still cannot arrive unnoticed. The absence
checks that remain (no DELETE, no method override on the read, no timer) are the ones the move
did not touch.

THE THREE ANSWERS THAT MUST STAY THREE (PRD P4), each of which this fleet has shipped as the
wrong one at least once: the scan could not run (UNKNOWN, with its reason -- never an empty
list); the scan ran and a group is empty (omitted); and an installed agent the report did not
classify (kept, under its own heading -- a row that vanishes is the defect).

Run: python3 tools/discover_pane_contract_test.py     (exit 1 on failure)
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
FAILS: list[str] = []


def check(name: str, got, want=True) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def discover_block() -> str:
    a = UI.index("// ── Discover (agent-lifecycle PRD R2)")
    b = UI.index("const GOVERN_PANES = {", a)
    return UI[a:b]


def source_contract() -> None:
    check("govern sub-nav has the chip", 'data-gov="discover"' in UI)
    check("pane is registered, and mounts by loading",
          "discover: { el: 'govern-discover', mount: () => discoverLoad() }" in UI)
    check("pane section exists", '<section class="govern-pane" id="govern-discover" hidden>' in UI)
    check("rescan is wired", "e.target.id === 'disc-rescan'" in UI)

    block = discover_block()
    # ONE READ AND ONE WRITE, changed deliberately on 2026-09-21 and narrowed in the same move.
    #
    # This pane was pinned READ-ONLY, and the pin did its job: adding the Register action turned
    # it red on four checks at once, which is the review this file exists to force. Registration
    # is the act the old pin's own comment called "a later, separate, operator act" (R4), and the
    # Discover row is where the operator is looking at the thing being registered -- putting the
    # button anywhere else would mean re-identifying the agent by hand, which is the defect
    # (#1067). So the allowance is singular and spelled out, rather than the rule being dropped:
    # exactly two requests, exactly one of them a write, only POST, only to that one route, and
    # carrying no `plugin_id`. A third request, another verb, or a typed id turns this red again.
    fetches = re.findall(r"apiFetch\(\s*'([^']+)'\s*(?:,\s*\{([^}]*)\})?", block)
    # TWO requests of the pane's own: the inventory read, and register (#1101), which is the one
    # write built inline here -- retire and reinstate go through the retire block's reviewed
    # functions instead. Pinned by route and method, not by count alone.
    check("exactly two requests in the Discover block: the read and the one write", len(fetches), 2)
    reads = [f for f in fetches if "method" not in f[1]]
    writes = [f for f in fetches if "method" in f[1]]
    check("the read is the inventory read, with no method override",
          [f[0] for f in reads], ["/api/agents"])
    check("there is exactly ONE write built here, and it is the register route",
          [f[0] for f in writes], ["/api/agents/register"])
    check("...and it is a POST", all("'POST'" in f[1] for f in writes), True)
    for verb in ("'PUT'", "'DELETE'", "'PATCH'", '"PUT"', '"DELETE"', '"PATCH"'):
        check(f"no {verb} anywhere in the Discover block", verb in block, False)
    # The BODY, pinned whole, rather than "the string plugin_id is absent from the block": the
    # response's derived id is SHOWN to the operator (`out.plugin_id`), and that is the point of
    # deriving it. What must not happen is sending one.
    check("the write's body is the clicked row's atlas id and a reason, and nothing else",
          "body: JSON.stringify({ atlas_id: atlasId, reason })" in block)
    # THE ENUMERATION that replaced the absence-pin (#1113). Any write-capable control the render
    # grows must be added here with a reason, which is the review step the absence-pin provided.
    # It grew by one when register (#1101) and retire (#1113) landed in the same pane.
    WRITE_CONTROLS = {"data-retire": "retire (#1100, moved here by #1113)",
                      "data-reinstate": "reinstate (#1100, moved here by #1113)",
                      "data-register": "register a discovered harness (#1101)",
                      # dp, 2026-09-28: 12 phantoms, two prompts each. One reason for all of the
                      # never-acted ones; each through the same route, never with confirm_active.
                      "data-retire-all": "retire every never-acted orphan in one act"}
    found = set(re.findall(r"\bdata-(?:retire-all|retire|reinstate|register|delete|revoke|grant|merge-alias)(?![\w-])", block))
    check("the write-capable controls in this pane are exactly the reviewed four",
          sorted(found), sorted(WRITE_CONTROLS))
    check("retire and reinstate are dispatched by the retire block's own delegated handler",
          "closest('[data-retire],[data-reinstate],[data-retire-all],#disc-show-retired,#disc-hide-retired')" in UI)
    # THE BULK ACT MUST NOT BE THE WAY AROUND THE LIVE-MEMBER GUARD. retireNeverActed sends each id
    # without confirm_active, so an id that acted recently is refused by the server and reported.
    bulk = UI[UI.index("async function retireNeverActed("):UI.index("async function reinstateAgent(")]
    check("bulk retire never sends confirm_active", "confirm_active" in bulk, False)
    check("bulk retire goes through the same retire route per id",
          "/api/agents/${encodeURIComponent(id)}/retire" in bulk)
    check("bulk retire asks for the reason and the evidence pointer", "if (!reason) return;" in bulk and "if (!ref) return;" in bulk)
    check("retire is offered ONLY on the unaccounted group, never on an installed agent's row",
          block.count("data-retire=") == 1
          and "g.key !== 'unaccounted' ? ''" in block)
    check("no timer of its own -- a filesystem walk is fetched on show and on rescan only",
          "setInterval" in block, False)

    check("a fetch failure is rendered as UNKNOWN, not as an empty machine",
          "could not reach the inventory" in block and "status: 'UNKNOWN'" in block)
    # ...and it must still list the registry half, which does not come from the walk that died.
    check("a fetch failure still passes the members through, so the orphans stay reachable",
          block.count("discoverMembers(lastData)"), 2)
    # ...and the members are the REGISTRY's, not only those with a trust row: a member that never
    # acted has none, and was invisible here (dp, 2026-09-28).
    # BEHAVIOURAL, not a string: a first source-only pin stayed green with the merge disabled.
    import re as _re
    def _fn(name):
        a = UI.index(f"function {name}(")
        depth, i = 0, UI.index("{", a)
        while True:
            depth += UI[i] == "{"; depth -= UI[i] == "}"; i += 1
            if depth == 0:
                return UI[a:i]
    lvl = _re.search(r"const LEVEL_ORDER = [^;]*;", UI).group(0)
    prog = (lvl + _fn("aggregateHarnessTrust") + _fn("discoverMembers") +
            "\nconst D = JSON.parse(process.argv[1]);"
            "process.stdout.write(JSON.stringify(discoverMembers(D).map(m => [m.plugin_id, m.action_count])));")
    data = {"trust": [{"plugin_id": "claude-code", "action_count": 5415, "level": "high"}],
            "members": ["claude-code", "Claude-code", "mcnugget-being"]}
    out = subprocess.run(["node", "-e", prog, json.dumps(data)], capture_output=True, text=True, timeout=30)
    got = json.loads(out.stdout) if out.returncode == 0 else out.stderr.strip()[-200:]
    check("the loader adds every registry id the trust rows lack, at zero acts, without duplicating",
          got, [["claude-code", 5415], ["Claude-code", 0], ["mcnugget-being", 0]])
    check("UNKNOWN says it is not 'nothing found'", 'this is not "nothing found"' in block)
    check("undefined failure mode is its own state", "failure mode unknown" in block)
    check("both names are shown, and the grant-relevant one is labelled",
          "governance id" in block and "atlas <code>" in block)


def run_model(report, members=None, retired=None, show_retired=False) -> dict:
    block = discover_block()
    pure = block[block.index("const DISCOVER_GROUPS"):block.index("function discoverRender(")]
    prog = pure + ("\nconst A = JSON.parse(process.argv[1]);"
                   "\nprocess.stdout.write(JSON.stringify(discoverModel(A[0], A[1], A[2], A[3])));")
    arg = json.dumps([report, members, retired, show_retired])
    r = subprocess.run(["node", "-e", prog, arg], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        FAILS.append(f"node failed: {r.stderr.strip()[:300]}")
        return {"groups": [], "unknown": None}
    return json.loads(r.stdout)


def agent(atlas_id, plugin, installed, atlas=None, **kw):
    return {"agent": atlas_id, "plugin": plugin, "installed": installed, "atlas": atlas or {},
            "configs_read": [], "findings": [], **kw}


def behaviour() -> None:
    ok_report = {
        "status": "OK", "governed": ["claude"],
        "gaps": {"miswired": ["gemini"], "ungoverned": ["codex"], "ungovernable": ["aider"],
                 "dormant_plugin": ["cursor"], "partial": [], "miswired_3p": [], "unknown": []},
        "scope": {"workspace": "/w", "agent_enumeration": "agent-atlas",
                  "agent_enumeration_complete": True, "atlas": "/a", "atlas_source": "env"},
        "detail": [
            agent("claude", "claude-code", True, {"harness": "Claude Code", "fails_open": True,
                                                   "blocking_events": ["PreToolUse"], "fidelity": "verified"}),
            agent("gemini", "gemini", True, {"harness": "Gemini CLI", "fails_open": False}),
            agent("codex", "codex", True, {"harness": "Codex"}),
            agent("aider", None, True, {"harness": "Aider", "fails_open": True}),
            agent("cursor", "cursor", False),
        ],
    }
    m = run_model(ok_report)
    check("OK report is not unknown", m.get("unknown"), False)
    check("WORST FIRST: miswired leads, governed follows the gaps, dormant is last",
          [g["key"] for g in m["groups"]], ["miswired", "ungoverned", "ungovernable", "governed", "dormant_plugin"])
    rows = {r["atlasId"]: r for g in m["groups"] for r in g["rows"]}
    check("the two names are distinct fields", (rows["claude"]["atlasId"], rows["claude"]["governanceId"]),
          ("claude", "claude-code"))
    check("display name comes from the atlas descriptor", rows["claude"]["name"], "Claude Code")
    check("fails_open true  -> open", rows["claude"]["failure"], "open")
    check("fails_open false -> closed", rows["gemini"]["failure"], "closed")
    check("fails_open ABSENT -> unknown, NOT closed and NOT open", rows["codex"]["failure"], "unknown")
    check("no plugin -> no governance id, rather than echoing the atlas id", rows["aider"]["governanceId"], "")
    check("scope carries where the atlas came from", m["scope"]["atlasSource"], "env")

    # UNKNOWN that still saw things: the banner AND the rows. The inventory deliberately keeps
    # walking when the atlas is missing; dropping its rows here would undo that.
    partial = dict(ok_report, status="UNKNOWN", reason="agent-atlas registry not readable",
                   scope=dict(ok_report["scope"], agent_enumeration_complete=False))
    m = run_model(partial)
    check("UNKNOWN keeps its reason", (m["unknown"], m["reason"]), (True, "agent-atlas registry not readable"))
    check("UNKNOWN still lists what it saw", sum(len(g["rows"]) for g in m["groups"]), 5)
    check("an incomplete enumeration is flagged", m["scope"]["complete"], False)

    # THE OTHER DIRECTION (GPT, PR #1073 HOLD): an agent the inventory could not classify.
    # Shaped like the real producer in inventory.py -- config present and hestia-wired, no
    # executable in the searched roots -- which leaves installed=false and therefore ALSO files
    # the agent under dormant_plugin. The first cut had no `unknown` group and a fallback that
    # required `installed`, so the agent that CAUSED the UNKNOWN was the one row not drawn.
    why = "config dir present and hestia-wired, but no executable found in the searched roots"
    amb = {"status": "UNKNOWN", "governed": [],
           "gaps": {"unknown": ["claude"], "dormant_plugin": ["claude", "gemini"], "miswired": []},
           "detail": [agent("claude", "claude-code", False, {"harness": "Claude Code"}, unknown=[why]),
                      agent("gemini", "gemini-cli", False)]}
    m = run_model(amb)
    by_key = {g["key"]: g for g in m["groups"]}
    # .get throughout: a missing group must be a NAMED failure, not a KeyError that hides the rest.
    urow = ((by_key.get("unknown") or {}).get("rows") or [{}])[0]
    check("agent-unknown: the banner is up", m["unknown"], True)
    check("agent-unknown: a visible group holds the agent, and it leads",
          (m["groups"][0]["key"], [r["atlasId"] for r in m["groups"][0]["rows"]]), ("unknown", ["claude"]))
    check("agent-unknown: the row keeps the inventory's specific reason",
          urow.get("unknownReasons"), [why])
    check("agent-unknown: NOT relabelled dormant -- the unknown group claims it exclusively",
          [r["atlasId"] for r in (by_key.get("dormant_plugin") or {}).get("rows", [])], ["gemini"])
    check("agent-unknown: ...and the report's other filing survives as a claim, not a group",
          urow.get("alsoFiledUnder"), ["dormant_plugin"])
    check("agent-unknown: drawn exactly once", sum(r["atlasId"] == "claude" for g in m["groups"] for r in g["rows"]), 1)
    # WHO IS OFFERED REGISTRATION. Not everyone: the button must not appear where it would be a
    # no-op (already a member) or where the daemon could not derive an id without inventing one.
    # Added after a sabotage -- "offer it on an already-governed agent" -- passed clean, because
    # this file pinned the request's shape and nothing about who may send it.
    reg = {"status": "OK", "governed": ["claude"],
           "gaps": {"ungoverned": ["codex"], "ungovernable": ["aider"], "unprovisioned_being": ["sage"]},
           "detail": [agent("claude", "claude-code", True, governed=True),
                      agent("codex", "codex", True),
                      agent("aider", None, True),
                      agent("sage", None, True, {"harness": "SAGE", "kind": "being"}, kind="being")]}
    rows = {r["atlasId"]: r for g in run_model(reg)["groups"] for r in g["rows"]}
    check("a governed agent is already a member: no button", rows["claude"]["registerable"], False)
    check("an installed, ungoverned harness with a plugin id: offered", rows["codex"]["registerable"], True)
    check("a being with no launcher yet: offered (its id comes from the <machine>-being convention)",
          rows["sage"]["registerable"], True)
    check("no plugin and not a being: NOT offered, because registering would mean inventing an id",
          rows["aider"]["registerable"], False)
    # NOT INSTALLED HERE (dp, 2026-09-27): the atlas knows harnesses this machine lacks, and the
    # first cut offered register on all of them -- five buttons on McNugget, none installed.
    dormant = dict(reg, gaps={"dormant_plugin": ["cursor"]},
                   detail=reg["detail"] + [agent("cursor", "cursor", False)])
    drow = {r["atlasId"]: r for g in run_model(dormant)["groups"] for r in g["rows"]}
    check("a harness NOT INSTALLED here is not offered: registering it mints an absent member",
          drow["cursor"]["registerable"], False)
    # A BEING (atlas `kind: being`). Its gap is its own; its governance id is per seat and comes
    # from its launcher, so an unprovisioned one has none -- and must not be told "no hestia
    # plugin" (it needs none), nor be dropped because no older group claims it.
    being = {"status": "GAP", "governed": ["claude"],
             "gaps": {"unprovisioned_being": ["sage"]},
             "detail": [agent("claude", "claude-code", True),
                        agent("sage", None, True, {"harness": "SAGE", "kind": "being", "fails_open": False},
                              kind="being", launchers=[])]}
    mb = run_model(being)
    bk = {g["key"]: g for g in mb["groups"]}
    brow = ((bk.get("unprovisioned_being") or {}).get("rows") or [{}])[0]
    check("being: an unprovisioned being is drawn in its own group", brow.get("atlasId"), "sage")
    check("being: tagged as a being, with no governance id invented for it",
          (brow.get("being"), brow.get("governanceId")), (True, ""))
    check("being: never 'unclassified' -- the report DID classify it", "unclassified" in bk, False)
    gov = dict(being, governed=["claude", "sage"], gaps={},
               detail=[being["detail"][0], agent("sage", "legion-being", True, {"harness": "SAGE", "kind": "being"},
                                                 kind="being", launchers=[{"unit": "u", "member": "legion-being"}])])
    grow = [r for g in run_model(gov)["groups"] if g["key"] == "governed" for r in g["rows"] if r["atlasId"] == "sage"]
    check("being: a governed one shows its PER-SEAT id, not `sage`",
          [(r["governanceId"], r["launchers"]) for r in grow], [("legion-being", 1)])

    # GAP outranks UNKNOWN in the inventory's status, so status alone cannot raise the banner.
    m = run_model(dict(amb, status="GAP"))
    check("agent-unknown under status=GAP: banner still up, row still there",
          (m["unknown"], m["groups"][0]["key"]), (True, "unknown"))
    # A report that disagrees with itself: reasons on the record, id missing from gaps.unknown.
    m = run_model(dict(amb, gaps={"dormant_plugin": ["claude", "gemini"]}))
    check("agent-unknown named only by its detail record is still claimed",
          [(g["key"], g["rows"][0]["atlasId"]) for g in m["groups"]][:1], [("unknown", "claude")])
    # ...and listed with no record at all: a row by id, and the absence of a reason is visible.
    m = run_model({"status": "UNKNOWN", "gaps": {"unknown": ["ghost"]}})
    check("agent-unknown with no detail record: drawn, with no invented reason",
          [(r["atlasId"], r["unknownReasons"]) for g in m["groups"] for r in g["rows"]], [("ghost", [])])

    # The daemon's own UNKNOWN when the inventory is not installed: status + reason, nothing else.
    m = run_model({"status": "UNKNOWN", "reason": "agent-inventory is not installed on this machine"})
    check("not-installed: unknown, with the daemon's reason, no invented rows",
          (m["unknown"], m["reason"], m["groups"]),
          (True, "agent-inventory is not installed on this machine", []))

    # Garbage in. None of these may throw, and none may read as a clean machine.
    for label, junk in (("empty object", {}), ("null", None), ("detail is not a list", {"status": "OK", "detail": 7}),
                        ("rows are not objects", {"status": "OK", "detail": [None, 3, "x"], "governed": ["ghost"]})):
        m = run_model(junk)
        check(f"garbage ({label}): survives", isinstance(m.get("groups"), list))
    m = run_model({})
    check("no status at all is UNKNOWN, with a reason", (m["unknown"], bool(m["reason"])), (True, True))
    m = run_model({"status": "OK", "governed": ["ghost"], "detail": []})
    check("an id with no detail record still gets a row, by its id", m["groups"][0]["rows"][0]["name"], "ghost")

    # An installed agent no group claims must not vanish.
    stray = dict(ok_report, detail=ok_report["detail"] + [agent("windsurf", None, True, {"harness": "Windsurf"})])
    m = run_model(stray)
    check("unclassified installed agent is SHOWN, and first", (m["groups"][0]["key"], m["groups"][0]["rows"][0]["atlasId"]),
          ("unclassified", "windsurf"))
    quiet = dict(ok_report, detail=ok_report["detail"] + [agent("windsurf", None, False)])
    check("a NOT-installed unclassified agent is not noise", run_model(quiet)["groups"][0]["key"], "miswired")


def unaccounted() -> None:
    """THE REGISTRY HALF (dp, 2026-09-25): ids hestia records as members that the inventory --
    which walks disk and the atlas -- cannot see, and therefore never listed. dp's three
    `claude-code` rows are the case: two were minted by mistyped grants (#1067) and were
    invisible in the pane built to find exactly that."""
    # The live shape on this machine: the inventory names `claude` (plugin `claude-code`) and
    # nothing else; the registry also holds the two phantoms.
    report = {"status": "OK", "governed": ["claude"], "gaps": {},
              "detail": [agent("claude", "claude-code", True, {"harness": "Claude Code"})]}
    members = [{"plugin_id": "claude-code", "action_count": 5415},
               {"plugin_id": "Claude-code", "action_count": 0},
               {"plugin_id": "caude-code", "action_count": 0}]

    m = run_model(report, members, [])
    by_key = {g["key"]: g for g in m["groups"]}
    check("the phantoms get a group, and it LEADS -- they are the reason to open this pane",
          m["groups"][0]["key"], "unaccounted")
    check("...holding exactly the ids no inventory record accounts for",
          [r["governanceId"] for r in by_key["unaccounted"]["rows"]], ["Claude-code", "caude-code"])
    check("the live id is NOT an orphan: the inventory's `plugin` field accounts for it",
          "claude-code" not in [r["governanceId"] for r in by_key["unaccounted"]["rows"]])
    check("governed still holds the real one", [r["atlasId"] for r in by_key["governed"]["rows"]], ["claude"])
    check("the act count rides along -- it is what tells two look-alikes apart",
          [r["actionCount"] for r in by_key["unaccounted"]["rows"]], [0, 0])
    # REGISTER AND RETIRE MUST NEVER MEET ON ONE ROW. An unaccounted id is by definition already
    # a member, so offering to register it would mint a second record for the same id -- the
    # #1067 failure from the other side. Held today only by discoverRow(id, null) computing
    # registerable=false from an empty record; pinned so a change there cannot quietly undo it.
    check("an unaccounted row is never offered register -- it is already a member",
          [r["registerable"] for r in by_key["unaccounted"]["rows"]], [False, False])

    # ACCOUNTED-FOR MEANS THE GOVERNANCE ID, NOT THE ATLAS ID. They are different namespaces;
    # matching on the atlas id would silently account for a member it has no relation to.
    m = run_model({"status": "OK", "detail": [agent("claude-code", None, True)]},
                  [{"plugin_id": "claude-code", "action_count": 1}], [])
    check("an atlas id that merely LOOKS like the member id does not account for it",
          [r["governanceId"] for g in m["groups"] for r in g["rows"] if g["key"] == "unaccounted"],
          ["claude-code"])

    # Retired orphans: hidden by default, revealed by the toggle, and counted either way.
    m = run_model(report, members, ["Claude-code", "caude-code"])
    check("retiring both empties the group rather than leaving empty rows",
          "unaccounted" in [g["key"] for g in m["groups"]], False)
    check("...and the count of what is hidden survives, so the toggle can be offered",
          (m["hiddenRetired"], m["retiredOrphans"]), (2, 2))
    m = run_model(report, members, ["Claude-code", "caude-code"], True)
    rows = {r["governanceId"]: r for g in m["groups"] for r in g["rows"] if g["key"] == "unaccounted"}
    check("show retired: both are back", sorted(rows), ["Claude-code", "caude-code"])
    check("...marked retired, which is what swaps retire for reinstate in the render",
          [rows[k]["retired"] for k in sorted(rows)], [True, True])
    m = run_model(report, members, ["Claude-code"])
    check("one retired, one not: only the retired one is hidden",
          ([r["governanceId"] for g in m["groups"] for r in g["rows"] if g["key"] == "unaccounted"],
           m["hiddenRetired"]), (["caude-code"], 1))

    # THE OLD FIXTURES STILL HOLD. Called with the report alone, this pane is what it was.
    m = run_model(report)
    check("no members passed: no group, and no invented rows",
          ("unaccounted" in [g["key"] for g in m["groups"]], m["hiddenRetired"]), (False, 0))
    for label, junk in (("null members", None), ("not a list", 7), ("rows are not objects", [None, 3, "x"]),
                        ("no plugin_id", [{"action_count": 1}]), ("retired is not a list", 7)):
        arg = junk if label != "retired is not a list" else members
        ret = junk if label == "retired is not a list" else []
        m = run_model(report, arg, ret)
        check(f"garbage ({label}): survives, and does not read as a clean machine",
              isinstance(m.get("groups"), list) and isinstance(m.get("hiddenRetired"), int))

    # A FAILED SCAN MUST NOT STRAND THEM. The walk is what died; the registry came from the
    # snapshot. An operator who came here to retire a phantom still finds it.
    m = run_model({"status": "UNKNOWN", "reason": "could not reach the inventory (boom)"}, members, [])
    check("the inventory unreachable: UNKNOWN is up AND all three orphans are listed",
          (m["unknown"], [r["governanceId"] for g in m["groups"] for r in g["rows"]]),
          (True, ["claude-code", "Claude-code", "caude-code"]))


def member_ids() -> None:
    """THREE VOCABULARIES (dp, 2026-09-28). Kimi's atlas id is `kimi_code_cli`, its plugin
    directory `kimi`, its member id `kimi-code`. Keyed on the directory, the pane named its
    governance id `kimi` and filed the registered `kimi-code` under "nothing on this machine
    accounts for it" -- with a Retire button -- while it ran governed."""
    report = {
        "status": "OK", "governed": ["kimi_code_cli"],
        "gaps": {"miswired": [], "ungoverned": [], "ungovernable": [], "dormant_plugin": [],
                 "partial": [], "miswired_3p": [], "unknown": []},
        "scope": {"workspace": "/w", "agent_enumeration": "agent-atlas",
                  "agent_enumeration_complete": True, "atlas": "/a", "atlas_source": "env"},
        "detail": [agent("kimi_code_cli", "kimi", True, {"harness": "Kimi Code"}, member="kimi-code")],
    }
    m = run_model(report, [{"plugin_id": "kimi-code", "action_count": 48110}], [])
    rows = {r["atlasId"]: r for g in m["groups"] for r in g["rows"]}
    check("governance id is the MEMBER id, not the plugin directory",
          rows["kimi_code_cli"]["governanceId"], "kimi-code")
    check("a registered member the inventory accounts for (by member id) is not unaccounted",
          [g["key"] for g in m["groups"]].count("unaccounted"), 0)
    # An inventory that predates `member` still falls back to the directory.
    old = dict(report, detail=[agent("codex", "codex", True, {"harness": "Codex"})])
    m2 = run_model(old, [{"plugin_id": "codex", "action_count": 1}], [])
    check("no `member` field: the plugin directory is still the fallback",
          {r["atlasId"]: r for g in m2["groups"] for r in g["rows"]}["codex"]["governanceId"], "codex")


def registry_members() -> None:
    """dp, 2026-09-28: "when i tried to register the being, it said already registered but it
    doesn't show up. and we still have two claude-code registrations." One cause: Discover built
    its members from TRUST rows, which exist only for members that have acted."""
    report = {"status": "GAP", "machine": "McNugget", "governed": ["claude"],
              "gaps": {"unprovisioned_being": ["sage"]},
              "detail": [agent("claude", "claude-code", True, member="claude-code"),
                         agent("sage", None, True, {"harness": "SAGE", "kind": "being"}, kind="being",
                               launchers=[])]}
    reg = lambda *ids: [{"plugin_id": i, "action_count": 5415 if i == "claude-code" else 0} for i in ids]
    rows = lambda m: {r["atlasId"]: (g["key"], r) for g in m["groups"] for r in g["rows"]}

    m = run_model(report, reg("claude-code", "Claude-code", "mcnugget-being"), [])
    r = rows(m)
    check("a registered, never-launched being says who it is registered as",
          r["sage"][1].get("registeredAs"), "mcnugget-being")
    check("...and is NOT offered register again (that answered 'already registered')",
          r["sage"][1]["registerable"], False)
    check("...and is not listed as an orphan: it is right here, just not launched",
          "mcnugget-being" in [x["governanceId"] for g in m["groups"] if g["key"] == "unaccounted" for x in g["rows"]],
          False)
    check("a never-acted phantom from the registry IS listed, so it can be retired",
          [x["governanceId"] for g in m["groups"] if g["key"] == "unaccounted" for x in g["rows"]],
          ["Claude-code"])

    m = run_model(report, reg("claude-code"), [])
    check("not yet registered: the being IS offered register",
          rows(m)["sage"][1]["registerable"], True)

    # The general rule: a row whose id is already a member is never offered register.
    rep2 = dict(report, gaps={"ungoverned": ["codex"]},
                detail=[agent("codex", "codex", True, member="codex")])
    m = run_model(rep2, reg("codex"), [])
    check("an installed harness whose id is already a member: no register button",
          rows(m)["codex"][1]["registerable"], False)


def cleanup() -> None:
    """dp, 2026-09-28: Discover's orphan group held 12 ids -- typos, test ids, and hestia's own
    CLI and inventory. The tools are not phantoms; the rest should go in one act."""
    report = {"status": "OK", "machine": "McNugget", "governed": ["claude"], "gaps": {},
              "detail": [agent("claude", "claude-code", True, member="claude-code")]}
    ms = [{"plugin_id": "claude-code", "action_count": 5415},
          {"plugin_id": "hestia-cli", "action_count": 0}, {"plugin_id": "agent-inventory", "action_count": 0},
          {"plugin_id": "Claude-code", "action_count": 0}, {"plugin_id": "test-being", "action_count": 0},
          {"plugin_id": "claude-cod3", "action_count": 3}]
    m = run_model(report, ms, [])
    by = {g["key"]: [r["governanceId"] for r in g["rows"]] for g in m["groups"]}
    check("hestia's own tools are listed apart, not as phantoms",
          sorted(by.get("hestia_own", [])), ["agent-inventory", "hestia-cli"])
    check("...and are NOT in the orphan group, where retire lives",
          [x for x in by.get("unaccounted", []) if x in ("hestia-cli", "agent-inventory")], [])
    check("the typos and test ids ARE orphans", sorted(by.get("unaccounted", [])),
          ["Claude-code", "claude-cod3", "test-being"])
    # The bulk list is built in the render from the group's rows: never-acted and not retired.
    # claude-cod3 has acts here, so it must be left for a deliberate single retire.
    rows = {r["governanceId"]: r for g in m["groups"] if g["key"] == "unaccounted" for r in g["rows"]}
    bulk = sorted(i for i, r in rows.items() if not r.get("retired") and not r.get("actionCount"))
    check("the bulk offer covers only never-acted ids", bulk, ["Claude-code", "test-being"])
    check("the render builds the bulk list by exactly that rule",
          "g.rows.filter(r => !r.retired && !r.actionCount).map(r => r.governanceId)" in UI)


def live() -> None:
    """The real report from this machine, when there is one. It is the only fixture nobody wrote."""
    inv = Path.home() / ".local/bin/hestia-agent-inventory"
    if not inv.is_file():
        print("SKIPPED: live report -- hestia-agent-inventory is not installed here (fixtures still ran)")
        return
    r = subprocess.run([str(inv), "--no-witness", "--json"], capture_output=True, text=True, timeout=120)
    try:
        report = json.loads(r.stdout)
    except ValueError:
        print("SKIPPED: live report -- the installed inventory did not return JSON")
        return
    m = run_model(report)
    listed = {row["atlasId"] for g in m["groups"] for row in g["rows"]}
    # EVERY gap list, `unknown` included. The first cut of this line subtracted gaps.unknown from
    # what it expected to see drawn -- the test was written to permit the very drop it should
    # have caught (GPT, PR #1073 review).
    gaps = report.get("gaps") or {}
    expected = set(report.get("governed") or []) | {i for ids in gaps.values() if isinstance(ids, list) for i in ids}
    check("live: every agent the report groups is drawn", sorted(expected - listed), [])
    check("live: the banner is up whenever the report, or any agent in it, is unknown",
          m["unknown"], report.get("status") == "UNKNOWN" or bool(gaps.get("unknown")))
    print(f"live report: status={report.get('status')} groups={[ (g['key'], len(g['rows'])) for g in m['groups'] ]}")


def main() -> int:
    source_contract()
    if shutil.which("node"):
        behaviour()
        unaccounted()
        registry_members()
        cleanup()
        member_ids()
        live()
    else:
        print("SKIPPED: behaviour -- no node on PATH (the source contract above still ran)")
    for f in FAILS:
        print("FAIL", f)
    print(f"discover pane contract: {'FAILED' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
