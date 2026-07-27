#!/usr/bin/env bash
# Deploy the hestia gemini governance adapter for a live gemini-cli member.
#
# Copies the gate + its shared lib to EXT4 (the only fail-open surface on gemini's engine is a hook
# TIMEOUT, and a 9p /mnt/c cold-load can exceed it), seeds the member identity + standing law, and
# wires the BeforeTool gate into ~/.gemini/settings.json at USER level (project-source hooks are gated
# behind isTrustedFolder()). Idempotent: re-run to redeploy after the repo changes.
#
# Usage: install.sh [WORKSPACE] [EXT4_DEST]
#   WORKSPACE  repo root the member is granted within (default: /mnt/c/exe/projects/ai-agents)
#   EXT4_DEST  ext4 dir to hold the runnable copy      (default: ~/.gemini/hestia-plugins)
set -euo pipefail

WORKSPACE="${1:-/mnt/c/exe/projects/ai-agents}"
EXT4_DEST="${2:-$HOME/.gemini/hestia-plugins}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"          # hestia/plugins
GEMINI_HOME="$HOME/.gemini"
GOVERNOR="$WORKSPACE/hestia/plugins/claude-code/hooks/pre_tool_use.py"

echo "[install] source=$SRC  workspace=$WORKSPACE  ext4=$EXT4_DEST"
[ -f "$GOVERNOR" ] || { echo "[install] FATAL: society governor not found at $GOVERNOR" >&2; exit 1; }

# 1. Copy gate + instance + shared lib to ext4, preserving the gate's ../../lib import structure.
mkdir -p "$EXT4_DEST/gemini/hooks" "$EXT4_DEST/gemini/instance" "$EXT4_DEST/lib"
cp "$SRC/gemini/hooks/before_tool.py" "$SRC/gemini/hooks/observe.sh" "$SRC/gemini/hooks/hydrate.sh" "$EXT4_DEST/gemini/hooks/"
cp "$SRC/gemini/instance/identity.seed.json" "$EXT4_DEST/gemini/instance/"
cp "$SRC/lib/path_scope.py" "$EXT4_DEST/lib/"
chmod +x "$EXT4_DEST/gemini/hooks/"*.sh "$EXT4_DEST/gemini/hooks/before_tool.py"
echo "[install] gate+lib copied to ext4"

# 2. Seed the live member identity (do NOT clobber an existing live one - it accrues state).
mkdir -p "$GEMINI_HOME/hestia-instance"
if [ ! -f "$GEMINI_HOME/hestia-instance/identity.json" ]; then
  cp "$SRC/gemini/instance/identity.seed.json" "$GEMINI_HOME/hestia-instance/identity.json"
  echo "[install] seeded identity.json (member #3, web4-scoped, honest 0.5 T3)"
else
  echo "[install] identity.json already present - left as-is (keeps accrued state)"
fi

# 3. Standing law where gemini reads it natively.
cp "$SRC/gemini/GEMINI.md" "$GEMINI_HOME/GEMINI.md"
echo "[install] GEMINI.md deployed to $GEMINI_HOME"

# 4. Merge the hooks block into settings.json (USER level), pinning hooksConfig.enabled.
GATE="HESTIA_WORKSPACE=$WORKSPACE HESTIA_SOCIETY_GATE=$GOVERNOR python3 $EXT4_DEST/gemini/hooks/before_tool.py"
OBS="$EXT4_DEST/gemini/hooks/observe.sh"
HYD="HESTIA_WORKSPACE=$WORKSPACE $EXT4_DEST/gemini/hooks/hydrate.sh"
SETTINGS="$GEMINI_HOME/settings.json" GATE="$GATE" OBS="$OBS" HYD="$HYD" python3 - <<'PY'
import json, os
p = os.environ["SETTINGS"]
try:
    cfg = json.load(open(p))
except Exception:
    cfg = {}
cfg.setdefault("hooksConfig", {})["enabled"] = True   # a one-line kill-switch; pin it ON explicitly
cfg["hooks"] = {
    "BeforeTool":  [{"matcher": ".*", "hooks": [{"type": "command", "command": os.environ["GATE"], "timeout": 15000}]}],
    "SessionStart":[{"hooks": [{"type": "command", "command": os.environ["OBS"], "timeout": 15000}]}],
    "AfterTool":   [{"matcher": ".*", "hooks": [{"type": "command", "command": os.environ["OBS"], "timeout": 10000}]}],
    "SessionEnd":  [{"hooks": [{"type": "command", "command": os.environ["HYD"], "timeout": 20000}]}],
}
json.dump(cfg, open(p, "w"), indent=2)
print(f"[install] wrote hooks + hooksConfig.enabled=true to {p}")
PY

echo "[install] DONE. Gate is wired at USER level on ext4."
echo "[install] NEXT (operator): authenticate gemini-cli once ('gemini' then follow the Google login),"
echo "[install]       then a BeforeTool call will run this gate. Governor: $GOVERNOR (hestia daemon must be up)."
