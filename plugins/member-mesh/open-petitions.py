#!/usr/bin/env python3
"""The mirror of the debt fold: petitions this member has OPEN.

`hestia_member_unanswered` answers "what have you not replied to". Nothing has
ever answered "what have you ASKED that is still open" — and the member is the
only party that can retire a MOOT one, because it is the only party that knows
the act is over. Almost none of them are filed deliberately: on CBP, 30 of 30
recorded lapses were auto-minted by the gate on a refused write, and
`gate_escalation_withdrawn` had fired twice in the mesh's lifetime. The id is
printed once, into a refusal, in a wake that has usually ended by the time the
petition expires, so "which do I hold" was not a question a member could ask.

Two modes, deliberately in ONE file so the filter and the renderer are tested by
the same suite:

  fold <for_plugin>   stdin = `hestia_gate_pending_escalations` response
                      stdout = the primer fold (this member's rows only)
  render <primer>     stdout = the prompt block, empty when there is nothing

Shared by all three fire templates on purpose. A member that cannot see its own
petitions is not a claude-code property, and a renderer that lives in one
template fixes one seat rather than the class.
"""
import json
import re
import sys

# What survives into the primer. `stated_reason` is the daemon's own truncation
# of the refused command; `stated_detail` is kept only because its wording is the
# one available discriminator between a gate-auto-minted petition and one the
# member chose to file, and those two want different responses.
KEEP = ("escalation_id", "secs_remaining", "marker", "tool_name", "opened_at",
        "stated_reason", "stated_detail", "peer_participation", "bar")

clean = lambda s: re.sub(r"[\x00-\x1f\x7f]", "", str(s))[:400]


def fold(payload, for_plugin):
    """Filter a pending-escalations response down to one member's rows.

    `asked` is NOT derivable from `mine` being empty: a failed RPC and a member
    that holds nothing are the same empty list, and they want opposite readings.
    So the flag records whether the question was actually put, and the renderer
    says which case it is looking at.
    """
    pending = payload.get("pending") if isinstance(payload, dict) else None
    return {
        "asked": isinstance(pending, list),
        "mine": [{k: r.get(k) for k in KEEP if k in r}
                 for r in (pending or [])
                 if isinstance(r, dict) and r.get("asked_by") == for_plugin],
    }


def short(sec):
    try:
        sec = int(sec)
    except Exception:
        return "?"
    if sec >= 3600:
        return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"
    if sec >= 60:
        return f"{sec // 60}m"
    return f"{sec}s"


# The remedy the not-measured arms used to omit. Both arms named a DIAGNOSIS
# (which producer wrote this primer, why the read failed) and no ANSWER, so a
# member that wanted the number was left with "restart your watcher" — the one
# action a woken member structurally cannot take, because restarting its own
# watcher kills the wake that is reading the sentence. The read is one RPC and
# the fold is in this file; a member on any watcher vintage can answer the
# question for itself. Measured on CBP 2026-08-26 from a wake whose primer
# carried no key at all: count 0, `{"asked": true, "mine": []}`.
SELF_SERVE = ("You can answer it yourself without a restart: call "
              "`hestia_gate_pending_escalations` (session_id from `hestia_connect`) "
              "and pipe the response through `open-petitions.py fold <your plugin_id>` "
              "— `asked:true` with an empty `mine` is a MEASURED zero, which this "
              "line is not.")


def render(f):
    """The prompt block. Empty string when the member holds nothing."""
    if not isinstance(f, dict):
        return ""
    if not f.get("asked"):
        # The read failed, or the WATCHER predates this fold. Say so: "you hold
        # none" is a claim and this is not evidence for it — the same
        # absence-read-as-pass the primer's own ownership stamp exists to stop.
        #
        # And say WHICH, because the two want opposite responses and the primer
        # asserted the first for both. Measured on CBP 2026-08-26: the claude and
        # kimi watchers were executing a8dccda (2026-08-06), which has no fold at
        # all, so every wake read "the pending-escalations read failed" about a
        # read that was never attempted — a false cause, stated flatly, in the one
        # surface a woken member is guaranteed to read. The discriminator is on
        # disk and costs nothing: a watcher too old to fold writes NO
        # `open_petitions` key, while a failed read writes `asked:false`.
        # See tools/process_vintage.py for why the watcher's vintage is not
        # something you can read off /proc.
        if f.get("_absent"):
            # Say what the ARTIFACT shows and stop. Key-absence dates THIS PRIMER's
            # producer, not the watcher now running, and codex named two live
            # counterexamples on PR #634: a retained primer written by the old watcher
            # is retried AFTER a restart, so a fully current watcher can launch a
            # keyless one; and the current watcher's own composition fallback
            # (`... || echo "$OUT" > "$PRIMER"`) emits a keyless primer when the final
            # step fails. Both make "your watcher predates the fold" a cause the
            # artifact does not entail — the same overclaim-from-absence this branch
            # exists to stop, committed by the branch itself.
            return ("Open petitions: NOT MEASURED this wake — this primer carries no "
                    "`open_petitions` key, so the read was never attempted for it. "
                    "That dates the primer's PRODUCER (a watcher without the fold, or "
                    "a composition fallback), not necessarily the watcher running now; "
                    "`tools/process_vintage.py units` is what tells them apart. This "
                    "is not evidence that you hold none. " + SELF_SERVE)
        return ("Open petitions: NOT MEASURED this wake (the pending-escalations "
                "read failed) — this is not evidence that you hold none. " + SELF_SERVE)
    mine = f.get("mine") or []
    if not mine:
        return ""
    out = ["Petitions YOU have open (nothing else tells you these exist; the id "
           "is printed once, into a refusal, in a wake that has usually ended):"]
    for r in mine:
        pp = r.get("peer_participation") or {}
        invited = pp.get("invited") or []
        auto = ("gate-auto" if "did not choose to escalate" in str(r.get("stated_detail", ""))
                else "member-filed")
        # `bar` is NOT in the live `hestia_gate_pending_escalations` payload
        # (measured against the running daemon 2026-08-19) even though the
        # `opened` chain event has always carried it. Kept in KEEP so the block
        # improves for free if it is ever added, but rendered as absent rather
        # than as "?" — a placeholder in the slot where a bar goes reads as a bar
        # the reader failed to parse, not as a field the daemon never sent.
        tags = ([clean(r["bar"])] if r.get("bar") else []) + [auto]
        out.append(
            f"- {clean(r.get('escalation_id', ''))} "
            f"[{', '.join(tags)}] expires in "
            f"{short(r.get('secs_remaining'))}; {len(invited)} invited, "
            f"{pp.get('concurred', 0)} concurred, {pp.get('dissented', 0)} dissented; "
            f"marker={clean(r.get('marker', ''))} tool={clean(r.get('tool_name', ''))}")
        if r.get("stated_reason"):
            out.append(f"    for: {clean(r['stated_reason'])}")
    # The move, said out loud because the absence of a surface was only half the
    # defect. The other half is that the sanctioned action is not reachable from
    # the refusal text, which offers re-issue (a recast, scored below compliance)
    # and appeal (about the RULE, not this row) and nothing else.
    out.append(
        "You cannot rule your own (NOT-SAME). If the act is done, abandoned, or you "
        "recast around it, WITHDRAW — `hestia_gate_arbitrate_escalation` with "
        "approve:false and your session_id — which files `self_withdrawn`, claims no "
        "independence, needs no peer and counts toward no bar. Letting it lapse "
        "instead mints a record whose note says the deadline passed with no decision, "
        "which is false about a petition you had already made moot.")
    return "\n".join(out)


def main(argv):
    if len(argv) >= 3 and argv[1] == "fold":
        try:
            payload = json.load(sys.stdin)
        except Exception:
            payload = {}
        json.dump(fold(payload, argv[2]), sys.stdout)
        return 0
    if len(argv) >= 3 and argv[1] == "render":
        try:
            d = json.load(open(argv[2]))
            f = d.get("open_petitions") or {}
            # Key-ABSENT and asked:false are different facts about different
            # components — the watcher never folded, versus the daemon refused the
            # read — and only this line can still tell them apart. `render` gets a
            # dict either way, so the discriminator has to be carried, not inferred.
            if "open_petitions" not in d:
                f = dict(f, _absent=True)
        except Exception:
            return 0
        block = render(f)
        if block:
            print(block)
        return 0
    print(__doc__.strip().splitlines()[0], file=sys.stderr)
    print("usage: open-petitions.py fold <for_plugin> | render <primer.json>",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
