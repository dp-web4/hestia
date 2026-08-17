#!/usr/bin/env sh
# Hestia Phase-0 identity hydration — the persistence layer for a session-ephemeral member (Codex).
#
# SAGE pattern ("model is weather, identity is organism"): the member's reasoning substrate does not
# persist between sessions; continuity is carried entirely by local context files. This hook runs on
# SessionEnd and (1) updates the live identity.json (session count, timestamps, act count from the
# observation log), and (2) rewrites the dynamic STATE section of the deployed AGENTS.md between the
# HESTIA:STATE markers — so the NEXT session boots already knowing its own footprint. SessionEnd (not
# SessionStart) because the system prompt is assembled at boot: state written at end-of-session N is
# what session N+1 wakes up with.
#
# Same contract as observe.sh: fire-and-forget, ALWAYS exit 0, never interfere (observation layer).

IDIR="${HESTIA_CODEX_INSTANCE_DIR:-${CODEX_HOME:-$HOME/.codex}/hestia-instance}"
OBS="${HESTIA_OBSERVE_DIR:-${CODEX_HOME:-$HOME/.codex}/hestia-observe}/observe.jsonl"
AGENTS="${HESTIA_CODEX_AGENTS_MD:-${CODEX_HOME:-$HOME/.codex}/AGENTS.md}"
SEED="${CODEX_PLUGIN_ROOT:-$(dirname "$0")/..}/instance/identity.seed.json"

_HESTIA_EV="$(cat)"   # SessionEnd event JSON on stdin (session_id, cwd, ...)
export _HESTIA_EV

mkdir -p "$IDIR" 2>/dev/null
[ -f "$IDIR/identity.json" ] || cp "$SEED" "$IDIR/identity.json" 2>/dev/null

python3 - "$IDIR/identity.json" "$OBS" "$AGENTS" <<'PY' 2>/dev/null
import json, sys, os, datetime
ident_p, obs_p, agents_p = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    ev = json.loads(os.environ.get("_HESTIA_EV", "{}"))
except Exception:
    ev = {}
sid = ev.get("session_id", "unknown")

ident = json.load(open(ident_p, encoding="utf-8"))
now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

# count this session's observed acts (skip-and-count malformed lines — never die)
acts = 0
try:
    for line in open(obs_p, encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
            if r.get("session_id") == sid and r.get("hook_event_name") == "PostToolUse":
                acts += 1
        except Exception:
            pass
except FileNotFoundError:
    pass

ident["session_count"] = ident.get("session_count", 0) + 1
ident["first_session"] = ident.get("first_session") or now
ident["last_session"] = now
ident.setdefault("sessions", []).append(
    {"n": ident["session_count"], "id": sid, "ended": now, "acts_observed": acts})
ident["sessions"] = ident["sessions"][-50:]  # bounded

# This hook owns continuity only. It must not derive or mutate authorization
# from a repository inventory. Scope is supplied by the daemon's vault-backed
# policy snapshot; the identity file is a bounded, non-authoritative replica.

json.dump(ident, open(ident_p, "w", encoding="utf-8"), indent=2)

# rewrite the dynamic state block in the deployed AGENTS.md (markers required; absent -> skip)
B, E = "<!-- HESTIA:STATE:BEGIN -->", "<!-- HESTIA:STATE:END -->"
state = f"""{B}
## Your footprint here (auto-updated at each session end — this IS your continuity)
- **Sessions in this role:** {ident['session_count']} (first {ident['first_session']}, last ended {ident['last_session']})
- **Phase:** {ident['phase']}  ·  **Role:** {ident['role']}  ·  acts observed last session: {acts}
- **Live identity file:** `~/.codex/hestia-instance/identity.json` — read it to recall your history; milestones and session records are there.
- **Facts your trained self-model gets wrong:** (1) you HAVE a native hook system (Claude-Code-lineage: PreToolUse/PostToolUse/SessionStart/SessionEnd/Stop/... — enabled via `[features] codex_hooks = true`). This scaffold runs on it. (2) Your `PreToolUse` gate covers the SHELL tool ONLY; the filesystem boundary for out-of-scope repos is the sandbox (`sandbox_mode = "workspace-write"`), not the hook. Don't re-derive these errors.
{E}"""
try:
    s = open(agents_p, encoding="utf-8").read()
    if B in s and E in s:
        s = s[:s.index(B)] + state + s[s.index(E) + len(E):]
        open(agents_p, "w", encoding="utf-8").write(s)
except FileNotFoundError:
    pass
PY
exit 0
