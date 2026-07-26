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
# Quoted: systemd splits ExecStart on whitespace, so an unquoted workspace path with a
# space becomes two arguments and the check silently inspects its first word (cbp).
Environment="HESTIA_WORKSPACE=$WORKSPACE"
ExecStart="$BIN" --workspace "$WORKSPACE"
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
  BIN="$BIN" WORKSPACE="$WORKSPACE" python3 - "$SETTINGS" <<'PY'
import json, os, shlex, sys
path, binp = sys.argv[1], os.environ["BIN"]
cfg = json.load(open(path))
# --workspace, not the environment. A SessionStart hook inherits the harness's env, not
# the timer unit's, so the hook read the compiled-in CBP default on every other machine
# and answered UNKNOWN (thor, 2026-07-26). Scope has to travel in the command itself.
# Quoted, because a workspace path with a space otherwise truncates to its first word and
# the hook answers UNKNOWN about a directory nobody named (cbp, 2026-07-26).
cmd = f"{shlex.quote(binp)} --workspace {shlex.quote(os.environ['WORKSPACE'])} --brief"
hooks = cfg.setdefault("hooks", {}).setdefault("SessionStart", [])

# CONVERGE ON ONE ENTRY, DO NOT JUST REWRITE THE ONES YOU RECOGNISE (cbp, 2026-07-26).
# First cut matched the whole command string, so a bare `$BIN --brief` from an earlier
# install survived and a second entry was appended. The fix — match on the binary —
# repaired the case that had been exercised and left the one next door: with a stale entry
# AND an already-correct entry both present, both were rewritten to the same string and the
# machine ran two inventories per session. That is the failure the fix was written to
# prevent, one arrangement over, and Thor is in exactly that state now.
# So the invariant is not "no stale entries", it is "EXACTLY ONE entry runs this binary" —
# asserted below rather than argued, because that is the property that was silently false
# twice. Identity, not equality: two duplicate entries are equal dicts, and list.remove()
# would take out the one being kept.
ours = [(grp, h) for grp in hooks for h in grp.get("hooks", [])
        if binp in h.get("command", "")]
if ours:
    keep = ours[0][1]
    changed = keep.get("command") != cmd
    keep["command"] = cmd
    keep.setdefault("type", "command")
    keep.setdefault("timeout", 10)
    drop = {id(h) for _, h in ours[1:]}
    if drop:
        for grp in hooks:
            grp["hooks"] = [h for h in grp.get("hooks", []) if id(h) not in drop]
        # A group emptied by that is ours and now holds nothing; leaving it behind is
        # harmless but it accumulates one per re-install.
        hooks[:] = [g for g in hooks if g.get("hooks")]
    if changed or drop:
        json.dump(cfg, open(path, "w"), indent=2)
        print(f"SessionStart hook: converged to 1 entry "
              f"({'rewritten with --workspace' if changed else 'already correct'}, "
              f"{len(drop)} duplicate(s) removed)")
    else:
        print("SessionStart hook: already present")
else:
    # Its own group: a slow or broken sibling in a shared group must not take the
    # inventory down with it, and vice versa.
    hooks.append({"hooks": [{"type": "command", "command": cmd, "timeout": 10}]})
    json.dump(cfg, open(path, "w"), indent=2)
    print("SessionStart hook: added (--workspace, --brief, timeout 10s)")

final = [h for grp in cfg["hooks"]["SessionStart"] for h in grp.get("hooks", [])
         if binp in h.get("command", "")]
if len(final) != 1:
    sys.exit(f"SessionStart hook: expected exactly 1 entry running {binp}, found "
             f"{len(final)} — {path} left as written, backup is alongside it")
PY
else
  echo "SessionStart hook: skipped ($SETTINGS not found)"
fi

echo
echo "on demand:  hestia-agent-inventory --workspace $WORKSPACE"
echo "            (or export HESTIA_WORKSPACE=$WORKSPACE in your shell rc — a bare"
echo "             invocation falls back to the compiled-in default and answers UNKNOWN)"
echo "            --brief       one line        --no-witness   skip the chain write"
echo "next fire:  $(systemctl --user list-timers hestia-agent-inventory.timer --no-pager 2>/dev/null | sed -n 2p)"
