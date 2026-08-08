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
#   1. DERIVE THE TARGET FROM THE REGISTRATION; NEVER ASSUME IT. The copy that ENFORCES is
#      by definition the one the harness invokes, so reading the invocation MEASURES the
#      deployment instead of trusting a note about it. A declared `dest` is a declared
#      value where an audited one is available — the same class as `merged != deployed`.
#      (Mechanism folded from #273, which this PR closed in favour of; dp's disposition on
#      that close asked for exactly this fold. Measured 2026-08-08, all four members:
#      claude-code, codex and kimi declared correctly — and `gemini` declared
#      `~/.gemini/hooks`, which DOES NOT EXIST, while its three hooks are registered and
#      enforcing from a `hestia-plugins` subtree. Under the declared reading this script
#      printed "SKIP gemini — member not installed on this host" about a fully installed,
#      currently-enforcing member. That is the invariant failing in its quiet direction:
#      not "a directory exists with nothing invoking it" but "nothing is at the declared
#      directory while something IS invoking, from elsewhere.")
#
#      COROLLARY — AN ABSENT REGISTRATION MEANS THE MEMBER IS NOT ON THIS BOX. Skip it,
#      never mkdir. Creating the directory fabricates a member that was never installed,
#      and the next audit reads the fabrication as a real deployment. (From
#      member-mesh/install.sh, the only pre-existing installer that gets this right.)
#      Skipping on the REGISTRATION rather than on the DIRECTORY is the sharper test: a
#      directory can exist with nothing invoking it, and — per gemini above — can be
#      absent while the member is fully live.
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

# --- A governed session must not install its own gate. -----------------------------------
# Folded from #273. An agent that can refresh the thing that governs it is not governed, and
# it does not stop being true because the refresh is spelled as a deploy. This script is a
# WRITE POSITION THE GATE DOES NOT MARK: `_SELF_MARKERS` catches the per-plugin `hooks`
# directories, and this file sits outside all of them, so `bash deploy/install-members.sh`
# carries no marker in its command text and a governed session could reach every member's
# enforcing gate through it — including its own. The check below removes the cheap, silent
# version of that and removes "I didn't know" as an account; it does not make it impossible.
# The complete fix is a marker for this path in the gate's `_SELF_MARKERS`, which is a gate
# edit, and is disclosed here rather than quietly taken.
#
# The override exists because an operator genuinely at the keyboard inside a session should
# not be stuck — but it is loud, it is recorded in the output, and it names itself.
#
# DRY_RUN is deliberately exempt. A governed member reading which copy is enforcing is the
# measurement this whole line of work runs on; refusing it would only push the seat to
# re-derive the same answer by other means. Reading a deployment is not performing one —
# the same distinction the law already draws between `dd if=/dev/sda` and `of=/dev/sda`.
if [ "$DRY_RUN" != "1" ] && { [ -n "${CLAUDECODE:-}" ] || [ -n "${HESTIA_ROLE:-}" ]; }; then
  if [ "${HESTIA_GATE_INSTALL_ACK:-}" != "i-am-the-operator" ]; then
    cat >&2 <<'EOF'
REFUSED: this looks like a governed agent session (CLAUDECODE / HESTIA_ROLE are set).

Installing here would let a session refresh the gates that decide its own calls — and this
installer does it for EVERY member at once, so the blast radius is the whole fleet, not one
seat. That is the act the gate's self-access rule exists to make visible, and routing it
through a deploy script does not change what it is.

Run this from a plain operator shell instead. If you ARE the operator and are deliberately
running inside a session, re-run with:

    HESTIA_GATE_INSTALL_ACK=i-am-the-operator deploy/install-members.sh

which proceeds and says so in the output. DRY_RUN=1 is exempt: it writes nothing.
EOF
    exit 3
  fi
  echo "!! OVERRIDE: installing from inside an agent session on an explicit operator ack."
fi

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

  # --- decomposition: the member declares WHAT it installs, and HOW ITS HARNESS ------
  # --- records a registration. The core derives WHERE from that registration. -------
  # This is the fractal split dp asked for: the invariant (derive, never assume) stays
  # up here once; the per-harness detail (which file, which syntax) decomposes into the
  # member's own expects.json and needs no new script.
  #
  # The reader emits one `basename<TAB>absolute-path` line per registered hook. It never
  # spells an install path itself — a source file in this repo that spells one
  # contiguously is a file this repo's own gate refuses to let a governed member Write
  # (the FP8 constraint), which is also why `registration.path` is a list of SEGMENTS.
  # Command substitution, NOT `mapfile < <(...)`: a process substitution's exit status is
  # not the producer's, so the reader's SKIP codes below would all read as success.
  reg_rc=0
  reg_out="$(python3 - "$expects" <<'PY'
import json, os, re, sys

spec = (json.load(open(sys.argv[1], encoding="utf-8")).get("install") or {})
reg = spec.get("registration") or {}
segs, reader = reg.get("path") or [], reg.get("reader", "")
if not segs or not reader:
    sys.exit(2)                     # member declares no registration: caller SKIPs loudly
path = os.path.join(os.path.expanduser("~"), *segs)
if not os.path.exists(path):
    sys.exit(3)                     # harness not registered on this host: not our member

tokens = []
if reader == "json-hook-commands":
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                tokens.extend(v.split()) if k == "command" and isinstance(v, str) else walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    try:
        walk(json.load(open(path, encoding="utf-8")))
    except ValueError:
        sys.exit(4)                 # registration present but unparseable: never guess
elif reader == "toml-hook-commands":
    # Deliberately a line scan, not a TOML parse: tomllib is 3.11+ and this script must
    # run on whatever python3 the operator's box has. Only `command = "..."` is read.
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"""\s*command\s*=\s*(['"])(.*)\1\s*$""", line)
        if m:
            tokens.extend(m.group(2).split())
else:
    sys.exit(5)                     # unknown reader: a typo must not read as "no hooks"

seen = set()
for tok in tokens:
    # A hook command is `ENV=v python3 /abs/path/hook.py`; the target is the token that is
    # an absolute path, and its DIRECTORY is where the harness actually invokes from.
    if tok.startswith("/") and os.path.basename(tok) not in seen:
        seen.add(os.path.basename(tok))
        print(f"{os.path.basename(tok)}\t{tok}")
PY
)" || reg_rc=$?
  case "$reg_rc" in
    2) log "SKIP  $member — declares no install.registration (nothing to derive a target from)"; any_skipped=1; continue ;;
    3) log "SKIP  $member — its harness registration file is absent (member not on this host)"; any_skipped=1; continue ;;
    4) log "SKIP  $member — registration file present but unparseable; refusing to guess a target"; any_skipped=1; continue ;;
    5) die  "$member declares an unknown install.registration.reader" ;;
  esac

  declare -A registered=()
  while IFS=$'\t' read -r reg_base reg_path; do
    [ -n "$reg_base" ] && registered["$reg_base"]="$reg_path"
  done <<< "$reg_out"

  mapfile -t files < <(python3 -c '
import json,sys
for f in (json.load(open(sys.argv[1])).get("install") or {}).get("files",[]):
    print(f)' "$expects")

  [ "${#files[@]}" -gt 0 ] || { log "SKIP  $member — install.files is empty"; any_skipped=1; continue; }

  # The declared `dest` is KEPT — but as a CLAIM THIS SCRIPT CHECKS, never as a value it
  # uses. Deleting it would delete the only place the drift can be caught; using it is the
  # defect. Divergence is the signal that a member's manifest has rotted away from its
  # harness, and it is exactly how gemini's was found.
  declared="$(python3 -c '
import json,os,sys
p=((json.load(open(sys.argv[1])).get("install") or {}).get("dest") or "")
print(os.path.expanduser(p) if p else "")' "$expects")"

  log "MEMBER $member"
  member_files_json=""
  for rel in "${files[@]}"; do
    src="$REPO_ROOT/plugins/$member/$rel"
    [ -f "$src" ] || die "$member declares '$rel' but $src does not exist"
    base="$(basename "$rel")"

    target="${registered[$base]:-}"
    if [ -z "$target" ]; then
      # NOT an error and NOT a silent success: a host that does not register this hook has
      # nothing to deploy, which is a different outcome from "deployed". Same reason the
      # deploy gauge must not read amber as green.
      log "  skip  $base — not registered on this host"
      any_skipped=1
      continue
    fi
    target_dir="$(dirname "$target")"
    [ -d "$target_dir" ] || die "$member/$base is registered at $target but $target_dir does not exist"
    if [ -n "$declared" ] && [ "$target_dir" != "$declared" ]; then
      warn "$member/$base: expects.json declares '$declared' but the harness invokes it from '$target_dir' — installing to the REGISTERED path; fix the declaration"
    fi

    src_hash="$(sha256sum "$src" | cut -d' ' -f1)"
    if [ -f "$target" ] && [ "$(sha256sum "$target" | cut -d' ' -f1)" = "$src_hash" ]; then
      log "  ok    $base (already current) -> $target_dir"
    elif [ "$DRY_RUN" = "1" ]; then
      log "  would $base -> $target_dir"
    else
      # INVARIANT 2: preserve what is currently enforcing before replacing it.
      [ -f "$target" ] && cp -p "$target" "$target.pre-install.bak"
      install -m 0755 "$src" "$target"
      # INVARIANT 3: prove the bytes landed. cp exiting 0 is not evidence.
      got="$(sha256sum "$target" | cut -d' ' -f1)"
      [ "$got" = "$src_hash" ] || die "$member/$base verify FAILED (src $src_hash != installed $got)"
      log "  wrote $base -> $target_dir"
    fi
    # The recorded path is the DERIVED one, so the authority file says where the bytes
    # actually went — not where a manifest said they would. An audit that reads this can
    # now be checked against the live registration instead of against the same claim.
    member_files_json="$member_files_json{\"file\":\"$base\",\"path\":\"$target\",\"sha256\":\"$src_hash\"},"
  done

  # A member every one of whose files was unregistered installed NOTHING; recording it
  # would be invariant 4's failure one level down — a partial (here, empty) install
  # written up as a deployment.
  if [ -z "$member_files_json" ]; then
    log "SKIP  $member — none of its declared files are registered on this host"
    any_skipped=1
    continue
  fi
  any_installed=1

  [ $first_entry -eq 1 ] || installed_json="$installed_json,"
  first_entry=0
  installed_json="$installed_json{\"member\":\"$member\",\"declared_dest\":\"$declared\",\"files\":[${member_files_json%,}]}"
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
