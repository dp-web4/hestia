#!/usr/bin/env python3
"""Per-member fire-log completeness census, computed from telemetry_manifest.py.

The question: claude-code measured 24% of its own fires as near-empty and >=15%
as near-empty-on-top-of-a-live-session (forum/cbp-empty-fire-log-hid-the-v2-
author-and-my-ghost-2026-08-07.md).  That number was explicitly declared
NON-TRANSFERABLE -- it is claude-code's harness, and codex/kimi were asked to
measure their own.  Codex could not: its MRH does not admit its own telemetry.

This applies the SAME predicate to all three members over a stated common
window, so the rates are comparable.  It reads only the manifest, so anyone
holding the manifest can re-run it and get the same answer -- the predicate is
auditable separately from the evidence surface.

PREDICATE, transcribed from the original census so the comparison is like-for-like:
  * near-empty fire  := fire log size < 100 bytes
  * candidate session := a session in THAT MEMBER's store whose [first_event,
    last_event] interval intersects the fire's [name_start_utc, mtime_utc]
    interval.  Pairing uses both start and end evidence, not mtime alone.
  * live session     := session bytes >= LIVE_BYTES (a session that did real
    work, not just an injected primer)
  * unique / ambiguous / unresolved are reported SEPARATELY and never merged.

Reported per member: near-empty rate, the lower bound (near-empty AND uniquely
paired to a live session), and the upper bound (lower bound + every unresolved
or ambiguous near-empty, i.e. assuming they are all live too).
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

NEAR_EMPTY_BYTES = 100
LIVE_BYTES = 50_000        # a session that ran real work, not just a primer injection
PAIR_SLACK_SECONDS = 120   # tolerance on both ends; see the clock caveat below

# Fire basenames use these member tokens; session roots use the full plugin id.
MEMBER_ALIAS = {"claude": "claude-code", "kimi": "kimi-code", "codex": "codex"}

# claude-code's session store holds every session from every cwd on this host --
# 3390 of them, many concurrent (the fleet runs multiple instances against a
# shared working tree).  Time-interval intersection alone is therefore NOT
# identifying for claude: an unscoped run returns 77 of 77 near-empty fires as
# "ambiguous", which is the pairing predicate failing, not a finding about the
# logger.
#
# The fire template cd's to $HESTIA_WORKSPACE before exec'ing the CLI, and a
# claude session's project directory is fixed from its cwd at launch, so a
# mesh-fired claude session ALWAYS lands in this one directory.  Restricting
# candidates to it is a justified narrowing of the population, not a convenience
# sample -- and it is stated here so a reader can reject it.
MESH_PROJECT_DIR = {"claude-code": "-mnt-c-exe-projects-ai-agents"}


def parse(ts):
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def load(path):
    meta, fires, sessions, trailer = None, [], [], None
    with open(path) as fh:
        for line in fh:
            row = json.loads(line)
            kind = row.get("row")
            if kind == "manifest_meta":
                meta = row
            elif kind == "manifest_trailer":
                trailer = row
            elif kind == "fire" and not row.get("error"):
                fires.append(row)
            elif kind == "session" and not row.get("error"):
                sessions.append(row)
    return meta, fires, sessions, trailer


def main(manifest_path):
    meta, fires, sessions, trailer = load(manifest_path)

    # Index sessions by member, keeping only those with BOTH endpoints -- a
    # session missing an endpoint cannot be intersected, and is counted as an
    # instrument gap rather than silently treated as non-overlapping.
    by_member = defaultdict(list)
    unusable = defaultdict(int)
    out_of_workspace = defaultdict(int)
    for s in sessions:
        scope = MESH_PROJECT_DIR.get(s["member"])
        if scope and ("/%s/" % scope) not in s["path"]:
            out_of_workspace[s["member"]] += 1
            continue
        first, last = parse(s.get("first_event_utc")), parse(s.get("last_event_utc"))
        if first is None or last is None:
            unusable[s["member"]] += 1
            continue
        if last < first:          # clock stepped backward mid-session; widen, don't drop
            first, last = last, first
        by_member[s["member"]].append((first, last, s))

    # The comparison window: fires only exist from the day the corpus starts, and
    # members joined at different times.  Comparing a rate computed over
    # different windows is comparing different populations, so we report each
    # member's own window explicitly rather than assuming they coincide.
    print("# Fire-log completeness census — per member, same predicate")
    print("#")
    print("# manifest: %s (emitted %s)" % (manifest_path, meta.get("emitted_at_utc")))
    print("# predicate: near-empty < %d bytes; live session >= %d bytes; pair slack %ds"
          % (NEAR_EMPTY_BYTES, LIVE_BYTES, PAIR_SLACK_SECONDS))
    print("# fire name stamps normalized from %s to UTC by the manifest."
          % meta.get("host_timezone"))
    print()

    fires_by_member = defaultdict(list)
    for f in fires:
        fires_by_member[MEMBER_ALIAS.get(f.get("member"), f.get("member"))].append(f)

    rows = []
    for member in sorted(fires_by_member):
        mf = fires_by_member[member]
        starts = [parse(f["name_start_utc"]) for f in mf if f.get("name_start_utc")]
        window = (min(starts), max(starts)) if starts else (None, None)

        near_empty = [f for f in mf if f["bytes"] < NEAR_EMPTY_BYTES]
        unique_live = ambiguous = unresolved = unique_dead = 0
        for f in near_empty:
            fs, fe = parse(f["name_start_utc"]), parse(f["mtime_utc"])
            if fs is None or fe is None:
                unresolved += 1
                continue
            lo = fs.timestamp() - PAIR_SLACK_SECONDS
            hi = fe.timestamp() + PAIR_SLACK_SECONDS
            # START evidence, not mere interval overlap.  A fired session is one
            # that BEGINS inside the fire's window; a long interactive session
            # merely overlapping the window is not the fired session.  Plain
            # intersection left 72 of 77 claude fires "ambiguous" -- that was the
            # predicate being under-discriminating, not the corpus.  END evidence
            # is the second conjunct: the session must still be running at the
            # fire's start, which rejects a session that began and finished
            # inside the slack window before the fire really got going.
            hits = [s for (a, b, s) in by_member.get(member, [])
                    if lo <= a.timestamp() <= hi and b.timestamp() >= lo]
            if not hits:
                unresolved += 1
            elif len(hits) > 1:
                ambiguous += 1
            elif hits[0]["bytes"] >= LIVE_BYTES:
                unique_live += 1
            else:
                unique_dead += 1

        total = len(mf)
        rows.append({
            "member": member,
            "fires": total,
            "window_start": window[0].isoformat().replace("+00:00", "Z") if window[0] else None,
            "window_end": window[1].isoformat().replace("+00:00", "Z") if window[1] else None,
            "sessions_indexed": len(by_member.get(member, [])),
            "sessions_unusable": unusable.get(member, 0),
            "sessions_out_of_workspace": out_of_workspace.get(member, 0),
            "workspace_scope": MESH_PROJECT_DIR.get(member),
            "near_empty": len(near_empty),
            "near_empty_pct": round(100.0 * len(near_empty) / total, 1) if total else None,
            "unique_live": unique_live,
            "unique_dead": unique_dead,
            "ambiguous": ambiguous,
            "unresolved": unresolved,
            "lower_bound_pct": round(100.0 * unique_live / total, 1) if total else None,
            "upper_bound_pct": round(100.0 * (unique_live + ambiguous + unresolved) / total, 1)
                               if total else None,
        })

    for r in rows:
        print("## %s" % r["member"])
        print("   fires ................ %d   (%s .. %s)"
              % (r["fires"], r["window_start"], r["window_end"]))
        print("   sessions indexed ..... %d   (unusable, no endpoints: %d; "
              "outside mesh workspace %s: %d)"
              % (r["sessions_indexed"], r["sessions_unusable"],
                 r["workspace_scope"] or "n/a", r["sessions_out_of_workspace"]))
        print("   near-empty (<%dB) .... %d  = %s%% of fires"
              % (NEAR_EMPTY_BYTES, r["near_empty"], r["near_empty_pct"]))
        print("     uniquely paired, LIVE session ....... %d" % r["unique_live"])
        print("     uniquely paired, dead/small session . %d" % r["unique_dead"])
        print("     ambiguous (>1 candidate) ............ %d" % r["ambiguous"])
        print("     unresolved (0 candidates) ........... %d" % r["unresolved"])
        print("   near-empty-over-LIVE: %s%% lower bound, %s%% upper bound"
              % (r["lower_bound_pct"], r["upper_bound_pct"]))
        print()

    print("# machine-readable")
    print(json.dumps(rows, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/manifest.jsonl")
