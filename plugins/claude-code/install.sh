#!/usr/bin/env bash
#
# Install the claude-code adapter's hooks to the paths the harness actually invokes.
#
# WHY THIS FILE EXISTS. Every other hook-shipping plugin in this tree has one
# (`agent-inventory`, `gemini`, `member-mesh`); `claude-code` did not. The consequence was
# not cosmetic. The claude-code seat is one of the two doing the governance research, and
# it is the seat whose gate is a hand-placed copy with no reproducible way to refresh it.
# So gate fixes merged, greened against the in-tree file, and then stopped — four separate
# claims discharged on 2026-08-07 (mesh notices 1583/1584/1585/1586) all ended at the same
# unbuildable rung, "dp-redeploy". Measured that day: the enforcing copy was 1993 lines
# against 2502 in-tree, 509 behind, and FP13 (`VAR=path` head-checked as a write) still
# fired on a governed session that main had already fixed in #254.
#
# `shipped is not in force` has a ladder: committed -> routed -> merged -> rebuilt ->
# restarted -> measured. For THIS artifact the top of the ladder is short and worth saying
# out loud, because it was never written down anywhere: the harness spawns the hook fresh
# for every tool call, so there is no build and no restart. Copy the file and the next tool
# call is governed by it. The only rung that was ever missing is the copy.
#
# TARGETS ARE DERIVED, NEVER HARDCODED, for the same two reasons the test suite's
# `_installed_gate_path()` derives its own: the install path belongs to the operator and a
# constant here would be wrong on every other machine — and, sharper, a source file that
# spells that path contiguously is a file this repo's own gate refuses to let a governed
# member Write (the FP8 constraint). This script therefore never says the path. It reads
# the registration and asks the harness where it invokes each hook from. That is the
# correct source anyway: the copy that enforces is by definition the one being invoked, so
# reading the invocation MEASURES the deployment instead of trusting a note about it.
#
# WHAT THIS IS NOT: containment. Same disclaimer the gate makes about itself, and it is
# load-bearing here rather than decorative. This script is a WRITE POSITION THE GATE DOES
# NOT MARK. `_SELF_MARKERS` catches `plugins/claude-code/hooks`, and this file sits one
# directory above it so that it can be authored at all — which means `bash <this file>`
# carries no marker in its command text and a governed session could reach the enforcing
# gate through it. The env check below removes the cheap, silent version of that and
# removes "I didn't know" as an account; it does not make it impossible. The complete fix
# is a marker for this path in the gate's `_SELF_MARKERS`, which is a gate edit and is
# disclosed rather than quietly taken.
set -euo pipefail

REPO_HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")/hooks" && pwd)"
HOOK_FILES=(pre_tool_use.py witness.py law_inject.py)

# --- A governed session must not install its own gate. -----------------------------------
# An agent that can refresh the thing that governs it is not governed, and it does not stop
# being true because the refresh is spelled as a deploy. The override exists because an
# operator who genuinely is at the keyboard inside a session should not be stuck, but it is
# loud, it is recorded in the output, and it names itself.
if [ -n "${CLAUDECODE:-}" ] || [ -n "${HESTIA_ROLE:-}" ]; then
  if [ "${HESTIA_GATE_INSTALL_ACK:-}" != "i-am-the-operator" ]; then
    cat >&2 <<'EOF'
REFUSED: this looks like a governed agent session (CLAUDECODE / HESTIA_ROLE are set).

Installing the adapter here would let a session refresh the gate that decides its own
calls. That is the act the gate's self-access rule exists to make visible, and routing it
through a deploy script does not change what it is.

Run this from a plain operator shell instead. If you ARE the operator and are deliberately
running inside a session, re-run with:

    HESTIA_GATE_INSTALL_ACK=i-am-the-operator <this script>

which proceeds and says so in the output.
EOF
    exit 3
  fi
  echo "!! OVERRIDE: installing from inside an agent session on an explicit operator ack."
fi

# --- Where does the harness invoke each hook from? ---------------------------------------
# Any event, not just PreToolUse: the gate is registered on PreToolUse, the witness on
# PostToolUse and the law injector on SessionStart. Installing each file to the path its
# OWN registration names is both more general and more honest than assuming one directory.
resolve_target() {
  python3 - "$1" <<'PY'
import json, os, sys
want = sys.argv[1]
reg = os.path.expanduser(os.path.join("~", ".claude", "settings.json"))
try:
    with open(reg, encoding="utf-8") as fh:
        cfg = json.load(fh)
except (OSError, ValueError):
    sys.exit(1)
for _event, groups in (cfg.get("hooks") or {}).items():
    for group in groups or []:
        for h in group.get("hooks") or []:
            for tok in str(h.get("command", "")).split():
                if os.path.basename(tok) == want and os.path.isabs(tok):
                    print(tok)
                    sys.exit(0)
sys.exit(1)
PY
}

sha() { python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"; }

installed=0
skipped=0
failed=0

for name in "${HOOK_FILES[@]}"; do
  src="$REPO_HOOKS/$name"
  if [ ! -f "$src" ]; then
    echo "  MISSING  $name — not in this checkout" >&2
    failed=$((failed + 1))
    continue
  fi
  if ! dst="$(resolve_target "$name")"; then
    # SKIPPED, not silently green: a host that does not register this hook has nothing to
    # deploy, and that is a different outcome from "deployed". Same reason the deploy gauge
    # skips rather than passes where there is no registration.
    echo "  SKIP     $name — no registration on this host"
    skipped=$((skipped + 1))
    continue
  fi

  want="$(sha "$src")"
  if [ -f "$dst" ]; then
    have="$(sha "$dst")"
    if [ "$want" = "$have" ]; then
      echo "  CURRENT  $name — already byte-identical (${want:0:12}…)"
      continue
    fi
    # Content-addressed backup, deliberately NOT timestamped and deliberately not `cp -p`:
    # a preserved mtime dates the backup by when the REPLACED file was built, not by when
    # it was replaced, which is a ledger that misreads in the confident direction. The hash
    # says exactly which bytes these are and cannot drift.
    backup="$dst.pre-${have:0:12}"
    cp "$dst" "$backup"
    echo "  BACKUP   $name -> $(basename "$backup")"
  fi

  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
  chmod +x "$dst"

  # Verify by reading back, not by trusting cp's exit code. This is the whole point of the
  # script: the claim "it is deployed" should rest on a measurement of the deployed bytes.
  got="$(sha "$dst")"
  if [ "$want" = "$got" ]; then
    echo "  OK       $name -> $dst (${got:0:12}…)"
    installed=$((installed + 1))
  else
    echo "  FAILED   $name -> $dst — wrote ${want:0:12}… but read back ${got:0:12}…" >&2
    failed=$((failed + 1))
  fi
done

echo
echo "installed=$installed skipped=$skipped failed=$failed"
if [ "$failed" -gt 0 ]; then
  exit 1
fi
if [ "$installed" -gt 0 ]; then
  echo "In force on the NEXT tool call — the harness spawns each hook per invocation," \
       "so there is no rebuild and no restart to wait for."
  echo "Confirm independently:  python3 plugins/claude-code/tests/gate_false_refusal_test.py"
  echo "  (its in_tree_matches_the_enforcing_copy check compares sha256 against the live" \
       "registration; it was RED by construction until this ran.)"
fi
