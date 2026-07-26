#!/usr/bin/env bash
# Install the agent inventory on this machine, with all three trigger surfaces
# (dp, 2026-07-26: "make it a regular check — on launch, operator ondemand, and
# periodic schedule").
#
#   on launch          SessionStart hook, --brief, so a session opens knowing whether
#                      it shares this box with something ungoverned
#   operator ondemand  `hestia-agent-inventory` on PATH
#   periodic           systemd USER timer, hourly
#
# WHY THE RUNNING COPY IS NOT THE REPO COPY. The repo lives on /mnt/c, which is 9p, and
# a cold 9p read can outlast a hook timeout — at which point Claude-lineage hooks fail
# OPEN. This check exists to find governance that silently isn't there; it must not
# become an instance of it. So the executable is installed to ~/.local/bin (ext4) and
# every trigger calls THAT, the same shape as the hestia binary's own deploy. Re-run
# this script after editing inventory.py — the repo copy is source, not runtime.
#
# USER SCOPE IS DELIBERATE AND HAS A COST: a --user timer only runs while the user has a
# session, unless lingering is enabled. This script reports which of those is true rather
# than assuming, because "the timer is installed" and "the timer will fire" are different
# facts and the gap between them is exactly the class of defect being hunted here.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${HESTIA_WORKSPACE:-$(cd "$SRC_DIR/../../.." && pwd)}"
BIN="$HOME/.local/bin/hestia-agent-inventory"
UNIT_DIR="$HOME/.config/systemd/user"
SETTINGS="$HOME/.claude/settings.json"

mkdir -p "$(dirname "$BIN")" "$UNIT_DIR"

# ---- 1. the executable, on ext4 -------------------------------------------------
install -m 0755 "$SRC_DIR/inventory.py" "$BIN"
echo "installed: $BIN  (source: $SRC_DIR/inventory.py)"

# ---- 2. periodic: hourly user timer ---------------------------------------------
cat > "$UNIT_DIR/hestia-agent-inventory.service" <<EOF
[Unit]
Description=hestia agent inventory (installed / plugins available / governed)
Documentation=file://$SRC_DIR/README.md

[Service]
Type=oneshot
Environment=HESTIA_WORKSPACE=$WORKSPACE
ExecStart=$BIN
# Observation only. A non-zero exit here must never look like a governance failure,
# and the script is written to exit 0 regardless; this is belt-and-braces.
SuccessExitStatus=0 1
EOF

cat > "$UNIT_DIR/hestia-agent-inventory.timer" <<'EOF'
[Unit]
Description=Hourly hestia agent inventory
# No After=default.target here. That plus WantedBy=default.target is the ordering cycle
# that silently deleted watcher start jobs fleet-wide on 2026-07-25 — systemd resolves a
# cycle by DROPPING a job, so the failure mode is a unit that simply never runs.

[Timer]
OnBootSec=3min
OnUnitActiveSec=1h
Persistent=true
RandomizedDelaySec=90

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now hestia-agent-inventory.timer >/dev/null
echo "installed: hourly timer (systemd --user)"

# The distinction that matters: enabled != will fire.
if loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q 'Linger=yes'; then
  echo "  lingering: ON — the timer fires even with no login session"
else
  echo "  lingering: OFF — this timer ONLY fires while $USER has a session."
  echo "             enable with: loginctl enable-linger $USER   (needs sudo)"
fi

# ---- 3. on launch: SessionStart hook --------------------------------------------
if [ -f "$SETTINGS" ]; then
  cp -a "$SETTINGS" "$SETTINGS.bak.$(date +%Y%m%d-%H%M%S)"
  BIN="$BIN" python3 - "$SETTINGS" <<'PY'
import json, os, sys
path, binp = sys.argv[1], os.environ["BIN"]
cfg = json.load(open(path))
cmd = f"{binp} --brief"
hooks = cfg.setdefault("hooks", {}).setdefault("SessionStart", [])
present = any(cmd in h.get("command", "")
              for grp in hooks for h in grp.get("hooks", []))
if present:
    print("SessionStart hook: already present")
else:
    # Its own group: a slow or broken sibling in a shared group must not take the
    # inventory down with it, and vice versa.
    hooks.append({"hooks": [{"type": "command", "command": cmd, "timeout": 10}]})
    json.dump(cfg, open(path, "w"), indent=2)
    print("SessionStart hook: added (--brief, timeout 10s)")
PY
else
  echo "SessionStart hook: skipped ($SETTINGS not found)"
fi

echo
echo "on demand:  hestia-agent-inventory            # full JSON + witnesses to chain"
echo "            hestia-agent-inventory --brief    # one line"
echo "            hestia-agent-inventory --no-witness"
echo "next fire:  $(systemctl --user list-timers hestia-agent-inventory.timer --no-pager 2>/dev/null | sed -n 2p)"
