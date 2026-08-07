#!/usr/bin/env bash
# Install every member's governance surface from this checkout, and record what was
# installed so the running daemon can prove it.
#
# WHY THIS EXISTS, in one line: the fleet had three one-off installers, two members with
# none, and nothing anywhere that wrote the deployment-authority file the dashboard reads —
# so "deployment: unknown" was the only value it could ever show.
#
# THE SHAPE (dp, 2026-08-07): "don't do for one, do for all. one at a time is how we drift.
# core lives as high up the hierarchy as possible, details decompose/recompose only as
# needed." So: the INVARIANTS live here, once. WHAT each member installs is DATA, in that
# member's own `expects.json`. Adding a member is a data edit, never another script.
#
# THE INVARIANTS, each of them learned from a defect:
#
#   1. AN ABSENT DESTINATION MEANS THE MEMBER IS NOT ON THIS BOX — skip it, never mkdir.
#      Creating the directory fabricates a member that was never installed, and the next
#      audit reads the fabrication as a real deployment. (From member-mesh/install.sh,
#      which is the only existing installer that gets this right.)
#
#   2. BACK UP BEFORE OVERWRITE. The running gate is the only copy of what is currently
#      enforcing; losing it loses the ability to answer "what changed?" after a bad deploy.
#
#   3. VERIFY AFTER WRITING, PER FILE. `cp` exiting 0 is not evidence the bytes landed.
#      A deploy that cannot prove itself is the thing this script exists to end.
#
#   4. WRITE THE AUTHORITY FILE LAST, AND ONLY ON FULL SUCCESS. `current-build.json` is
#      what the dashboard reads to say green/amber. Writing it on a partial install would
#      make the indicator confidently wrong, which is worse than "unknown".
#
#   5. HESTIA_HOME RESOLVES env-first, else the standard home — never assumed present.
#      (codex's review of #253: its hook env carries HESTIA_WORKSPACE and not HESTIA_HOME,
#      so a resolver that requires the variable fails on a real member.)
#
# WHAT THIS DELIBERATELY DOES NOT DO: install the daemon binary, or restart anything. A
# member's gate and the daemon fail differently and are approved differently — the gate is
# a governance surface needing an operator decision, the binary is not. Conflating them is
# how a hook install rides in on a binary approval.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HESTIA_HOME="${HESTIA_HOME:-$HOME/.hestia}"
AUTHORITY="$HESTIA_HOME/current-build.json"
DRY_RUN="${DRY_RUN:-0}"

log()  { printf '%s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die()  { printf 'FATAL: %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null || die "python3 is required (manifest parsing + hashing)"

build_id="$(git -C "$REPO_ROOT" describe --tags --always --dirty 2>/dev/null || echo unknown)"
head_sha="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
case "$build_id" in
  *-dirty)
    # A dirty tree can still be installed deliberately, but it must never be recorded as a
    # clean build id — that is precisely the declared-where-audited-belongs defect.
    warn "working tree is DIRTY; the authority file will record it as such"
    ;;
esac

log "hestia member install"
log "  repo      : $REPO_ROOT"
log "  build     : $build_id"
log "  home      : $HESTIA_HOME"
[ "$DRY_RUN" = "1" ] && log "  MODE      : DRY RUN (nothing will be written)"
log ""

installed_json="["
first_entry=1
any_installed=0
any_skipped=0

for expects in "$REPO_ROOT"/plugins/*/expects.json; do
  [ -e "$expects" ] || continue
  member="$(basename "$(dirname "$expects")")"

  # --- decomposition: the member declares WHERE it installs and WHAT ----------------
  dest="$(python3 -c '
import json,os,sys
d=json.load(open(sys.argv[1])).get("install") or {}
p=d.get("dest","")
print(os.path.expanduser(p) if p else "")' "$expects")"

  if [ -z "$dest" ]; then
    log "SKIP  $member — declares no install target (expects.json has no install.dest)"
    any_skipped=1
    continue
  fi

  # INVARIANT 1: absent destination = member not on this box. Skip, never create.
  if [ ! -d "$dest" ]; then
    log "SKIP  $member — $dest does not exist (member not installed on this host)"
    any_skipped=1
    continue
  fi

  mapfile -t files < <(python3 -c '
import json,sys
for f in (json.load(open(sys.argv[1])).get("install") or {}).get("files",[]):
    print(f)' "$expects")

  [ "${#files[@]}" -gt 0 ] || { log "SKIP  $member — install.files is empty"; any_skipped=1; continue; }

  log "MEMBER $member -> $dest"
  member_files_json=""
  for rel in "${files[@]}"; do
    src="$REPO_ROOT/plugins/$member/$rel"
    [ -f "$src" ] || die "$member declares '$rel' but $src does not exist"
    base="$(basename "$rel")"
    target="$dest/$base"

    src_hash="$(sha256sum "$src" | cut -d' ' -f1)"
    if [ -f "$target" ] && [ "$(sha256sum "$target" | cut -d' ' -f1)" = "$src_hash" ]; then
      log "  ok    $base (already current)"
    elif [ "$DRY_RUN" = "1" ]; then
      log "  would $base"
    else
      # INVARIANT 2: preserve what is currently enforcing before replacing it.
      [ -f "$target" ] && cp -p "$target" "$target.pre-install.bak"
      install -m 0755 "$src" "$target"
      # INVARIANT 3: prove the bytes landed. cp exiting 0 is not evidence.
      got="$(sha256sum "$target" | cut -d' ' -f1)"
      [ "$got" = "$src_hash" ] || die "$member/$base verify FAILED (src $src_hash != installed $got)"
      log "  wrote $base"
    fi
    member_files_json="$member_files_json{\"file\":\"$base\",\"sha256\":\"$src_hash\"},"
  done
  any_installed=1

  [ $first_entry -eq 1 ] || installed_json="$installed_json,"
  first_entry=0
  installed_json="$installed_json{\"member\":\"$member\",\"dest\":\"$dest\",\"files\":[${member_files_json%,}]}"
done

installed_json="$installed_json]"
log ""

if [ "$any_installed" = "0" ]; then
  # Not an error: a box may legitimately host no member. But it must not silently write an
  # authority file claiming a deployment that did not happen.
  log "no member installed on this host; authority file NOT written"
  exit 0
fi

if [ "$DRY_RUN" = "1" ]; then
  log "DRY RUN complete; authority file NOT written"
  exit 0
fi

# INVARIANT 4: written last, only after every file verified.
mkdir -p "$HESTIA_HOME"
tmp="$AUTHORITY.$$.tmp"
python3 - "$tmp" "$build_id" "$head_sha" "$installed_json" <<'PY'
import json, sys, time
tmp, build_id, head_sha, installed = sys.argv[1:5]
json.dump({
    "build_id": build_id,
    "head_sha": head_sha,
    "installed_at": int(time.time()),
    "installed_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "members": json.loads(installed),
}, open(tmp, "w"), indent=2, sort_keys=True)
PY
mv "$tmp" "$AUTHORITY"
log "authority written: $AUTHORITY (build_id=$build_id)"
log ""
log "The daemon reads this via HESTIA_CURRENT_BUILD_FILE. If the dashboard still says"
log "'deployment authority is not configured', the INSTALLED unit is missing that"
log "Environment= line — deploy/templates/hestia.service carries it, so the unit is stale."
