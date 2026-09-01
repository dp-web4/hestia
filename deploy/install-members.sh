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

# ORDER IS LOAD-BEARING: the engine is installed and $HESTIA_HOME/shared is repointed
# BEFORE any hook entrypoint is written. Hooks import their decision engine from that
# symlink, so installing a hook first opens a window in which the installed hook is newer
# than the engine it imports -- and since 2026-08-31 the seats import the shared shell
# classifier with no local copy to fall back to, that window is a hook that cannot start.
# The engine swap is already atomic (build dir, verify digests, rename the symlink); this
# ordering is what makes the whole install atomic from a hook's point of view.
# --- THE SHARED ENGINE IS AN INSTALL ARTIFACT TOO. ----------------------------------------
# Every hook entrypoint installed below imports its decision engine from plugins/_shared/ —
# and until now the ledger bound the entrypoints and ZERO bytes of the engine they call
# (#481: current-build.json binds hook entrypoints but 0 bytes of _shared; the hooks digested
# to installed paths while the engine executed from the mutable workspace checkout). An audit
# that digests the hook but not the engine the hook imports proves the shape of the gate, not
# its decisions.
#
# WHAT IS INSTALLED IS WHAT THE MANIFEST DECLARES (#525 review, the "option B" ruling). The
# runtime set is plugins/_shared/RUNTIME_MANIFEST.txt, one filename per line — NOT a glob of
# the directory, because _shared holds the tests beside the engine, and "which files are
# engine" as an implicit rule is exactly the rule that drifts. The manifest declares; this
# script deploys precisely that set; the test suite pins the declaration against what the
# hooks actually import, in both directions.
#
# THE ACTIVE SET IS EXACTLY THE RECORDED SET. A per-file overwrite loop leaves a deleted or
# renamed module live on disk while the ledger stops naming it — bytes executable that no
# deployment truth represents, the failure the #525 review blocked on. So the engine installs
# as ONE content-addressed build: stage every declared file into a fresh directory, verify
# each digest THERE, and only then point $HESTIA_HOME/shared — a symlink — at the verified
# build with a single atomic rename. Three consequences, each load-bearing:
#   * a source file deleted in build N+1 is absent from build N+1's directory, so it leaves
#     the ACTIVE set the moment the symlink flips — ledger and executable set cannot disagree;
#   * an interrupted install never flips, so the running engine is never a half-written mix
#     of two builds;
#   * old builds stay, content-addressed and inert — they ARE the backup invariant 2 asks
#     for, and a build whose bytes no longer match its address is quarantined, never reused.
# The ledger still records the stable active paths ($HESTIA_HOME/shared/<file>) and is still
# written last, only on full success — a failed stage or verify dies BEFORE any flip.
#
# What is deliberately NOT here: plugins/lib/path_scope.py (gemini's installed lib) is copied
# by plugins/gemini/install.sh, a different installer with its own discipline. Folding it in
# would mean this script deriving gemini's ext4 layout — the one-off shape this script exists
# to end. Recording gemini's lib belongs to gemini's installer gaining ledger discipline, not
# to this section reaching sideways.
log "SHARED ENGINE (plugins/_shared)"
engine_manifest="$REPO_ROOT/plugins/_shared/RUNTIME_MANIFEST.txt"
[ -f "$engine_manifest" ] || die "plugins/_shared/RUNTIME_MANIFEST.txt is missing — the engine set is a declaration, not a glob"
mapfile -t engine_names < <(grep -vE '^[[:space:]]*(#|$)' "$engine_manifest")
[ "${#engine_names[@]}" -gt 0 ] || die "RUNTIME_MANIFEST.txt declares no files — refusing to record an empty engine"

engine_hashes=()
set_fingerprint=""
for base in "${engine_names[@]}"; do
  src="$REPO_ROOT/plugins/_shared/$base"
  [ -f "$src" ] || die "RUNTIME_MANIFEST.txt declares '$base' but $src does not exist"
  src_hash="$(sha256sum "$src" | cut -d' ' -f1)"
  engine_hashes+=("$src_hash")
  set_fingerprint="$set_fingerprint$src_hash  $base
"
done
# One address for the whole set: the build directory's name IS the digests of its contents.
build_digest="$(printf '%s' "$set_fingerprint" | sha256sum | cut -c1-16)"
builds_dir="$HESTIA_HOME/shared.builds"
build_dir="$builds_dir/$build_digest"
shared_link="$HESTIA_HOME/shared"

# Every declared file present in $1, each hashing to its declared digest. Applied to the
# STAGED set before it may become active, and to an existing build before it may be reused.
engine_build_ok() {
  local i
  for i in "${!engine_names[@]}"; do
    [ -f "$1/${engine_names[$i]}" ] || return 1
    [ "$(sha256sum "$1/${engine_names[$i]}" | cut -d' ' -f1)" = "${engine_hashes[$i]}" ] || return 1
  done
}

shared_engine_json="["
for i in "${!engine_names[@]}"; do
  [ "$i" -eq 0 ] || shared_engine_json="$shared_engine_json,"
  # Same record shape as the member files below, so one audit reads both sections. The path
  # is the stable ACTIVE path, not the build directory: the symlink is the contract.
  shared_engine_json="$shared_engine_json{\"file\":\"${engine_names[$i]}\",\"path\":\"$shared_link/${engine_names[$i]}\",\"sha256\":\"${engine_hashes[$i]}\"}"
done
shared_engine_json="$shared_engine_json]"

if [ "$DRY_RUN" = "1" ]; then
  for base in "${engine_names[@]}"; do
    log "  would $base -> $shared_link (build $build_digest)"
  done
else
  mkdir -p "$builds_dir"
  # Staging dirs from an interrupted run are inert — nothing points at them. Sweep them.
  for stale in "$builds_dir"/.staging.*; do
    [ -e "$stale" ] && rm -rf "$stale"
  done

  if [ -d "$build_dir" ]; then
    if engine_build_ok "$build_dir"; then
      log "  ok    build $build_digest (already staged, re-verified)"
    else
      # A content-addressed directory whose bytes no longer match their address: an installed
      # engine file was rewritten after deploy. Quarantine loudly; never silently reuse. The
      # symlink dangles until the rebuild below lands — the honest direction for a tampered
      # engine is to fail, not to coast on bytes the ledger no longer recognizes.
      warn "build $build_digest FAILED re-verification — quarantining as $build_dir.corrupt.$$ and rebuilding"
      mv "$build_dir" "$build_dir.corrupt.$$"
    fi
  fi
  if [ ! -d "$build_dir" ]; then
    staging="$builds_dir/.staging.$$"
    mkdir -p "$staging"
    for i in "${!engine_names[@]}"; do
      # Imported, not executed: 0644, not the entrypoints' 0755.
      install -m 0644 "$REPO_ROOT/plugins/_shared/${engine_names[$i]}" "$staging/${engine_names[$i]}"
    done
    # INVARIANT 3: prove the bytes landed — the WHOLE staged set, before it can become active.
    engine_build_ok "$staging" || die "engine build $build_digest verify FAILED in staging; nothing was activated"
    mv "$staging" "$build_dir"
    log "  wrote build $build_digest (${#engine_names[@]} files, staged and verified)"
  fi

  # THE FLIP: one atomic rename of a symlink. Before it, the active engine is untouched;
  # after it, it is exactly the verified build. There is no between.
  if [ -e "$shared_link" ] && [ ! -L "$shared_link" ]; then
    # A pre-symlink install left shared/ as a real directory. INVARIANT 2: preserve, then move.
    warn "migrating legacy shared/ directory aside to $shared_link.pre-flip.bak"
    mv "$shared_link" "$shared_link.pre-flip.bak"
  fi
  current_target="$(readlink "$shared_link" 2>/dev/null || true)"
  if [ "$current_target" = "shared.builds/$build_digest" ]; then
    log "  ok    shared -> $current_target (already current)"
  else
    flip="$HESTIA_HOME/.shared.flip.$$"
    ln -s "shared.builds/$build_digest" "$flip"
    python3 -c 'import os, sys; os.rename(sys.argv[1], sys.argv[2])' "$flip" "$shared_link"
    log "  wrote shared -> shared.builds/$build_digest"
  fi
fi

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
  #
  # 2026-08-18: the divergence is STRUCTURAL for claude-code, not a stale string. Three
  # layouts are now measured, one per seat that looked:
  #   declaration  ~/.claude/hooks/hestia          (an installed hooks dir)
  #   Legion       ~/.claude/plugins/hestia/hooks  (a different installed subtree)
  #   HUB          the hestia git checkout, in place — the declared dir does not exist there
  # No single string is right for all three, so the warning below must NOT tell the operator
  # to "fix the declaration": that instruction is unsatisfiable fleet-wide and would invite
  # someone to pick a winner and break the other two seats. What is per-seat is the SHAPE of
  # the answer, not just its content. HUB's case is the sharp one — its enforcing copy is a
  # working tree, so `git pull` is a gate deployment there and a survey keyed on installed
  # paths reads HUB as ungated while it runs the newest code in the fleet.
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
      warn "$member/$base: expects.json declares '$declared' but the harness invokes it from '$target_dir' — installing to the REGISTERED path. The declared value is a per-seat CLAIM this run just checked, not a fleet-wide target: layouts differ by seat, so this divergence may be structural rather than a stale string to correct"
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

log ""

if [ "$DRY_RUN" = "1" ]; then
  log "DRY RUN complete; authority file NOT written"
  exit 0
fi

# INVARIANT 4: written last, only after every file verified.
mkdir -p "$HESTIA_HOME"
tmp="$AUTHORITY.$$.tmp"
python3 - "$tmp" "$build_id" "$head_sha" "$installed_json" "$shared_engine_json" <<'PY'
import json, sys, time
tmp, build_id, head_sha, installed, shared_engine = sys.argv[1:6]
json.dump({
    "build_id": build_id,
    "head_sha": head_sha,
    "installed_at": int(time.time()),
    "installed_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "members": json.loads(installed),
    # Additive (#481 stage 1): the only shipped consumer reads `build_id` alone
    # (core/src/server/dashboard.rs's deployment_health), so nothing existing
    # can be broken by a key it never looks up.
    "shared_engine": json.loads(shared_engine),
}, open(tmp, "w"), indent=2, sort_keys=True)
PY
mv "$tmp" "$AUTHORITY"
log "authority written: $AUTHORITY (build_id=$build_id)"
log ""
log "The daemon reads this via HESTIA_CURRENT_BUILD_FILE. If the dashboard still says"
log "'deployment authority is not configured', the INSTALLED unit is missing that"
log "Environment= line — deploy/templates/hestia.service carries it, so the unit is stale."
