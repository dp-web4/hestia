#!/usr/bin/env sh
# Deploy (or audit) the member-mesh hook pair into each member's live hooks dir.
#
# WHY THIS EXISTS. plugins/member-mesh/ had no installer, while plugins/gemini/ and
# plugins/agent-inventory/ both did. So every mesh fix landed in the repo and stayed
# there: on CBP 2026-07-29, hours after #109 merged, all three deployed copies
# (~/.claude/hooks/member-mesh, ~/.kimi-code/hooks, ~/.codex/hooks) still carried the
# pre-#108 CLI — the one whose HESTIA_MESH_PLUGIN default is the literal string
# "kimi-code", i.e. the D1 impersonation default itself. Merged-but-dark was not an
# oversight anyone made; it was the default state, because nothing moved the files.
# Same class as deploy/fleet/install.sh:156 ("the mesh was 'enabled' and never ran"),
# one layer down: there, the watchers were wired and never started; here, the code was
# merged and never shipped.
#
# THE ORDERING HAZARD THIS REFUSES TO CREATE. The obvious sync order — copy the files,
# fix the config later — is the one that breaks members. #108 deleted the default, so
# after the copy a member's id comes from ONE place: HESTIA_MESH_PLUGIN on the hook's
# command line. A member whose config never pinned it was correct only because the
# default happened to name it (kimi-code's config.toml pins nothing to this day). Copy
# the files to that member and it goes rc=2 -> permanently DARK, every session, until
# someone notices. The pin is not a redundancy alongside the default: pre-sync the
# default is the only guard, post-sync the pin is the only guard, and there is no
# moment when both hold. So sync REFUSES an unpinned member rather than darkening it.
# Fix the config first, then re-run. --force exists for the operator who means it.
#
# --check is read-only and needs no operator standing: any member can run it to answer
# "is the code I am running the code that was merged?" — a question that, before this
# script, could only be answered by reading someone else's home directory.
#
# Usage: install.sh [--check] [--force] [member ...]
#   --check   report drift + pin state, write nothing, exit 1 if anything is off
#   --force   sync even a member whose config does not pin HESTIA_MESH_PLUGIN
#   member    one or more of: claude-code kimi-code codex (default: all present)
#
# Exit: 0 clean/synced · 1 --check found drift or an unpinned member · 2 sync refused
set -eu

SRC="$(cd "$(dirname "$0")" && pwd)"
FILES="hestia-mesh.py session-mesh-inbox.sh"

# member | live hooks dir | config file that wires the SessionStart hook
# The hooks dir differs per member because each engine picked its own layout; the
# config file differs in FORMAT too (json vs toml), which is why the pin check below
# greps rather than parses. A grep is enough: it is looking for an assignment on the
# command line, which in both formats is literal text.
MEMBERS="claude-code:$HOME/.claude/hooks/member-mesh:$HOME/.claude/settings.json
kimi-code:$HOME/.kimi-code/hooks:$HOME/.kimi-code/config.toml
codex:$HOME/.codex/hooks:$HOME/.codex/config.toml"

CHECK=0; FORCE=0; WANT=""
for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '1,32p' "$0"; exit 0 ;;
    -*) echo "install.sh: unknown flag $a" >&2; exit 2 ;;
    *) WANT="$WANT $a" ;;
  esac
done

for f in $FILES; do
  [ -f "$SRC/$f" ] || { echo "install.sh: FATAL: source missing: $SRC/$f" >&2; exit 2; }
done

DRIFT=0; UNPINNED=0; REFUSED=0
echo "[member-mesh] source=$SRC"

# Fed by here-document, NOT by `echo ... | while`: a pipe puts the loop in a subshell and
# the flags it sets die with it, which would have made every run exit 0 including the
# refusals. A redirect keeps the loop in this shell.
while IFS=: read -r member hooks config; do
  [ -n "$member" ] || continue
  case "$WANT" in "") : ;; *" $member"*) : ;; *) continue ;; esac

  # Absent hooks dir means this member is not installed on this box. Do NOT mkdir it:
  # creating a hooks dir for an engine that is not here manufactures a deployment that
  # nothing wires, which is the same lie as a stale one in the other direction.
  if [ ! -d "$hooks" ]; then
    printf '  %-12s NOT INSTALLED (%s absent) — skipped\n' "$member" "$hooks"
    continue
  fi

  # Pin state. Looked up on the line that names this hook, not anywhere in the file:
  # a HESTIA_MESH_PLUGIN mentioned in an unrelated block would answer the wrong question.
  pin="UNPINNED"
  if [ -f "$config" ] && grep -F 'session-mesh-inbox.sh' "$config" 2>/dev/null \
       | grep -q 'HESTIA_MESH_PLUGIN='; then
    pin="pinned"
  fi

  state=""
  for f in $FILES; do
    if [ ! -f "$hooks/$f" ]; then state="$state $f=ABSENT"
    elif cmp -s "$SRC/$f" "$hooks/$f"; then state="$state $f=current"
    else state="$state $f=DRIFT"; fi
  done

  printf '  %-12s %-10s%s\n' "$member" "$pin" "$state"

  # `[ x ] && flag=1` would be the last command of the list, so a FALSE test returns 1
  # and `set -e` kills the script mid-audit. Every conditional here is a full if/fi.
  case "$state" in *DRIFT*|*ABSENT*) DRIFT=1 ;; esac
  if [ "$pin" = "UNPINNED" ]; then UNPINNED=1; fi

  if [ "$CHECK" -eq 1 ]; then continue; fi
  case "$state" in *DRIFT*|*ABSENT*) : ;; *) continue ;; esac

  if [ "$pin" = "UNPINNED" ] && [ "$FORCE" -eq 0 ]; then
    echo "      REFUSED: $config does not pin HESTIA_MESH_PLUGIN on the hook command."
    echo "      Syncing would remove the default this member's id currently comes from,"
    echo "      and every session after it would be DARK. Pin it there first:"
    echo "        HESTIA_MESH_PLUGIN=$member ... $hooks/session-mesh-inbox.sh"
    echo "      Then re-run. (--force to proceed anyway and accept the dark window.)"
    REFUSED=1
    continue
  fi
  if [ "$pin" = "UNPINNED" ]; then
    echo "      FORCED past an unpinned config — this member is DARK until $config pins it."
  fi

  for f in $FILES; do
    # Back up before overwriting: the deployed copy is the only record of what this
    # member was actually running, and on CBP those hand-edits turned out to differ
    # per member (kimi's carried an unconditional HESTIA_ROLE and a hardcoded reply
    # target). Clobbering them unrecorded would erase the evidence of the drift.
    if [ -f "$hooks/$f" ]; then cp -p "$hooks/$f" "$hooks/$f.pre-sync.bak"; fi
    cp "$SRC/$f" "$hooks/$f"
    chmod +x "$hooks/$f"
  done
  echo "      synced (previous copies kept as *.pre-sync.bak)"
done <<MEMBER_TABLE
$MEMBERS
MEMBER_TABLE

if [ "$CHECK" -eq 1 ]; then
  if [ "$DRIFT" -eq 0 ] && [ "$UNPINNED" -eq 0 ]; then
    echo "[member-mesh] all present members current and pinned"
    exit 0
  fi
  echo "[member-mesh] DRIFT or UNPINNED member found (see above)"
  exit 1
fi
if [ "$REFUSED" -eq 1 ]; then
  echo "[member-mesh] one or more members REFUSED — fix the config pin, then re-run"
  exit 2
fi
exit 0
