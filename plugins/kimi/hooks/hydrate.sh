#!/usr/bin/env sh
# Hestia Phase-0 identity hydration — the persistence layer for a session-ephemeral member.
#
# SAGE pattern ("model is weather, identity is organism"): the member's reasoning substrate does not
# persist between sessions; continuity is carried entirely by local context files. This hook runs on
# SessionEnd and (1) updates the live identity.json (session count, timestamps, act count for the
# session from the observation log), and (2) rewrites the dynamic STATE section of the deployed
# AGENTS.md between the HESTIA:STATE markers — so the NEXT session boots already knowing its own
# footprint. SessionEnd (not SessionStart) because the system prompt is assembled at boot: state
# written at end-of-session N is what session N+1 wakes up with.
#
# Same contract as observe.sh: fire-and-forget, ALWAYS exit 0, never interfere (observation layer).

IDIR="${HESTIA_KIMI_INSTANCE_DIR:-${KIMI_CODE_HOME:-$HOME/.kimi-code}/hestia-instance}"
OBS="${HESTIA_OBSERVE_DIR:-${KIMI_CODE_HOME:-$HOME/.kimi-code}/hestia-observe}/observe.jsonl"
AGENTS="${HESTIA_KIMI_AGENTS_MD:-${KIMI_CODE_HOME:-$HOME/.kimi-code}/AGENTS.md}"
SEED="${KIMI_PLUGIN_ROOT:-$(dirname "$0")/..}/instance/identity.seed.json"

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

# Refresh the MRH base grant from the repo registry (dp 2026-07-21): base = ALL public repos +
# the granted private exceptions (shared-context), PLUS the launch cwd (handled live in the gate).
# PRESERVE accrued private grants (trust-earned widening) — recompute the public base, keep anything
# already granted into a private repo. Fail-soft: no readable registry -> leave in_scope untouched
# (seed default or prior). This is what makes the scope self-update fleet-wide on each hydrate.
PRIVATE_EXCEPTIONS = {"shared-context"}
REGISTRY = os.environ.get("HESTIA_REPO_REGISTRY") or os.path.join(
    os.environ.get("HESTIA_WORKSPACE", os.path.expanduser("~/ai-workspace")),
    "private-context", "infrastructure", "repos.jsonl")
try:
    public = set()
    for line in open(REGISTRY, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        name = r.get("name") or r.get("repo") or r.get("dir")
        vis = str(r.get("visibility") or r.get("access")
                  or ("public" if r.get("public") else "")).lower()
        if name and vis == "public":
            public.add(name)
    if public:  # only rewrite if the registry actually parsed public entries
        allowed_base = public | PRIVATE_EXCEPTIONS
        base = {f"repo:{n}" for n in allowed_base}
        cur = (ident.get("mrh", {}) or {}).get("in_scope", []) or []
        accrued = [s for s in cur if s.split(":", 1)[-1] not in allowed_base]  # trust-earned private grants
        ident.setdefault("mrh", {})["in_scope"] = sorted(base | set(accrued))
except FileNotFoundError:
    pass

json.dump(ident, open(ident_p, "w", encoding="utf-8"), indent=2)

# rewrite the dynamic state block in the deployed AGENTS.md (markers required; absent -> skip)
B, E = "<!-- HESTIA:STATE:BEGIN -->", "<!-- HESTIA:STATE:END -->"
state = f"""{B}
## Your footprint here (auto-updated at each session end — this IS your continuity)
- **Sessions in this role:** {ident['session_count']} (first {ident['first_session']}, last ended {ident['last_session']})
- **Phase:** {ident['phase']}  ·  **Role:** {ident['role']}  ·  acts observed last session: {acts}
- **Live identity file:** `~/.kimi-code/hestia-instance/identity.json` — read it to recall your history; your milestones and session records are there.
- **Fact your trained self-model gets wrong:** you HAVE a native hook system (16 events, PreToolUse/PostToolUse included). This scaffold runs on it. Don't re-derive the error.
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
