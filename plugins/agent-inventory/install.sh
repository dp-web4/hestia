#!/usr/bin/env bash
# Install the agent inventory on this machine, with all three trigger surfaces
# (dp, 2026-07-26: "make it a regular check — on launch, operator ondemand, and
# periodic schedule").
#
#   on launch          SessionStart hook, --brief, so a session opens knowing whether
#                      it shares this box with something ungoverned
#   operator ondemand  `hestia-agent-inventory` on PATH
#   periodic           systemd USER timer (Linux) / launchd USER agent (Darwin), hourly
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
if [ -n "${HESTIA_WORKSPACE:-}" ]; then WS_FROM="from HESTIA_WORKSPACE"; else WS_FROM="from git --git-common-dir"; fi
echo "workspace:  $WORKSPACE  ($WS_FROM)"

# THE SAME SENTENCE, ABOUT THE LOAD-BEARING VARIABLE (cbp, 2026-07-28, measured on Linux).
# The USER note below says it exactly: a variable set by login shells and absent from
# scrubbed ones is not part of the environment this script may assume. That is true of
# HOME too, and HOME is where all three triggers get INSTALLED — the next four lines are
# every path this script writes. On bash 5.2 an unset HOME is not defaulted (measured:
# `env -i bash -c 'echo $HOME'` is an unbound-variable abort; PATH and SHELL are defaulted,
# HOME and USER are not), so under `env -i` this script died at the BIN= line below, before
# step 1, with a bare "line 61: HOME: unbound variable" and nothing installed.
#
# That direction is the right one — it is a clean refusal, not the half-install USER
# produced — so this is a diagnostic, not a behaviour change. It is here because every
# other refusal in this file explains itself (see the workspace block above, rule 4: a
# scope we cannot establish must not be guessed) and this one did not.
#
# AND IT IS NOT A PLATFORM DIFFERENCE — bash 3.2 DOES NOT SUPPLY HOME EITHER (McNugget,
# 2026-07-28, measured on macOS 26.5, correcting the line that stood here). The reasoning
# above is right; the one claim attached to it that could only be checked on Darwin was
# wrong, so it is replaced with the measurement rather than deleted. Measured on
# /bin/bash 3.2.57: `env -i /bin/bash -c 'echo ${HOME-UNSET}'` prints UNSET, and bash 3.2
# defaults exactly what bash 5.2 does — PATH, SHELL, PWD, SHLVL yes; HOME, USER, LOGNAME
# no. Run against the pre-guard revision (66e6a82) this script died on Darwin at
# `line 61: HOME: unbound variable`: the same line, the same message, nothing installed.
#
# So the USER finding was never Darwin-only. It reached line 411 because it was measured
# under a SANDBOXED $HOME — `env -i HOME=/tmp/... ` — which is the sandbox this thread has
# run everything in, not a bash version. With HOME supplied and USER unset, both boxes
# agree: rc=0, all three steps. The two platforms have not diverged here at all, and this
# guard is worth MORE than the note it replaces claimed — on Darwin it is reachable by the
# very command that was said to bypass it.
#
# Refused, not derived. `id -un` can replace USER because the kernel knows the answer;
# nothing knows which home directory an unattended install MEANT, and guessing one writes
# a wrapper, a unit and a hook into it.
if [ -z "${HOME:-}" ]; then
  echo "install: HOME is not set, and every path this script writes is under it." >&2
  echo "         Login shells set it; scrubbed environments (containers, CI, anything" >&2
  echo "         launchd or systemd starts) do not, and bash does not default it." >&2
  echo "         Refusing to guess a home directory: nothing has been installed." >&2
  echo "         Re-run with: HOME=/path/to/home $0" >&2
  exit 1
fi

BIN="$HOME/.local/bin/hestia-agent-inventory"
UNIT_DIR="$HOME/.config/systemd/user"
AGENT_DIR="$HOME/Library/LaunchAgents"
# The plist FILENAME must contain the binary name, because that is what
# `inventory.py:periodic_trigger()` globs for (`*hestia-agent-inventory*.plist`). Naming
# it `io.hestia.agent-inventory` reads better and is invisible to the detector, which
# would report `absent` on a machine this script had just scheduled. The reverse of the
# usual coupling complaint: here the two files must agree, so the agreement is stated in
# both. Fleet convention for the prefix is `io.hestia.*` (deploy/templates).
LAUNCHD_LABEL="io.hestia-agent-inventory"
PLIST="$AGENT_DIR/$LAUNCHD_LABEL.plist"
LOG_DIR="$HOME/.local/state/hestia"
SETTINGS="$HOME/.claude/settings.json"

# ASKED OF THE ENVIRONMENT, NOT INHERITED FROM IT (McNugget, 2026-07-28, measured here).
# The lingering report used `$USER`, on both platforms. Under `set -u` an unset USER is a
# hard abort — and it lands mid-install: on Darwin at the gui/ session line, which is AFTER
# the launchd agent is bootstrapped and BEFORE step 3 wires the SessionStart hook. Measured
# with `env -i`: rc=1, stdout ending on "installed: hourly launchd agent ... run interval =
# 3600s", an hourly job loaded in gui/501, and no hook. Half-installed, reading as success
# — the same shape as the Darwin abort that opened this thread, one variable instead of one
# missing binary. The systemd branch has it too, three lines earlier (`loginctl show-user
# "$USER"`), so it is not a Darwin bug.
#
# USER is not part of the environment this script may assume: it is set by login shells and
# absent from scrubbed ones — containers, CI, and anything launchd or systemd starts, which
# is precisely the kind of automation that would run an installer unattended. `id -un` asks
# the kernel the same question and cannot be unset. UID_N below already did it this way; a
# report about who the job runs as should not be the one thing taken on trust.
USER_N="$(id -un)"

# ---- 0. which of the three triggers this platform can carry ----------------------
#
# DECIDED BEFORE STEP 1, NOT DISCOVERED AT STEP 2 (McNugget, 2026-07-28, on a Mac mini).
# This script is `set -euo pipefail` and step 2 called `systemctl --user daemon-reload`
# unconditionally. On Darwin that is exit 127 and the script dies — AFTER step 1 has
# installed the binary and pinned the workspace into it, and BEFORE step 3 wires the
# SessionStart hook. The residue is the exact shape this plugin exists to find: `command -v
# hestia-agent-inventory` succeeds, the on-demand surface answers, and the two triggers
# that make it a REGULAR check are absent with nothing after the fact reporting it. Honest
# at the terminal, silent a day later.
#
# The remedy is NOT to abort before step 1. Steps 1 and 3 are platform-neutral — a wrapper
# script and a JSON edit — and refusing to install them because the periodic backend is
# missing would drop two working triggers to punish the third. What the failure actually
# demanded was that the platform question be ASKED FIRST, so what gets installed is decided
# rather than discovered by an exit code halfway through.
#
# So: name the backend, wire what it supports, and make the gap outlive this terminal.
# `inventory.py:periodic_trigger()` stats for the unit and the plist on every run and puts
# `NO PERIODIC TRIGGER` on the brief line when the binary is installed with neither — which
# is what a reader a day later actually sees. Same rule as `lingering: OFF` below: this
# script already distinguishes "installed" from "will fire", and this is the rung under it.
PERIODIC_WHY=""
case "$(uname -s)" in
  Linux)  PERIODIC=systemd ;;
  Darwin) PERIODIC=launchd ;;
  *)      PERIODIC=none ;;
esac
# Having the platform is not having the tool: a container with no systemd, or a --user bus
# that is not running, is Linux and still cannot schedule anything.
if [ "$PERIODIC" = systemd ] && ! command -v systemctl >/dev/null 2>&1; then
  PERIODIC=none; PERIODIC_WHY="Linux, but no systemctl on PATH"
elif [ "$PERIODIC" = launchd ]; then
  # Same rule as systemctl above, and it is not hypothetical here: `plutil` is what makes
  # the difference between writing a plist and knowing it parses, and step 2 refuses to
  # claim a schedule it could not lint. Both tools ship with macOS; a box missing either
  # is far enough off the platform that guessing is the wrong move.
  for t in launchctl plutil; do
    if ! command -v "$t" >/dev/null 2>&1; then
      PERIODIC=none; PERIODIC_WHY="Darwin, but no $t on PATH"
    fi
  done
elif [ "$PERIODIC" = none ]; then
  PERIODIC_WHY="$(uname -s) has no periodic backend here"
fi

# Not `[ ... ] && mkdir`: under `set -e` a false test IS the list's exit status and takes
# the script down. The bug class this whole section is about, in one line of its own fix.
mkdir -p "$(dirname "$BIN")"
if [ "$PERIODIC" = systemd ]; then mkdir -p "$UNIT_DIR"; fi
if [ "$PERIODIC" = launchd ]; then mkdir -p "$AGENT_DIR" "$LOG_DIR"; fi
echo "periodic:   ${PERIODIC}${PERIODIC_WHY:+  ($PERIODIC_WHY)}"

# ---- 1. the executable, on ext4 -------------------------------------------------
#
# Installed as a WRAPPER that pins the workspace this installer detected, because the
# operator's on-demand surface was the one path that stayed degraded. The daemon knows its
# workspace (the unit sets HESTIA_WORKSPACE) and reports OK; a human running
# `hestia-agent-inventory` in a plain shell got UNKNOWN, because the script correctly
# refuses to trust a compiled-in default it cannot confirm. The rule is right — an
# unestablished scope must degrade — so the fix is to ESTABLISH it at install time rather
# than to weaken the rule. A caller-supplied HESTIA_WORKSPACE still wins.
#
# THE INTERPRETER IS PINNED FOR THE SAME REASON THE WORKSPACE IS (McNugget, 2026-07-28,
# measured on Darwin). The wrapper said `python3` and let PATH resolve it, so the three
# triggers did not have to agree on which python3 that is. A daemon's PATH is not a shell's.
# Measured with a throwaway LaunchAgent that printed its own environment:
#
#   launchd's PATH for a gui/ agent   /usr/bin:/bin:/usr/sbin:/sbin   (no plist override)
#   `command -v python3` in dp's shell  /opt/homebrew/bin/python3     Python 3.14.4
#   `command -v python3` under launchd  /usr/bin/python3              Python 3.9.6
#
# Two different interpreters, five minor versions apart, chosen by which trigger fired.
# TODAY THAT IS BENIGN AND THE HONEST THING IS TO SAY SO: both were run against this
# workspace and printed a byte-identical --brief line. What is not benign is the coupling —
# step 3 below derives the SessionStart timeout by running this binary under the SHELL's
# python3, and the periodic trigger would then run it under a different one. The pair that
# `--print-hook-timeout` exists to keep from drifting is only pinned on one side.
#
# NOT MEASURED HERE, and stated as unmeasured: on a Mac without the Xcode command line
# tools `/usr/bin/python3` is a stub, so the unpinned wrapper is exit 127 from launchd while
# `launchctl print` still shows a healthy job with the interval set — the schedule real, the
# plist linting, the detector saying `installed`, and the check never once having run. This
# box has Xcode, so that path could not be exercised on it.
#
# Resolving it HERE, in the same shell that is about to verify it, makes the wrapper
# independent of whatever PATH each of the three triggers happens to carry. Not
# Darwin-specific: a systemd --user unit sets no PATH either.
#
# AND ON LINUX THE PIN NEEDS A FLOOR (cbp, 2026-07-28, measured — this is the Linux review
# McNugget asked for, and the shared edit did bite). `command -v python3` in the installing
# shell is a STABLE path on the Mac this was written on (/opt/homebrew/bin/python3) and is
# routinely an EPHEMERAL one here: a venv, a conda prefix, a pyenv shim, a checkout under
# /tmp. Measured on cbp — install with a venv active, then delete the venv, which is what
# `rm -rf` on a project or a `python3 -m venv --clear` does every week:
#
#   pinned wrapper (this branch)   env: '/tmp/hli-venv/bin/python3': No such file  exit 127
#   unpinned wrapper (origin/main) [agent-inventory] OK on cbp: 4 installed ...    exit 0
#
# The pin turned a survivable environment change into a permanent 127, and — the part that
# matters — SILENTLY: `periodic_trigger()` still answered `systemd-user-timer-enabled` with
# `installed_bin` set, the strongest state this file has, while every hourly fire was 127
# and every SessionStart hook emitted nothing. That is precisely the shape McNugget named
# for a Mac without the Xcode CLT and marked NOT MEASURED — "the schedule real, the
# detector saying installed, and the check never once having run". It is reachable on Linux
# by a much more ordinary route than a missing toolchain, so it is measured here.
#
# The pin is still right — it fixed a real five-minor-version split between two triggers on
# Darwin — so this does not revert it. It gives it a floor: pinned when the pin is there,
# PATH when it is not, and the degradation is REPORTED rather than fatal. A check whose own
# wrapper exits 127 is an instance of the failure it exists to find; rule 5's pairing says
# the trigger and what it triggers must be evidence about each other.
#
# `readlink -f` was considered and is not sufficient: it resolves a venv (-> the base
# interpreter, durable) but a conda prefix is a real binary and a pyenv shim is a real
# file, so it fixes one of three cases and would read as fixing all of them.
#
# Benefit on this box today, measured for symmetry with the Darwin numbers: a systemd
# --user unit resolves /usr/bin/python3 3.12.3 and the shell resolves the identical path.
# The pin buys nothing here and costs the 127 above — which is the whole reason it needs
# the floor rather than a Linux exemption.
PYTHON="$(command -v python3 || true)"
if [ -z "$PYTHON" ]; then
  echo "install: no python3 on PATH. That is the interpreter every trigger runs;" >&2
  echo "         refusing to write a wrapper naming one this shell cannot find." >&2
  exit 1
fi
# EXISTS IS NOT RUNS, AND THE INSTALLER IS WHERE THAT IS CHEAPEST TO LEARN (McNugget,
# 2026-07-28, measured on macOS 26.5). `command -v python3` on a Mac WITHOUT the Xcode
# command line tools resolves /usr/bin/python3 — which is an xcrun stub, not an
# interpreter: 118KB, executable, on the default PATH, and `exit 1` with
# `xcrun: error: invalid active developer path` without running a line of python. The -z
# guard above passes it. Pinning it would wire all three triggers to an interpreter that
# has never run once, which is this plugin's own subject matter. Ask it, don't assume:
# 13ms, once, at the one moment a human is watching. Aborting here is NOT the trade
# rejected in step 0 — that dropped two working triggers to punish a third; this is the
# interpreter all three of them are, so there is nothing left to install that would work.
if ! "$PYTHON" -c '' 2>/dev/null; then
  echo "install: $PYTHON is on PATH but cannot run python." >&2
  echo "         On macOS that is the /usr/bin/python3 xcrun stub with no Xcode command" >&2
  echo "         line tools behind it: xcode-select --install, or put a working python3" >&2
  echo "         first on PATH. Nothing has been installed; all three triggers would run" >&2
  echo "         this interpreter, so there is no partial install worth leaving." >&2
  exit 1
fi
install -m 0755 "$SRC_DIR/inventory.py" "$BIN.py"
cat > "$BIN" <<WRAP
#!/bin/sh
# Generated by agent-inventory/install.sh — pins the workspace and the interpreter
# detected at install time. Both are scope: a trigger that resolves either from its own
# environment answers about a directory, or with a python, that nobody chose.
#
# The pin is scope, not a hard dependency. If the pinned interpreter is gone, fall back to
# PATH and SAY SO through the environment — inventory.py turns HESTIA_INTERPRETER_PIN_BROKEN
# into a finding on its own report. Exiting 127 here would replace a working check with
# silence, and silence reads as clean.
#
# AND THE FALLBACK IS PROBED, NOT JUST FOUND (McNugget, 2026-07-28, measured end to end on
# macOS 26.5 through a real launchd agent). \`-x\` and \`command -v\` answer "exists"; the
# floor needs "runs". On a Mac without the Xcode command line tools /usr/bin/python3 is an
# xcrun stub — and once the pinned directory is gone it is the FIRST python3 on the PATH
# launchd hands a gui/ agent (/usr/bin:/bin:/usr/sbin:/sbin). Found by \`command -v\`, so the
# -z branch never fires; exit 1 without running this file, so nothing reports. Measured:
# stdout 0 bytes, no unknown[] entry, no INTERPRETER PIN BROKEN clause, and
# periodic_trigger() still answering \`launchd-agent-installed\` with installed_bin set —
# the strongest state this plugin has. That is the same silence the floor was written to
# end, one platform over. So: run it once before trusting it, and if it cannot run, exit
# LOUDLY rather than let the stub exit quietly. 13ms, and only on the already-degraded path.
#
# THE BACKTICKS ABOVE ARE ESCAPED, AND THAT IS LOAD-BEARING (cbp, 2026-07-28, measured on
# Linux). This heredoc is UNQUOTED — it has to be, it interpolates \$PYTHON, \$BIN and
# \$WORKSPACE. So its body is prose to a reader and shell input to bash: an unescaped
# backtick pair is COMMAND SUBSTITUTION, run by install.sh at install time, and replaced in
# the generated file by its output. Unescaped, the three comment lines above ran \`-x\` and
# \`launchd-agent-installed\` as commands ("command not found" x2 on a clean install) and
# shipped a wrapper whose sentences had holes where the quoted words used to be — "Found by
# , so the -z branch never fires". Nothing executable broke, but only because the words
# happened to name nothing; the count of backticks was even by luck, and an ODD count is a
# hard \`bad substitution\` that writes a ZERO-BYTE wrapper. This file's house style is
# markdown prose in shell comments, which makes that a standing hazard rather than a typo:
# every future paragraph in here is one backtick pair away from executing itself. Escape
# them, and keep the check below (\`bash -n\` will not catch this — it is valid shell).
#
# AND THE SAME QUESTION IS ASKED OF THE PIN (cbp, 2026-07-28, measured on Linux). The rule
# above is right and it was applied to one of the two branches: \`command -v\` on the
# fallback got probed, \`-x\` on the PIN did not — and \`-x\` answers "exists" for exactly the
# same reason. A pin that is present and executable but cannot RUN never reaches either
# guard below: not -x-false, so no fallback, no \$PY -z branch, no
# HESTIA_INTERPRETER_PIN_BROKEN, no finding. It goes straight to the exec and dies there.
# Reachable on Linux by a route as ordinary as the Mac's stub: install with a version-manager
# shim first on PATH (pyenv's \$PYENV_ROOT/shims/python3 — which install.sh ALREADY warns
# about, three lines further down, as "re-resolves from ITS own environment"), then let that
# version go. The shim stays 0755 and answers -x forever; it exits 127 with
# "pyenv: version ... is not installed" without starting python. Measured here, sandboxed
# \$HOME, pin = shim, version removed:
#
#   exit 127 | stdout 0 bytes | no --brief line | no unknown[] entry | --json 0 bytes
#   and inventory.py, run by hand from a WORKING python against that same \$HOME, still
#   reports scope.installed_bin set and scope.periodic_trigger=systemd-user-timer-*
#
# — the strongest-state-while-every-fire-is-a-no-op pair, one rung up, on the PRIMARY path.
# Note what this costs the floor specifically: #95 put scope.interpreter on EVERY run and
# turned the broken pin into a finding, but both of those live INSIDE inventory.py, and this
# is the one case where inventory.py never starts. A report needs something alive to emit it
# — which is McNugget's own sentence, pointed at the branch it did not cover.
#
# So: gone and cannot-run are the SAME CASE and get the same handling. Note this does not
# exit — it falls back and REPORTS, per #95; exiting 127 is reserved for when the fallback
# cannot run either (the two branches below), because that is the only state with nothing
# left alive to report with.
#
# COST, measured, not asserted: one interpreter start on every run. 30ms on this box
# (/usr/bin/python3 3.12.3, 20 runs), against a real --brief over the fleet workspace at
# ~4.6s — 0.6%. Cheap here because the workspace walk is 9p; on a local-SSD workspace the
# same 30ms is a larger fraction, so it is a real trade and not a free one.
# CONSIDERED AND REJECTED, because it is cheaper but not honest: drop the \`exec\`, run the
# pin, and treat rc 126/127 as "the interpreter never started" — zero cost on success, but
# it couples this wrapper to inventory.py's exit codes, and the day the tool legitimately
# exits 127 the wrapper silently runs the whole inventory twice. A guard that is wrong when
# the thing it guards changes is the kind of check this plugin exists to find.
PY="$PYTHON"
if [ ! -x "\$PY" ] || ! "\$PY" -c '' 2>/dev/null; then
  PY="\$(command -v python3 2>/dev/null || true)"
  if [ -n "\$PY" ] && ! "\$PY" -c '' 2>/dev/null; then
    echo "hestia-agent-inventory: pinned interpreter $PYTHON is gone or cannot run," >&2
    echo "  and the PATH fallback \$PY exists but cannot run python either (on macOS" >&2
    echo "  /usr/bin/python3 is an xcrun stub needing the Xcode command line tools; on" >&2
    echo "  Linux, a version-manager shim whose version has been removed does the same)." >&2
    echo "  Re-run install.sh from a shell whose python3 works. This check has NOT run." >&2
    exit 127
  fi
  if [ -z "\$PY" ]; then
    echo "hestia-agent-inventory: pinned interpreter $PYTHON is gone or cannot run, and" >&2
    echo "  there is no python3 on PATH either. Re-run install.sh. This check has NOT run." >&2
    exit 127
  fi
  HESTIA_INTERPRETER_PIN_BROKEN="$PYTHON"
  export HESTIA_INTERPRETER_PIN_BROKEN
fi
exec env HESTIA_WORKSPACE="\${HESTIA_WORKSPACE:-$WORKSPACE}" "\$PY" "$BIN.py" "\$@"
WRAP
chmod 0755 "$BIN"
echo "installed: $BIN  (source: $SRC_DIR/inventory.py, workspace pinned to $WORKSPACE)"
echo "           interpreter pinned to $PYTHON"

# Said HERE, once, at the only moment a human is watching — the same argument as the
# agent-atlas warning at the top. The wrapper will survive the pin going stale, but a pin
# that is ALREADY known to be ephemeral is worth one line now rather than a degraded run
# an hour for the rest of the week.
PIN_WHY=""
case "$PYTHON" in
  "${VIRTUAL_ENV:-/nonexistent}"/*) PIN_WHY="inside the active virtualenv $VIRTUAL_ENV" ;;
  "${CONDA_PREFIX:-/nonexistent}"/*) PIN_WHY="inside the active conda env $CONDA_PREFIX" ;;
  */shims/*) PIN_WHY="a version-manager shim, which re-resolves from ITS own environment" ;;
  /tmp/*) PIN_WHY="under /tmp" ;;
esac
if [ -n "$PIN_WHY" ]; then
  echo "           WARNING: that interpreter is $PIN_WHY." >&2
  echo "           The wrapper falls back to PATH and reports it if this path disappears," >&2
  echo "           but the pin is only as durable as that directory. Re-run install.sh" >&2
  echo "           from a shell whose python3 is the one you want every trigger to use." >&2
fi

# ---- 2. periodic: hourly user timer ---------------------------------------------
# Guarded by the step-0 decision, not by trying it and seeing. Everything from here to the
# lingering report is backend-specific; step 3 below runs on every platform.

# Printed from two places: the platform that has no backend, and the platform that has one
# whose install could not be COMPLETED (a plist that will not lint). The second is the one
# worth having a shared exit for — it is where a script is most tempted to keep going and
# let the schedule be someone's later surprise.
skip_periodic() {
  echo "SKIPPED:   periodic trigger — $PERIODIC_WHY"
  echo "           The binary and the SessionStart hook are still installed, so this"
  echo "           check answers on demand and at session start. It will NOT run on its"
  echo "           own. Every run reports that itself: scope.periodic_trigger=absent,"
  echo "           and --brief carries NO PERIODIC TRIGGER — so the gap does not depend"
  echo "           on anyone having read this line."
}

if [ "$PERIODIC" = systemd ]; then
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
if loginctl show-user "$USER_N" -p Linger 2>/dev/null | grep -q 'Linger=yes'; then
  echo "  lingering: ON — the timer fires even with no login session"
else
  echo "  lingering: OFF — this timer ONLY fires while $USER_N has a session."
  echo "             enable with: loginctl enable-linger $USER_N   (needs sudo)"
fi
elif [ "$PERIODIC" = launchd ]; then
UID_N="$(id -u)"

# WHY THESE KEYS, AND WHICH SYSTEMD PROPERTIES HAVE NO ANALOGUE (McNugget, 2026-07-28).
# The timer above is the specification; this is the nearest launchd can get, and where it
# cannot get there the gap is named rather than papered over.
#
#   StartInterval 3600   = OnUnitActiveSec=1h. Interval since the last run, which is what
#                          the systemd side means. StartCalendarInterval would be a
#                          wall-clock slot — a different schedule wearing the same word.
#   RunAtLoad            ~ OnBootSec=3min. Not equal: RunAtLoad fires AT load, and launchd
#                          has no delay-after-load key for an interval job. The 3min on the
#                          systemd side buys boot quiet, not coverage, so this diverges by
#                          three minutes of contention and nothing else.
#   (none)               = RandomizedDelaySec=90. launchd has no jitter for StartInterval.
#                          One machine, one agent — the jitter was for fleets sharing a
#                          filer, and this walk is local. Recorded as absent, not as fine.
#   (none)               = Persistent=true. A StartInterval missed while the machine slept
#                          fires ONCE at next load, not once per missed interval. On a
#                          laptop that sleeps nightly the two backends diverge in COVERAGE:
#                          systemd catches up, launchd does not. `periodic_trigger()`
#                          carries this in its docstring; it is why the states are named
#                          differently and not merged.
#
# PATH is set even though step 1 now pins the interpreter. Belt and braces, and cheap: the
# thing that failed here was a daemon's PATH being narrower than the shell's, and the
# wrapper is not the only thing downstream that can want a tool (`git`, for the registry).
# The pin is the fix; this is the same fact written where the next reader of the plist is.
#
# ProcessType Background is what tells the scheduler this may be deprioritised — an hourly
# directory walk must never compete with the user's foreground work.
LAUNCHD_PATH="$(dirname "$PYTHON"):/usr/bin:/bin:/usr/sbin:/sbin"

# THE WHITELIST SAYS WHICH NAMES MAY EXPAND; IT DOES NOT SAY THE VALUE IS SAFE IN THE FILE
# BEING GENERATED (McNugget, 2026-07-28, measured on macOS 26.5 by installing). Three
# generated files, three target syntaxes, and the two whose syntax is shell already answer
# this: the wrapper interpolates inside double quotes, and the SessionStart hook goes
# through shlex.quote in step 3. The plist is the one whose syntax is XML, and it
# interpolated raw. `&`, `<` and `>` are legal in a POSIX path and are metacharacters here.
#
# Measured with HESTIA_WORKSPACE=/tmp/mcn-sb2/R&D — a folder name a Mac user types without
# thinking: plutil said "Encountered unknown ampersand-escape sequence at line 10", the
# plist was removed, and the periodic trigger was GONE. The same run's other two triggers
# were fine — the hook read `--workspace '/tmp/mcn-sb2/R&D'` and the wrapper ran and
# reported. So it was one trigger of three, lost to a character in a path.
#
# SIZED HONESTLY, THE WAY THIS THREAD HAS BEEN SIZING THINGS: not a silent failure. The
# lint-before-load guard below caught it, said so, and skip_periodic() made the gap
# self-reporting (scope.periodic_trigger=absent, NO PERIODIC TRIGGER on --brief). That is
# the backstop working. What was wrong is that a path was allowed to reach a syntax that
# could not hold it, and the diagnostic a reader got named plutil's parser message instead
# of the character in their own workspace path. Escaping is four lines; the backstop stays
# exactly where it is, because it also catches truncation, which this does not.
xml_escape() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
XML_LABEL="$(xml_escape "$LAUNCHD_LABEL")"
XML_BIN="$(xml_escape "$BIN")"
XML_WORKSPACE="$(xml_escape "$WORKSPACE")"
XML_HOME="$(xml_escape "$HOME")"
XML_PATH="$(xml_escape "$LAUNCHD_PATH")"
XML_LOG_DIR="$(xml_escape "$LOG_DIR")"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$XML_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$XML_BIN</string>
    <string>--workspace</string>
    <string>$XML_WORKSPACE</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HESTIA_WORKSPACE</key><string>$XML_WORKSPACE</string>
    <key>HOME</key><string>$XML_HOME</string>
    <key>PATH</key><string>$XML_PATH</string>
  </dict>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$XML_LOG_DIR/agent-inventory.log</string>
  <key>StandardErrorPath</key><string>$XML_LOG_DIR/agent-inventory.err</string>
</dict>
</plist>
PLIST_EOF

# LINT BEFORE LOAD, AND REMOVE ON FAILURE. `launchctl` refuses a malformed plist and says
# so unhelpfully (deploy/fleet/install.sh:verify_service_macos, probe 1) — but the file
# would still be sitting in ~/Library/LaunchAgents, where `ls` reads as a wired schedule
# and `periodic_trigger()`'s glob finds it. Leaving it is manufacturing the exact artifact
# this plugin exists to catch. So: unlinted means uninstalled, said out loud, and the run
# continues to step 3 because the other two triggers are unaffected.
#
# AND `plutil -lint` IS A PARSER, NOT A VALIDATOR — measured, not assumed. Appending
# `<<<junk` after `</plist>` still lints OK (macOS 26.5): it stops at the closing tag. It
# catches truncation and malformed XML (a 300-byte cut reports "Encountered unexpected
# EOF"), and it says nothing about whether the dict describes a job launchd will run. That
# second question is why the `launchctl print` probe below exists and is not redundant
# with this one.
LINT="$(plutil -lint "$PLIST" 2>&1 || true)"
case "$LINT" in
  *OK*) : ;;
  *)
    rm -f "$PLIST"
    PERIODIC=none
    PERIODIC_WHY="Darwin — the generated plist did not lint (plutil: $LINT); removed, not left for launchctl to refuse"
    skip_periodic ;;
esac

if [ "$PERIODIC" = launchd ]; then
  # bootout/bootstrap is the modern spelling and the one that reports errors usefully;
  # load/unload is kept for older macOS. `bootout` on a label that is not loaded exits
  # non-zero, which under `set -e` is the same class of abort this whole file is about.
  launchctl bootout "gui/$UID_N/$LAUNCHD_LABEL" 2>/dev/null || true
  BOOTSTRAP_ERR="$(launchctl bootstrap "gui/$UID_N" "$PLIST" 2>&1)" || {
    launchctl unload "$PLIST" 2>/dev/null || true
    BOOTSTRAP_ERR="$(launchctl load "$PLIST" 2>&1)" || true
  }
  echo "installed: hourly launchd agent ($PLIST)"

  # `launchctl load` SUCCEEDS ON A VALID PLIST AND SAYS NOTHING ABOUT THE JOB (same
  # finding, deploy/fleet 2026-07-25). So the claim is not "we wrote a file with
  # StartInterval in it" — it is "launchd is holding a job with that interval", which is a
  # different fact and the only one that makes this a regular check. Ask launchd, not the
  # filesystem.
  PRINTED="$(launchctl print "gui/$UID_N/$LAUNCHD_LABEL" 2>&1 || true)"
  INTERVAL="$(printf '%s\n' "$PRINTED" | sed -n 's/.*interval *= *\([0-9][0-9]*\).*/\1/p' | head -1)"
  if [ "$INTERVAL" = 3600 ]; then
    echo "  launchd:   job loaded in gui/$UID_N, run interval = ${INTERVAL}s"
  else
    echo "  WARNING:   the plist is on disk and lints, but launchd does not report a" >&2
    echo "             3600s run interval for $LAUNCHD_LABEL." >&2
    echo "             launchctl bootstrap said: ${BOOTSTRAP_ERR:-(nothing)}" >&2
    echo "             launchctl print gui/$UID_N/$LAUNCHD_LABEL for the full state." >&2
    echo "             Treat the schedule as NOT wired until that says otherwise." >&2
  fi

  # The distinction that matters, launchd's version of the lingering report. A gui/ domain
  # agent is bound to the GUI login session: it does not run when nobody is logged in, and
  # it stops at logout. That is the same fact as `lingering: OFF` — installed is not
  # will-fire — and it is worse here because there is no `enable-linger` to point at. The
  # honest remedy is a LaunchDaemon (root, system domain), which is a privilege escalation
  # this observation-only check has no business asking for.
  echo "  session:   gui/$UID_N — this agent fires only while $USER_N is logged in."
  echo "             There is no launchd equivalent of loginctl enable-linger for a user"
  echo "             agent; a fire missed while logged out or asleep happens ONCE at next"
  echo "             load, not once per missed hour (no Persistent= analogue)."

  # Label drift, the agent-inventory shape of deploy/fleet's probe 2. `periodic_trigger()`
  # answers from a GLOB, so any other plist whose name carries the binary name counts as
  # this machine's schedule — including a stale one from a rename, pointing at a binary
  # that no longer exists. One `installed` answer would then cover for a dead job.
  DRIFT=""
  for cand in "$AGENT_DIR"/*hestia-agent-inventory*.plist; do
    [ -f "$cand" ] || continue
    [ "$cand" = "$PLIST" ] && continue
    DRIFT="$DRIFT $cand"
  done
  if [ -n "$DRIFT" ]; then
    echo "  WARNING:   LABEL DRIFT — other plists also match the detector's glob:" >&2
    for d in $DRIFT; do echo "               $d" >&2; done
    echo "             periodic_trigger() reports 'installed' if ANY of them carries a" >&2
    echo "             schedule, so a stale one hides a dead job. Review and bootout." >&2
  fi
fi
else
  skip_periodic
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
  # `$PYTHON`, not a bare `python3` — and this one is HYGIENE, not a defect (cbp,
  # 2026-07-28). Stated plainly because it was queued as a nit for two hops and the honest
  # answer is smaller than it looked: install.sh never modifies PATH, and `PYTHON` is
  # `command -v python3` from this same process, so the two always resolved to the same
  # file. The stub case cannot bite here either — step 1 PROBES `$PYTHON` and exits 1
  # before step 3 exists. I could not construct a run on Linux where the bare form
  # differs. It changes anyway, because "every trigger runs the interpreter we pinned" is
  # the invariant this branch is about, and one of the four call sites naming it a second
  # way is how that invariant stops being checkable — not because it is broken today.
  BIN="$BIN" WORKSPACE="$WORKSPACE" HOOK_TIMEOUT="$HOOK_TIMEOUT" \
    "$PYTHON" - "$SETTINGS" <<'PY'
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
if [ "$PERIODIC" = systemd ]; then
  echo "next fire:  $(systemctl --user list-timers hestia-agent-inventory.timer --no-pager 2>/dev/null | sed -n 2p)"
elif [ "$PERIODIC" = launchd ]; then
  # No `list-timers` here: launchd exposes the interval, not the next fire time, so this
  # says the interval and where the last one went rather than inventing a timestamp.
  echo "next fire:  within 3600s of the last run — launchd reports the interval, not a"
  echo "            next-fire time. Output: $LOG_DIR/agent-inventory.log (.err for stderr)"
  echo "            state:  launchctl print gui/$UID_N/$LAUNCHD_LABEL"
  echo "            now:    launchctl kickstart -p gui/$UID_N/$LAUNCHD_LABEL"
else
  echo "next fire:  never on its own — no periodic trigger on this platform ($PERIODIC_WHY)"
fi
