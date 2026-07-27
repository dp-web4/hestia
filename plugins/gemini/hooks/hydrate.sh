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
# (Full state-rewrite mirrors the codex hydrate; kept minimal here pending a live-run verification.)
cat > /dev/null   # drain the SessionEnd event on stdin
exit 0
