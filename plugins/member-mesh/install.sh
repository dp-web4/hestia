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
# WHAT THE FIRST REAL RUN FOUND, and why the refusal is no longer about one variable.
# kimi-code reviewed this script by USING it (notice 352, 2026-07-29) and caught what the
# paragraph above does not cover: its deployed hook carried an inline
#     OUT=$(HESTIA_ROLE=role:constellation:interactive-dev python3 ... peek)
# which the merged copy does not have. The sync dropped it and printed "synced". The
# member kept its ID and lost its GRAIN — hestia-mesh.py's own docstring says an absent
# HESTIA_ROLE normalizes to role:constellation:member, a different member-shape than the
# one whose acts were being judged. kimi found it by reading the diff by hand.
#
# HESTIA_MESH_PLUGIN was never the point; it was the variable that happened to be
# noticed first. The general rule is: THE CONFIG COMMAND LINE IS THE ONLY PLACE A VALUE
# SURVIVES A SYNC. So sync now refuses any HESTIA_* that the deployed hook assigns and
# the config does not — the same refusal as the pin, taken off the single instance.
#
# And the standing case the same scan exposes, which no sync causes and nothing else was
# ever going to report: a member with NO role anywhere at all. On CBP today that is
# codex — ~/.codex/config.toml pins HESTIA_MESH_PLUGIN and no role, its deployed hook
# has none either, so every codex act has been landing on the daemon's default grain.
# "pinned" was being printed as if it were the whole answer.
#
# --check is read-only and needs no operator standing: any member can run it to answer
# "is the code I am running the code that was merged?" — a question that, before this
# script, could only be answered by reading someone else's home directory.
#
# Usage: install.sh [--check] [--force] [member ...]
#   --check   report drift, pin, role and pending-loss state; write nothing; exit 1 if off
#   --force   sync past an unpinned config OR past a variable the overwrite would delete
#   member    one or more of: claude-code kimi-code codex (default: all present)
#
# Exit: 0 clean/synced · 1 --check found drift, an unpinned member, or one with no role
#       · 2 sync refused (unpinned, or the overwrite would take a variable away)
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

# The HESTIA_* names ASSIGNED — not merely referenced — in a shell file. `${HESTIA_ROLE:-x}`
# is a read and does not match: the name must be immediately followed by `=`.
#
# Whole-line comments are dropped first, so a commented-out example does not read as a live
# assignment. An INLINE `#` is deliberately NOT stripped: in shell it may sit inside a quoted
# string, and the two errors are not symmetric. Over-reporting costs a refusal the operator
# can --force past in one command; under-reporting costs a member its grain and prints
# "synced" over the top. When the parse is uncertain, refuse.
assigned_vars() {
  { sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*\/\//d' "$1" \
      | grep -oE '(^|[[:space:]]|[;&(])HESTIA_[A-Z0-9_]*=' \
      | grep -oE 'HESTIA_[A-Z0-9_]*' | sort -u; } 2>/dev/null || :
}

# The same, for the config line(s) that actually invoke this hook — not anywhere in the file,
# since a HESTIA_* named in an unrelated block answers the wrong question. The config differs
# in FORMAT per member (json vs toml), so this greps rather than parses: it is looking for an
# assignment on a command line, which in both formats is literal text. Whole-line comments go
# first — the original check grepped the raw file, so a commented-out hook line read as
# "pinned" and unlocked the very sync that darkens the member.
config_vars() {
  [ -f "$1" ] || return 0
  { grep -F 'session-mesh-inbox.sh' "$1" \
      | sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*\/\//d' \
      | grep -oE 'HESTIA_[A-Z0-9_]*=' \
      | grep -oE 'HESTIA_[A-Z0-9_]*' | sort -u; } 2>/dev/null || :
}

DRIFT=0; UNPINNED=0; REFUSED=0; NOROLE=0
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

  # Everything the config hands this hook. The pin is one entry in it, not a category.
  cfg_vars="$(config_vars "$config")"
  cfg_vars="$(echo $cfg_vars)"          # newlines -> spaces, for the case-globs below
  pin="UNPINNED"
  case " $cfg_vars " in *" HESTIA_MESH_PLUGIN "*) pin="pinned" ;; esac

  state=""
  for f in $FILES; do
    if [ ! -f "$hooks/$f" ]; then state="$state $f=ABSENT"
    elif cmp -s "$SRC/$f" "$hooks/$f"; then state="$state $f=current"
    else state="$state $f=DRIFT"; fi
  done

  # What the overwrite would DELETE. Computed only when a file would actually be replaced:
  # if the deployed copy already equals the source, nothing can be lost by definition, and
  # scanning it anyway would report the source's own DARK-banner text (which echoes the
  # literal string "HESTIA_MESH_PLUGIN=<your-member-id>") as if it were an assignment.
  #
  # Note this does NOT subtract the assignments found in the SOURCE hook, for that same
  # reason: a text scan cannot tell that echoed instruction from real code, and crediting
  # it would mask a genuine loss of exactly the variable this script exists to protect.
  # The config line is the only place that counts, because it is the only place that
  # survives the copy.
  lost=""
  case "$state" in
    *DRIFT*|*ABSENT*)
      if [ -f "$hooks/session-mesh-inbox.sh" ]; then
        for v in $(assigned_vars "$hooks/session-mesh-inbox.sh"); do
          case " $cfg_vars " in *" $v "*) : ;; *) lost="$lost $v" ;; esac
        done
      fi ;;
  esac

  # Role, on its own axis: declared where it survives / only inside the copy about to be
  # overwritten / nowhere at all. The third is not a sync hazard, it is a standing one —
  # the daemon defaults an absent role to role:constellation:member and the connect
  # succeeds identically, so nothing downstream ever says the grain was wrong.
  rolestate="role=cfg"
  case " $cfg_vars " in
    *" HESTIA_ROLE "*) : ;;
    *) case " $lost " in
         *" HESTIA_ROLE "*) rolestate="role=hook" ;;
         *) rolestate="NO-ROLE"; NOROLE=1 ;;
       esac ;;
  esac

  losstxt=""
  if [ -n "$lost" ]; then losstxt="  LOSS-ON-SYNC:$(echo $lost | tr ' ' ',')"; fi
  printf '  %-12s %-9s %-9s%s%s\n' "$member" "$pin" "$rolestate" "$state" "$losstxt"

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

  # The same refusal as the pin, off the single variable that happened to be noticed first.
  if [ -n "$lost" ] && [ "$FORCE" -eq 0 ]; then
    echo "      REFUSED: the deployed hook assigns$lost, and $config does not."
    echo "      The overwrite deletes that assignment. Nothing downstream fails — the"
    echo "      member keeps its id, silently changes grain, and this script prints"
    echo "      'synced'. Put it where a sync cannot reach it, on the hook's command"
    echo "      line in $config:"
    for v in $lost; do
      echo "        $v=<the value it is running today>   (kept in $hooks/session-mesh-inbox.sh.pre-sync.bak if you sync first)"
    done
    echo "      Then re-run. (--force to proceed and accept the loss.)"
    REFUSED=1
    continue
  fi
  if [ -n "$lost" ]; then
    echo "      FORCED past a pending loss —$lost will be gone from this member."
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
  if [ "$DRIFT" -eq 0 ] && [ "$UNPINNED" -eq 0 ] && [ "$NOROLE" -eq 0 ]; then
    echo "[member-mesh] all present members current, pinned, and declaring a role"
    exit 0
  fi
  echo "[member-mesh] DRIFT, UNPINNED or NO-ROLE member found (see above)"
  exit 1
fi
if [ "$REFUSED" -eq 1 ]; then
  echo "[member-mesh] one or more members REFUSED — fix the config pin, then re-run"
  exit 2
fi
exit 0
