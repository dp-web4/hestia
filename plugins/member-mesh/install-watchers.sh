#!/usr/bin/env bash
# Install, start and report one member-mesh watcher per member registered on this host (#1373).
#
# WHY THIS EXISTS. dp, 2026-10-23: the mesh should be "a standard part of what hestia does, fleet-wide, and
# installation should be automatic". Before this, a watcher ran only where an operator had once started one by hand
# (CBP, since 2026-07). Thor ran the automatic deploy every 4 h for weeks, its daemon answering on 7711, and had no
# watcher, no mesh hook and no mesh traffic. Nothing reported it, because nothing that runs automatically ever knew a
# watcher should exist. The deploy (deploy/from-main/hestia-deploy.sh, install_mesh) runs this after the members'
# install, the same way it runs agent-inventory's installer.
#
# WHAT IS AUTOMATIC AND WHAT IS NOT.
#   automatic: a systemd user unit per member, enabled and running. It polls the member's inbox and, with no fire
#              command, PRINTS (hestia-watch-member.sh's print-only mode): delivery into a live session goes
#              through the member's mesh hooks, which install-members.sh now installs from each member's template.
#   opt-in:    FIRING a headless CLI session on a notice. hestia-watch-member.sh's header: "auto-firing a CLI session
#              is a consequential act -- enable per-member only with dp's sign-off". That stays a per-host operator
#              act: create $HESTIA_HOME/mesh-fire.d/<member> (any content; say who and why). The next deploy rewrites
#              the unit with the member's fire script. Removing the file disarms it the same way.
#
# WHICH MEMBERS. A member is ON THIS HOST when its own harness config registers session-mesh-inbox.sh pinned to its
# id (HESTIA_MESH_PLUGIN=<id>), the registration install-members.sh just wrote or confirmed. Registration, not a
# directory (install-members.sh invariant 1): no registration -> no unit, said aloud.
#
# A HAND-STARTED WATCHER ALREADY RUNNING (CBP). hestia-watch-member.sh holds a per-member flock. If another process
# holds it, a unit would only exit 1 and restart into StartLimit. So the member is reported held(...) and no unit is
# written. Retiring the hand-started watcher is the operator's call; the next deploy then installs the unit.
#
# WHERE IT RUNS FROM. The deploy checkout (this file's own directory). The watcher hashes its source at start and
# re-execs a snapshot when the git-tracked file moves (maybe_self_deploy), so a deploy that resets the checkout to
# a newer main updates a running watcher without a restart here. That is the opposite of #606, where the source
# was a developer tree on a 7-day-old branch.
#
# ORDERING. After=/Wants=hestia.service, WantedBy=default.target, and NEVER After=default.target: on CBP that third
# edge closed a loop systemd broke by deleting both watchers' start jobs at every boot (deploy/fleet/install.sh).
# StartLimitIntervalSec=120 > burst 5 x RestartSec 5, or the limit can never trip (the same file, measured).
#
# Usage: install-watchers.sh [--check]
#   --check   report only; write, enable and start nothing
# Prints one line per member, then `mesh: <id>=<state> ...` as its LAST line (the deploy records that line).
# Exit 0 always unless arguments are wrong: a member's state is data for the deploy line, not a reason to stop it.
set -uo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HESTIA_HOME="${HESTIA_HOME:-$HOME/.hestia}"
UNIT_DIR="$HOME/.config/systemd/user"
STATE="${HESTIA_MESH_STATE:-$HOME/.local/state/hestia-mesh}"
CHECK=0
for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "install-watchers.sh: unknown argument $a" >&2; exit 2 ;;
  esac
done

# mesh id | harness config (relative to $HOME) | fire script
# HESTIA_MESH_WATCH_TABLE replaces the table for the test (install_watchers_test.sh): a fixture named like a real
# harness config is a governance-closure path wherever it sits, so the test's configs carry other names.
TABLE="${HESTIA_MESH_WATCH_TABLE:-claude-code|.claude/settings.json|fire-claude.sh
kimi-code|.kimi-code/config.toml|fire-kimi.sh
codex|.codex/config.toml|fire-codex.sh}"

have_systemd=1
command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1 || have_systemd=0

summary=""
while IFS='|' read -r id cfg fire; do
  [ -n "$id" ] || continue
  conf="$HOME/$cfg"
  unit="hestia-mesh-watch-$id.service"
  state=""
  # Registered here, pinned to THIS id? A grep, as in install.sh: an assignment on a command line is literal text
  # in both config formats. Comment lines dropped first so a commented-out hook does not count.
  if [ ! -f "$conf" ] || ! sed -e '/^[[:space:]]*#/d' "$conf" | grep -F 'session-mesh-inbox.sh' | grep -qE "HESTIA_MESH_PLUGIN=$id([^A-Za-z0-9_-]|\$)"; then
    state="absent"
  elif [ "$have_systemd" = "0" ]; then
    state="skipped(no systemd user manager)"
  else
    lock="$STATE/watch-$id.lock"
    held=""
    if [ -f "$lock" ] && ! systemctl --user is-active --quiet "$unit"; then
      if ! flock -n "$lock" true 2>/dev/null; then held=1; fi
    fi
    if [ -n "$held" ]; then
      state="held(another watcher holds $lock; retire it to let the deploy own this member)"
    else
      args="$id $id-watch"
      mode="print-only"
      if [ -e "$HESTIA_HOME/mesh-fire.d/$id" ]; then
        if [ -n "${HESTIA_WORKSPACE:-}" ] && [ -d "${HESTIA_WORKSPACE:-}" ]; then
          args="$args $SRC/$fire"
          mode="fire"
        else
          mode="print-only(fire flag set, but no HESTIA_WORKSPACE directory for the fired CLI to run in)"
        fi
      fi
      want="[Unit]
Description=hestia member-mesh watcher for $id ($mode; installed by the hestia deploy, #1373)
Documentation=https://github.com/dp-web4/hestia/issues/1373
After=hestia.service
Wants=hestia.service
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=simple
Environment=HESTIA_HOME=$HESTIA_HOME
Environment=HESTIA_WORKSPACE=${HESTIA_WORKSPACE:-}
ExecStart=/usr/bin/env bash $SRC/hestia-watch-member.sh $args
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"
      if [ "$CHECK" = "1" ]; then
        if [ -f "$UNIT_DIR/$unit" ] && printf '%s' "$want" | cmp -s - "$UNIT_DIR/$unit"; then cur="current"; else cur="WOULD-WRITE"; fi
        act="$(systemctl --user is-active "$unit" 2>/dev/null || true)"
        state="${act:-inactive}($mode, unit $cur)"
      else
        changed=0
        mkdir -p "$UNIT_DIR"
        if ! { [ -f "$UNIT_DIR/$unit" ] && printf '%s' "$want" | cmp -s - "$UNIT_DIR/$unit"; }; then
          printf '%s' "$want" > "$UNIT_DIR/$unit.tmp" && mv "$UNIT_DIR/$unit.tmp" "$UNIT_DIR/$unit"
          changed=1
          echo "  $id: wrote $UNIT_DIR/$unit ($mode)"
        fi
        systemctl --user daemon-reload >/dev/null 2>&1 || true
        systemctl --user enable "$unit" >/dev/null 2>&1 || true
        if [ "$changed" = "1" ]; then
          systemctl --user restart "$unit" >/dev/null 2>&1 || true
        else
          systemctl --user start "$unit" >/dev/null 2>&1 || true
        fi
        # The post-condition is the process, not systemctl's exit code (the inventory rule): read what is running.
        sleep 2
        act="$(systemctl --user is-active "$unit" 2>/dev/null || true)"
        state="${act:-unknown}($mode)"
      fi
    fi
  fi
  echo "  $id: $state"
  summary="$summary $id=${state%%(*}"
done <<EOF
$TABLE
EOF
echo "mesh:${summary}"
exit 0
