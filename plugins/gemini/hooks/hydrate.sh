#!/usr/bin/env sh
# Hestia Phase-0 identity hydration for a session-ephemeral member (Gemini CLI).
# SAGE pattern ("model is weather, identity is organism"): continuity lives in local context files,
# not the cloud substrate. On SessionEnd: (1) update the live identity.json (session count, act count
# from the observation log), (2) refresh the deployed GEMINI.md STATE block so the NEXT session boots
# knowing its footprint. Same contract as observe.sh: fire-and-forget, ALWAYS exit 0.
IDIR="${HESTIA_GEMINI_INSTANCE_DIR:-${GEMINI_HOME:-$HOME/.gemini}/hestia-instance}"
SEED="${GEMINI_PLUGIN_ROOT:-$(dirname "$0")/..}/instance/identity.seed.json"
mkdir -p "$IDIR" 2>/dev/null
[ -f "$IDIR/identity.json" ] || cp "$SEED" "$IDIR/identity.json" 2>/dev/null

# Derive mrh.in_scope from the repo registry at every session end (PR #157, property D;
# dp 2026-08-04: one semantic producer — the public inventory plus explicit per-install or
# earned grants; a frozen seed is bootstrap input, not an alternate permanent authority).
# Until this block existed this member's in_scope was a literal that had not moved since the
# seed was written — a second producer shape for a core field, and the 24-missing-entries
# incident's exact mechanism. Mirrors plugins/codex/hooks/hydrate.sh; fail-soft: no readable
# registry -> leave in_scope untouched, never die. The full session bookkeeping rewrite
# (counts, STATE block) remains pending a live-run verification.
python3 - "$IDIR/identity.json" <<'PY' 2>/dev/null
import json, sys, os
ident_p = sys.argv[1]
try:
    ident = json.load(open(ident_p, encoding="utf-8"))
except Exception:
    raise SystemExit(0)  # no readable identity (seed copy failed) -- leave it alone

PRIVATE_EXCEPTIONS = {"shared-context", "memory", "private-context"}
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
        accrued = [s for s in cur if s.split(":", 1)[-1] not in allowed_base]  # trust-earned grants
        ident.setdefault("mrh", {})["in_scope"] = sorted(base | set(accrued))
        json.dump(ident, open(ident_p, "w", encoding="utf-8"), indent=2)
except FileNotFoundError:
    pass
PY

cat > /dev/null   # drain the SessionEnd event on stdin
exit 0
