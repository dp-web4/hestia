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

# HESTIA_MESH_SYSTEMCTL replaces systemctl for the test (install_watchers_test.py): a real run under test would
# otherwise drive this machine's own user manager, by the real unit names.
SYSTEMCTL="${HESTIA_MESH_SYSTEMCTL:-systemctl}"
have_systemd=1
command -v "$SYSTEMCTL" >/dev/null 2>&1 && "$SYSTEMCTL" --user show-environment >/dev/null 2>&1 || have_systemd=0

# Every unit this script writes carries this marker; only a unit carrying it is ever retired.
MARK="installed by the hestia deploy, #1373"

realp() { realpath "$1" 2>/dev/null || readlink -f "$1" 2>/dev/null \
  || python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1" 2>/dev/null || true; }
# Owned by this user and writable by no one else -- hestia-deploy.sh's _post_deploy_operator_only, the test that
# guards $HESTIA_HOME/post-deploy.d (Nova's hold on #1368). -perm -g+w / -o+w: BSD find has no `/`.
operator_only() {
  [ -n "$1" ] && [ -O "$1" ] \
    && [ -z "$(find "$1" -maxdepth 0 \( -perm -g+w -o -perm -o+w \) 2>/dev/null || true)" ]
}

# FIRE AUTHORITY (Nova's review of #1374): a flag's PRESENCE is not the operator's word. Firing is armed only by a
# REGULAR file directly in $HESTIA_HOME/mesh-fire.d whose realpath stays there, with that file, the directory and
# $HESTIA_HOME each owned by this user and writable by no one else, and the directory not itself a symlink. Anything
# else leaves the unit print-only and says why. Seats do not reach $HESTIA_HOME: the member gate's scope refuses it
# (a governed member asking for ~/.hestia opens a scope request a peer decides), so the operator-only test is the
# filesystem half of a boundary whose other half is the gate.
# Prints "ok" or the reason firing is refused.
fire_authority() {
  local id="$1" dir="$HESTIA_HOME/mesh-fire.d" flag rdir rflag
  flag="$dir/$id"
  [ -e "$flag" ] || [ -L "$flag" ] || { echo "none"; return 0; }
  operator_only "$(realp "$HESTIA_HOME")" || { echo "HESTIA_HOME is not operator-only"; return 0; }
  [ -L "$dir" ] && { echo "mesh-fire.d is a symlink"; return 0; }
  rdir="$(realp "$dir")"
  operator_only "$rdir" || { echo "mesh-fire.d is not operator-only"; return 0; }
  [ -L "$flag" ] && { echo "the flag is a symlink"; return 0; }
  rflag="$(realp "$flag")"
  [ "$(dirname "$rflag")" = "$rdir" ] || { echo "the flag resolves outside mesh-fire.d"; return 0; }
  [ -f "$rflag" ] || { echo "the flag is not a regular file"; return 0; }
  operator_only "$rflag" || { echo "the flag is not operator-only"; return 0; }
  echo "ok"
}

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
    # RETIRE (Nova's review of #1374): a unit this script wrote for a member that is no longer registered here must
    # not keep running. Only a unit carrying MARK is touched; anyone else's unit of the same name is reported.
    if [ -f "$UNIT_DIR/$unit" ]; then
      if grep -qF "$MARK" "$UNIT_DIR/$unit"; then
        if [ "$CHECK" = "1" ]; then
          state="absent(WOULD-RETIRE $unit)"
        elif [ "$have_systemd" = "1" ]; then
          "$SYSTEMCTL" --user disable --now "$unit" >/dev/null 2>&1 || true
          rm -f "$UNIT_DIR/$unit"
          "$SYSTEMCTL" --user daemon-reload >/dev/null 2>&1 || true
          act="$("$SYSTEMCTL" --user is-active "$unit" 2>/dev/null || true)"
          if [ "$act" = "active" ]; then state="absent(RETIRE FAILED: $unit still active)"; else state="absent(retired $unit)"; fi
        else
          rm -f "$UNIT_DIR/$unit"
          state="absent(retired $unit, no systemd user manager to stop it)"
        fi
      else
        state="absent($unit exists without the deploy's marker; left as it is)"
      fi
    fi
  elif [ "$have_systemd" = "0" ]; then
    state="skipped(no systemd user manager)"
  else
    lock="$STATE/watch-$id.lock"
    held=""
    if [ -f "$lock" ] && ! "$SYSTEMCTL" --user is-active --quiet "$unit"; then
      if ! flock -n "$lock" true 2>/dev/null; then held=1; fi
    fi
    if [ -n "$held" ]; then
      state="held(another watcher holds $lock; retire it to let the deploy own this member)"
    else
      args="$id $id-watch"
      mode="print-only"
      auth="$(fire_authority "$id")"
      if [ "$auth" = "ok" ]; then
        if [ -n "${HESTIA_WORKSPACE:-}" ] && [ -d "${HESTIA_WORKSPACE:-}" ]; then
          args="$args $SRC/$fire"
          mode="fire"
        else
          mode="print-only(fire flag set, but no HESTIA_WORKSPACE directory for the fired CLI to run in)"
        fi
      elif [ "$auth" != "none" ]; then
        mode="print-only(fire flag refused: $auth)"
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
        act="$("$SYSTEMCTL" --user is-active "$unit" 2>/dev/null || true)"
        state="${act:-inactive}($mode, unit $cur)"
      else
        changed=0
        mkdir -p "$UNIT_DIR"
        if ! { [ -f "$UNIT_DIR/$unit" ] && printf '%s' "$want" | cmp -s - "$UNIT_DIR/$unit"; }; then
          printf '%s' "$want" > "$UNIT_DIR/$unit.tmp" && mv "$UNIT_DIR/$unit.tmp" "$UNIT_DIR/$unit"
          changed=1
          echo "  $id: wrote $UNIT_DIR/$unit ($mode)"
        fi
        "$SYSTEMCTL" --user daemon-reload >/dev/null 2>&1 || true
        "$SYSTEMCTL" --user enable "$unit" >/dev/null 2>&1 || true
        if [ "$changed" = "1" ]; then
          "$SYSTEMCTL" --user restart "$unit" >/dev/null 2>&1 || true
        else
          "$SYSTEMCTL" --user start "$unit" >/dev/null 2>&1 || true
        fi
        # The post-condition is the process, not systemctl's exit code (the inventory rule): read what is running.
        sleep "${HESTIA_MESH_SETTLE:-2}"
        act="$("$SYSTEMCTL" --user is-active "$unit" 2>/dev/null || true)"
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
