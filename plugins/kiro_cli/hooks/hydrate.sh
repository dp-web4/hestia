#!/usr/bin/env sh
# Hestia Phase-0 identity hydration for a session-ephemeral member (Kiro CLI). On Stop: seed the live
# identity.json from the plugin seed if absent. Fire-and-forget, ALWAYS exit 0. (Full state-rewrite +
# in_scope regeneration from the public repo registry mirrors the codex hydrate - tracked follow-up.)
IDIR="${HESTIA_KIRO_INSTANCE_DIR:-${KIRO_HOME:-$HOME/.kiro}/hestia-instance}"
SEED="${KIRO_PLUGIN_ROOT:-$(dirname "$0")/..}/instance/identity.seed.json"
mkdir -p "$IDIR" 2>/dev/null
[ -f "$IDIR/identity.json" ] || cp "$SEED" "$IDIR/identity.json" 2>/dev/null
cat > /dev/null   # drain the Stop event on stdin
exit 0
