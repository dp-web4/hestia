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

# THE WORKSPACE MUST NOT DEPEND ON WHERE THIS SCRIPT WAS RUN FROM (cbp, 2026-07-26).
# It was `$SRC_DIR/../../..` — correct from the primary checkout, and silently `/tmp` from
# a detached worktree, baked into all three triggers at once. It fails in the reassuring
# direction (nothing ungoverned is ever found under /tmp), and the fleet's own
# sibling-session protocol REQUIRES installing from a detached worktree on a contended
# box, so the documented-safe path was the one that mis-scoped. The mitigation was
# knowledge held by whoever read the PR description; rule 3 refuses that.
#
# `--git-common-dir` resolves to the PRIMARY repo's .git from either place (verified on
# git 2.43 from both a checkout and a linked worktree), so the workspace is that repo's
# parent regardless of where the source sits. No `../../..` fallback: rule 4 — a scope we
# cannot establish must not be guessed and then written into three triggers.
if [ -n "${HESTIA_WORKSPACE:-}" ]; then
  WORKSPACE="$HESTIA_WORKSPACE"
elif GIT_COMMON_DIR="$(git -C "$SRC_DIR" rev-parse --path-format=absolute \
                         --git-common-dir 2>/dev/null)" && [ -n "$GIT_COMMON_DIR" ]; then
  WORKSPACE="$(cd "$GIT_COMMON_DIR/../.." && pwd)"
else
  echo "install: cannot establish the workspace." >&2
  echo "  $SRC_DIR is not inside a git checkout, or git is too old for" >&2
  echo "  --path-format=absolute (needs 2.31+). Refusing to guess: the old fallback was" >&2
  echo "  \$SRC_DIR/../../.., which from a detached worktree silently yields /tmp and" >&2
  echo "  bakes it into all three triggers." >&2
  echo "  Re-run with: HESTIA_WORKSPACE=/path/to/workspace $0" >&2
  exit 1
fi
# Establishing it is not the same as it being right. agent-atlas/talk-to is the registry
# the check cannot run without, so its absence is worth saying HERE — at install time,
# once — rather than as an UNKNOWN from three triggers an hour for the rest of the week.
if [ ! -d "$WORKSPACE/agent-atlas/talk-to" ]; then
  echo "install: WARNING — resolved workspace $WORKSPACE has no agent-atlas/talk-to." >&2
  echo "         Every trigger will report UNKNOWN ('could not look') until it does." >&2
fi
echo "workspace:  $WORKSPACE  (${HESTIA_WORKSPACE:+from HESTIA_WORKSPACE}${HESTIA_WORKSPACE:-from git --git-common-dir})"

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
# THE TIMEOUT IS DERIVED, NOT WRITTEN DOWN HERE (cbp, 2026-07-26). It has to exceed the
# binary's own scan budget, or the hook is SIGKILLed mid-walk and emits nothing — clause 5,
# where nothing reads as clean. A second copy of that number in this file is a coupling
# maintained by memory, and it is the pairing the review had to spell out in prose. So ask
# the binary, and fail loudly if it cannot answer: writing a guessed timeout is how the
# cliff gets rebuilt.
HOOK_TIMEOUT="$("$BIN" --print-hook-timeout 2>/dev/null || true)"
case "$HOOK_TIMEOUT" in
  ''|*[!0-9]*)
    echo "install: '$BIN --print-hook-timeout' did not return an integer (got" >&2
    echo "         '${HOOK_TIMEOUT}'). That flag is where the SessionStart timeout comes" >&2
    echo "         from; without it this script would have to hardcode a second copy of" >&2
    echo "         the scan budget, which is the drift it exists to prevent." >&2
    exit 1 ;;
esac

if [ -f "$SETTINGS" ]; then
  cp -a "$SETTINGS" "$SETTINGS.bak.$(date +%Y%m%d-%H%M%S)"
  BIN="$BIN" WORKSPACE="$WORKSPACE" HOOK_TIMEOUT="$HOOK_TIMEOUT" \
    python3 - "$SETTINGS" <<'PY'
import json, os, shlex, sys
path, binp = sys.argv[1], os.environ["BIN"]
tmo = int(os.environ["HOOK_TIMEOUT"])
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
    # setdefault on the timeout would have left an existing entry's stale value in place
    # forever — so the machine most in need of the raise (one that already has the hook)
    # is the one that would never get it. The invariant is not "an entry exists", it is
    # "exactly one entry runs this binary, with a timeout that outlasts its own budget".
    why = ([] if keep.get("command") == cmd else ["command"]) + \
          ([] if keep.get("timeout") == tmo else [f"timeout {keep.get('timeout')}->{tmo}"])
    changed = bool(why)
    keep["command"] = cmd
    keep["type"] = "command"
    keep["timeout"] = tmo
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
              f"({', '.join(why) if why else 'entry already correct'}"
              f"{f'; {len(drop)} duplicate(s) removed' if drop else ''})")
    else:
        print("SessionStart hook: already present")
else:
    # Its own group: a slow or broken sibling in a shared group must not take the
    # inventory down with it, and vice versa.
    hooks.append({"hooks": [{"type": "command", "command": cmd, "timeout": tmo}]})
    json.dump(cfg, open(path, "w"), indent=2)
    print(f"SessionStart hook: added (--workspace, --brief, timeout {tmo}s)")

# Asserted, not argued — both halves. Count was silently wrong twice; the timeout is the
# number whose being wrong produces silence rather than a bad answer.
final = [h for grp in cfg["hooks"]["SessionStart"] for h in grp.get("hooks", [])
         if binp in h.get("command", "")]
if len(final) != 1:
    sys.exit(f"SessionStart hook: expected exactly 1 entry running {binp}, found "
             f"{len(final)} — {path} left as written, backup is alongside it")
if final[0].get("timeout") != tmo:
    sys.exit(f"SessionStart hook: entry timeout is {final[0].get('timeout')}, expected "
             f"{tmo} (derived from the scan budget) — {path} left as written")
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
