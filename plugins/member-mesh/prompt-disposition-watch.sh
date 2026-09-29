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
# authority) and print disposition-kind notices THIS SESSION has not been shown. Silent when
# there is nothing new. FAIL-OPEN ALWAYS: every path exits 0; session-mesh-inbox.sh owns
# shouting about a dark inbox. UserPromptSubmit can block on some harnesses, and exiting 0 on
# every path is what keeps this hook incapable of doing so.
#
# WHO HAS SEEN IT IS PER SESSION, NOT PER MEMBER (GPT's hold on #1148). A notice is addressed
# to a plugin id, and every claude-code seat on a box shares one. The first cut kept one
# watermark per member, so the first sibling to prompt advanced it for everyone, and the
# session that actually asked was shown nothing. Reproduced with two sessions, sibling first.
# Presentation is now recorded per (member, session_id), read from the hook event on stdin.
# Claude Code, Kimi (its hook runner passes sessionId on UserPromptSubmit) and Codex (session_id
# is required in user-prompt-submit.command.input) all send it. The file name is a hash of the
# id, so an id never becomes a path.
#
# A NEW SESSION'S BASELINE. Adopting "everything up to the current max" on the first prompt
# would hide a disposition that landed before this session's first WATCHED prompt: the watch
# installed mid-session, a pruned watermark, a resumed session. So the first run surfaces
# dispositions queued within LOOKBACK seconds (default 900: the 600 s claim window plus the
# ~2m18s measured delivery latency, with margin) and records the current max. Anything older
# could not be claimed anyway, and showing it would retro-surface history on every new session.
# A session asks only after it has started, so the ordinary case (fresh session, then ask,
# then ruling) needs no look-back at all. It is there for the cases where the watch was not
# yet looking when the ruling landed.
#
# NO USABLE SESSION ID -> RECORD NOTHING. Marking a shared watermark would mark another
# session's delivery complete. Such a run prints the look-back window's dispositions, records
# nothing, and says the line will repeat.
#
# Per-session files older than TTL days (default 7) are pruned on each run.
#
# THE ADVICE. It never says "hestia gate poll <id>": poll arms the asker's claim fuse by
# plugin-id equality (#732, #707), so on a shared id it burns a sibling's window. Measured
# 2026-09-18: 6 of 6 dispositions delivered to claude-code belonged to a co-seat. The notice
# says the ruling may be a co-seat's and names the fuse-safe read (the pointer, via MCP
# resources/read), which still cannot say WHICH seat asked (#1060). The authoritative,
# session-addressed delivery is PRD_DISPOSITION_DELIVERY R4 / #849; this is the interim.
#
# Env: HESTIA_MESH_PLUGIN (required, pinned on the hook's command line; unset = silent),
#      HESTIA_MESH_STATE, HESTIA_DISPOSITION_LOOKBACK_S, HESTIA_DISPOSITION_SEEN_TTL_DAYS.

[ -n "${HESTIA_MESH_PLUGIN:-}" ] || exit 0
DISPWATCH_DIR="$(dirname "$0")" python3 -c '
import datetime, hashlib, json, os, re, subprocess, sys, time

member = os.environ["HESTIA_MESH_PLUGIN"]
state = os.environ.get("HESTIA_MESH_STATE") or os.path.join(
    os.path.expanduser("~"), ".local", "state", "hestia-mesh")
seen_dir = os.path.join(state, "disposition-seen", member)

def num(name, default):
    try:
        v = float(os.environ.get(name, ""))
        return v if v >= 0 else default
    except ValueError:
        return default

lookback = num("HESTIA_DISPOSITION_LOOKBACK_S", 900.0)
ttl = num("HESTIA_DISPOSITION_SEEN_TTL_DAYS", 7.0) * 86400

try:
    event = json.loads(sys.stdin.read() or "{}")
except Exception:
    event = {}
sid = event.get("session_id") if isinstance(event, dict) else None
sid = sid if isinstance(sid, str) and sid.strip() else None

try:
    r = subprocess.run([sys.executable, os.path.join(os.environ["DISPWATCH_DIR"], "hestia-mesh.py"),
                        "peek"], capture_output=True, text=True, timeout=5)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit(0)
    notices = json.loads(r.stdout).get("notices") or []
except Exception:
    sys.exit(0)
notices = [n for n in notices if isinstance(n, dict) and isinstance(n.get("id"), int)]

def age_s(n):
    """Seconds since the notice was queued; None when the stamp is unreadable."""
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?(Z|[+-]\d\d:\d\d)$",
                 str(n.get("queued_at") or ""))
    if not m:
        return None
    try:
        t = datetime.datetime.fromisoformat(m.group(1) + ("+00:00" if m.group(2) == "Z" else m.group(2)))
    except ValueError:
        return None
    return time.time() - t.timestamp()

def recent(n):
    a = age_s(n)
    return a is not None and a <= lookback

try:
    now = time.time()
    for f in os.listdir(seen_dir):
        p = os.path.join(seen_dir, f)
        if now - os.path.getmtime(p) > ttl:
            os.remove(p)
except OSError:
    pass

disps = [n for n in notices if n.get("kind") == "disposition"]
wm_file = os.path.join(seen_dir, hashlib.sha256(sid.encode()).hexdigest()[:24]) if sid else None
wm = None
if wm_file:
    try:
        wm = int(open(wm_file).read().strip())
    except Exception:
        wm = None
new = [n for n in disps if (n["id"] > wm if wm is not None else recent(n))]

if wm_file:
    top = max([n["id"] for n in notices] + [wm if wm is not None else 0])
    if top != wm:
        try:
            os.makedirs(seen_dir, exist_ok=True)
            with open(wm_file, "w") as f:
                f.write(str(top))
        except OSError:
            pass
if not new:
    sys.exit(0)

print("=== HESTIA: %d new disposition(s) for %s since this session last looked (#366) ===" % (len(new), member))
for n in sorted(new, key=lambda n: n["id"]):
    print("  [disposition] %s" % (n.get("pointer_uri") or "(no pointer)"))
print("A petition filed under this member id was RULED. It may be a co-seat\x27s: seats on one box")
print("share an id. If it is an approval of YOUR refused act, re-issue that exact act now to claim")
print("it; the claim window is burning. To read a ruling without touching that window, resolve the")
print("pointer (MCP resources/read). Do not check with gate poll: it starts the asker\x27s window (#732).")
if not wm_file:
    print("(This hook event carried no session id, so nothing was recorded as seen: these lines will")
    print("repeat while the ruling is recent. Marking them seen would hide them from other sessions.)")
' 2>/dev/null
exit 0
