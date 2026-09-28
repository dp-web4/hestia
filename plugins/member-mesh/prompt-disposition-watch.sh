#!/usr/bin/env sh
# UserPromptSubmit hook (any member): surface NEW disposition notices mid-session (#366).
#
# PROVENANCE. Built by kimi-code on 2026-08-27 for #366 and run from its own hooks dir for a
# month; hestia never shipped it. Upstreamed here on 2026-09-28 (findings/per-harness-witness-
# drift-2026-09-28.md, recommendation 5): a seat building its own copy was the evidence that
# the gap is real, and a private copy is the part that should not last. Kimi's copy stays
# where it is until install.sh syncs this one over it.
#
# The gap this closes: SessionStart reads the mesh inbox ONCE; a live session never looks
# again. The daemon's disposition push works (measured 2026-08-27: decision -> primer in
# 1m34s-2m18s), but delivery is a file drop and consumption is next-wake, so an approval
# sat unread while its 600 s claim window burned, twice in one day, on two seats.
#
# This is the prompt-time sweep: PEEK (non-consuming; the wake cycle stays the drain
# authority), print only disposition-kind notices newer than the watermark, and advance the
# watermark. It prints one line per disposition, and nothing when there is nothing new.
#
# FAIL-OPEN ALWAYS: any failure exits 0 and prints nothing. session-mesh-inbox.sh already owns
# shouting about a dark inbox, and this hook's failure must never break a prompt.
# UserPromptSubmit can block on some harnesses; exiting 0 on every path is what keeps this
# hook incapable of doing so.
#
# CHANGED IN THE UPSTREAM (two things kimi's single-seat copy did not have to face):
#   1. The watermark is per member, not per harness home:
#      ${HESTIA_MESH_STATE:-~/.local/state/hestia-mesh}/disposition-watermark/<member>, the
#      same state root hestia-mesh.py uses for drained/ and sent/. One member's
#      watermark can no longer hide another member's dispositions.
#   2. The advice no longer says "poll: hestia gate poll <id>". Every claude-code seat on a box
#      shares one plugin_id, and poll arms the asker's claim fuse by name equality (#732, #707),
#      so on a shared id that advice burns a SIBLING's window. Measured 2026-09-18: 6 of 6
#      dispositions delivered to claude-code belonged to a co-seat. The notice now says that
#      the ruling may not be yours, and names the fuse-safe read (the pointer, via MCP
#      resources/read). That read serves the plugin id, not the session, so it still cannot
#      say WHICH seat asked (#1060). The hook states that limit rather than papering over it.
#      `gate pending` is no substitute: a ruled escalation is no longer listed there.
#
# Env: HESTIA_MESH_PLUGIN must be pinned on the hook's command line (no default: unset means
#      the CLI refuses, and this hook stays silent, as does every other failure).

DIR="$(dirname "$0")"
[ -n "${HESTIA_MESH_PLUGIN:-}" ] || exit 0
STATE="${HESTIA_MESH_STATE:-$HOME/.local/state/hestia-mesh}"
WM="$STATE/disposition-watermark/$HESTIA_MESH_PLUGIN"

OUT=$(python3 "$DIR/hestia-mesh.py" peek 2>/dev/null) || exit 0
[ -n "$OUT" ] || exit 0

printf '%s' "$OUT" | WM_FILE="$WM" python3 -c '
import json, os, sys

wm_file = os.environ["WM_FILE"]
try:
    notices = json.load(sys.stdin).get("notices") or []
except Exception:
    sys.exit(0)

def write_wm(value):
    try:
        os.makedirs(os.path.dirname(wm_file), exist_ok=True)
        with open(wm_file, "w") as f:
            f.write(str(value))
    except OSError:
        pass

try:
    wm = int(open(wm_file).read().strip())
except Exception:
    # First run: adopt the present as the baseline, so history does not retro-surface.
    # Written UNCONDITIONALLY (max id over ALL notices, else 0): an absent watermark would
    # silently swallow the first real disposition.
    ids = [n["id"] for n in notices if isinstance(n.get("id"), int)]
    write_wm(max(ids) if ids else 0)
    sys.exit(0)

new = [n for n in notices
       if n.get("kind") == "disposition" and isinstance(n.get("id"), int) and n["id"] > wm]
if not new:
    sys.exit(0)

member = os.environ.get("HESTIA_MESH_PLUGIN", "?")
print("=== HESTIA: %d new disposition(s) for %s since last check (#366) ===" % (len(new), member))
for n in sorted(new, key=lambda n: n["id"]):
    print("  [disposition] %s" % (n.get("pointer_uri") or "(no pointer)"))
print("A petition filed under this member id was RULED. It may be a co-seat\x27s: seats on one box")
print("share an id. If it is an approval of YOUR refused act, re-issue that exact act now to claim")
print("it; the claim window is burning. To read a ruling without touching that window, resolve the")
print("pointer (MCP resources/read). Do not check with gate poll: it starts the asker\x27s window (#732).")
write_wm(max(n["id"] for n in new))
' 2>/dev/null
exit 0
