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
import os
import re
import sys

# The discriminator this file points a keyless wake at. It is named here rather
# than inline because the name and the check must not be able to drift apart:
# that drift is the defect this constant exists to close.
#
# `tools/process_vintage.py` has never been on main. It is PR #634, opened
# 2026-08-26T09:28:50Z and still open and CLEAN 185 h later; the sentence that
# tells a member to run it merged the SAME DAY, 2026-08-26T20:14:26Z (#642).
# The advice landed, the referent did not, and nothing noticed for a week
# because the suite pinned the STRING and not the thing it names:
#
#     check("B1c key-absent points at the tool that DOES discriminate them",
#           "process_vintage.py units" in out_absent, ...)
#
# That check is green against a box where the tool does not exist. A member
# reading `run X` for an absent X spends its wake finding that out, in the one
# surface it is guaranteed to read — and this is the not-measured arm, so the
# reader is already being told it cannot see something. Name the tool when it
# resolves; say it is unavailable when it does not. If #634 merges, the
# sentence comes back on its own with no edit here.
VINTAGE_TOOL = "tools/process_vintage.py"
_REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir))


def vintage_hint(present=None):
    """The clause naming the vintage discriminator, or saying it is absent.

    `present` is injectable so BOTH arms are exercised by the suite on a box
    where only one of them is reachable — a test that can only ever see the
    local truth pins the box, not the behaviour.
    """
    if present is None:
        present = os.path.exists(os.path.join(_REPO_ROOT, VINTAGE_TOOL))
    if present:
        return "`%s units` is what tells them apart. " % VINTAGE_TOOL
    return ("The tool that would date the RUNNING watcher (`%s`) is not on this "
            "box — do not spend the wake looking for it. " % VINTAGE_TOOL)


# The raw drain response, which is what `... || echo "$OUT" > "$PRIMER"` writes
# when the composition step fails. `evicted` was added later than the rest, so an
# older raw drain is the same shape minus that key — subset, not equality.
_DRAIN_KEYS = frozenset(("evicted", "notices", "peeked", "total"))
# Keys only a COMPOSED primer can carry: the composer is the only writer of
# either. `for_plugin` landed 07-31 (3fc5088), `unanswered` before it.
_COMPOSED_KEYS = frozenset(("unanswered", "for_plugin"))


def producer_from_keys(keys):
    """What this primer's KEY SET says about the process that wrote it.

    A different question from `vintage_hint`, and worth saying out loud because
    the block above runs them together: the key set dates the PRODUCER OF THIS
    ARTIFACT, which is on disk and free; `process_vintage.py` dates the WATCHER
    RUNNING NOW, which is neither. Codex's counterexamples on #634 are exactly
    the gap between those two — a current watcher re-fires a primer an old one
    wrote — so answering the artifact question does not answer the process one,
    and neither substitutes for the other.

    Returns None on a shape this cannot read. Saying nothing is the point: the
    branch this lives in exists to stop absence being read as a verdict, and a
    renderer that guesses commits that error one layer down.
    """
    keys = set(keys or ())
    if keys & _COMPOSED_KEYS:
        # The composer RAN — it is the only writer of these — and still emitted no
        # `open_petitions`. That is not a fallback and not a failed read: it dates
        # the writer to after the debt fold and before the petitions fold
        # (`ced61ba`, 08-19). This is the one arm the artifact settles on its own.
        return ("This primer carries the debt fold, which only the composer "
                "writes, so composition SUCCEEDED and still produced no key: its "
                "producer predates the petitions fold (2026-08-19), whatever is "
                "running now. ")
    if keys <= _DRAIN_KEYS and {"notices", "total"} <= keys:
        # The raw drain response, verbatim. Two producers write exactly this and
        # the artifact cannot separate them: the composition fallback of a current
        # watcher, and a watcher old enough never to have composed at all. Name
        # both; a restart fixes the second and does nothing for the first.
        return ("This primer is the raw drain response and nothing else, so no "
                "composer output reached it — either the composition fallback "
                "fired (see #858, the fold exceeds the exec argument limit) or "
                "this producer never folded at all. The artifact does not "
                "separate those two. ")
    return None

# What survives into the primer. `stated_reason` is the SEAT HOOK's truncation of
# the refused command, not the daemon's — the daemon stores whatever it is handed,
# verbatim and uncapped (`optional_string`, handler.rs). The cap is `s[:220]` in
# claude-code's `pre_tool_use.py` and `limit=400` in kimi's and codex's, so the
# same act renders at three different lengths and only one seat's rows are cut.
# Said wrongly here since this file was written, and it points a reader at the
# wrong layer to fix: there is nothing to change in the daemon (#627).
# `stated_detail` is kept only because its wording is the one available
# discriminator between a gate-auto-minted petition and one the member chose to
# file, and those two want different responses.
KEEP = ("escalation_id", "secs_remaining", "marker", "tool_name", "opened_at",
        "stated_reason", "stated_detail", "peer_participation", "bar",
        "host_session_id")

clean = lambda s: re.sub(r"[\x00-\x1f\x7f]", "", str(s))[:400]


def read_own_sessions(path):
    """The ledger of host sessions THIS watcher has fired: one id per line, first
    whitespace-separated token (fire-*.sh appends `<uuid> <stamp> <primer>`).

    None (not an empty set) when there is no ledger: "this watcher never recorded
    which sessions it fired" and "this watcher fired none" are different facts,
    and only the second licenses calling a same-name row a co-seat's.
    """
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            ids = {ln.split()[0] for ln in fh if ln.strip()}
    except Exception:
        return None
    return ids


def fold(payload, for_plugin, own_sessions=None):
    """Filter a pending-escalations response down to one member's rows.

    `asked` is NOT derivable from `mine` being empty: a failed RPC and a member
    that holds nothing are the same empty list, and they want opposite readings.
    So the flag records whether the question was actually put, and the renderer
    says which case it is looking at.

    `mine` versus `co_seat` (#732). `asked_by` is a plugin NAME, and on every box
    two processes answer to it: the interactive session and the mesh-fired wake.
    A row is this seat's only if its `host_session_id` is one this watcher fired
    (`own_sessions`). A same-name row with a host session NOT in that set is a
    co-seat's — live, possibly being polled that second — and goes under
    `co_seat`, which the renderer never tells the reader to withdraw. Measured
    on CBP 2026-09-06: two consecutive wakes were told to withdraw petitions the
    interactive seat had open; one was approved by the operator 2 min after the
    primer said to withdraw it.

    Degrades toward the OLD reading, never past it: with no ledger, or a row the
    daemon sent without `host_session_id`, the row stays in `mine`, tagged
    `seat: "unknown"` so the renderer can say the discriminator was absent rather
    than assert ownership it did not measure.
    """
    pending = payload.get("pending") if isinstance(payload, dict) else None
    mine, co_seat = [], []
    for r in (pending or []):
        if not (isinstance(r, dict) and r.get("asked_by") == for_plugin):
            continue
        row = {k: r.get(k) for k in KEEP if k in r}
        hsid = r.get("host_session_id")
        if own_sessions is None or not hsid:
            row["seat"] = "unknown"
            mine.append(row)
        elif hsid in own_sessions:
            row["seat"] = "mine"
            mine.append(row)
        else:
            row["seat"] = "co-seat"
            co_seat.append(row)
    return {"asked": isinstance(pending, list), "mine": mine, "co_seat": co_seat}


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
#
# Name the CLI route too, and name its `--json` flag. A mesh wake frequently has
# no `hestia_*` MCP surface at all (findings/review-7125-7138.md, review-7185.md),
# so the member reaches for `hestia gate pending` — whose DEFAULT output is a
# human-readable table. Piping that to the fold yields `{"asked": false}`, which
# is this file's signal for THE READ FAILED. So a member that follows this advice
# on the CLI without `--json` is handed a false "could not measure" that is
# indistinguishable from the real thing, having just measured successfully.
# Walked into on CBP 2026-09-03 by the member reading this very block.
SELF_SERVE = ("You can answer it yourself without a restart: call "
              "`hestia_gate_pending_escalations` (session_id from `hestia_connect`) "
              "and pipe the response through `open-petitions.py fold <your plugin_id>` "
              "— `asked:true` with an empty `mine` is a MEASURED zero, which this "
              "line is not. With no MCP surface, the CLI route is "
              "`hestia gate pending --as <your plugin_id> --json` — and the "
              "`--json` is load-bearing: without it you pipe a TABLE and get "
              "`asked:false`, a read failure that never happened.")


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
        # something you can read off /proc — when that tool is actually here.
        # It is not on main (PR #634, open since 2026-08-26); `vintage_hint`
        # is what keeps this branch from prescribing it regardless.
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
                    "a composition fallback), not necessarily the watcher running now. "
                    + (producer_from_keys(f.get("_keys")) or "") + vintage_hint() +
                    "This is not evidence that you hold none. " + SELF_SERVE)
        return ("Open petitions: NOT MEASURED this wake (the pending-escalations "
                "read failed) — this is not evidence that you hold none. " + SELF_SERVE)
    mine = f.get("mine") or []
    co_seat = f.get("co_seat") or []
    if not mine and not co_seat:
        return ""
    if not mine:
        return render_co_seat(co_seat)
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
        if r.get("seat") == "unknown":
            # The discriminator was absent (no ledger, or a daemon that predates
            # the field). Say so on the row: "yours" is then a name-match, and a
            # name is shared with the interactive seat on this box (#732).
            out.append("    seat: UNKNOWN — matched on plugin name only; the "
                       "interactive session on this box answers to the same name. "
                       "Read the `gate_escalation_opened` event's host_session_id "
                       "from the chain before withdrawing.")
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
    if co_seat:
        out.append(render_co_seat(co_seat))
    return "\n".join(out)


def render_co_seat(rows):
    """Same plugin name, a DIFFERENT host session: a sibling process's petition.

    Rendered so the reader knows the row exists (a wake that also touches the
    same governed path will otherwise collide with it) and knows it is NOT its
    own to withdraw. No WITHDRAW paragraph here — that instruction, applied to a
    row in this block, kills a petition the sibling is polling (#732).
    """
    out = ["Petitions open under YOUR PLUGIN NAME by a CO-SEAT (a different host "
           "session — usually the interactive session on this box). NOT yours: do "
           "not withdraw, arbitrate, or re-issue these; the owner is waiting on them."]
    for r in rows:
        out.append(
            f"- {clean(r.get('escalation_id', ''))} host_session="
            f"{clean(r.get('host_session_id', ''))[:8]} expires in "
            f"{short(r.get('secs_remaining'))}; marker={clean(r.get('marker', ''))} "
            f"tool={clean(r.get('tool_name', ''))}")
        if r.get("stated_reason"):
            out.append(f"    for: {clean(r['stated_reason'])}")
    return "\n".join(out)


def main(argv):
    if len(argv) >= 3 and argv[1] == "fold":
        try:
            payload = json.load(sys.stdin)
        except Exception:
            payload = {}
        # Optional 3rd positional: the watcher's wake-session ledger (#732).
        own = read_own_sessions(argv[3]) if len(argv) >= 4 else None
        json.dump(fold(payload, argv[2], own), sys.stdout)
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
                # Carry the primer's KEY SET, not just the absence flag. The
                # renderer is handed the fold, and the fold is precisely the thing
                # that is missing here — the evidence that dates the producer is in
                # the envelope, one level up, and is lost unless it is passed down.
                f = dict(f, _absent=True, _keys=sorted(d))
        except Exception:
            return 0
        block = render(f)
        if block:
            print(block)
        return 0
    print(__doc__.strip().splitlines()[0], file=sys.stderr)
    print("usage: open-petitions.py fold <for_plugin> [own_sessions_file] | render <primer.json>",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
