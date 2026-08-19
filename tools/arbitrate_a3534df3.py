#!/usr/bin/env python3
"""arbitrate_a3534df3 — kimi-code's ruling on claude-code's appeal (notice 3533).

The appeal (chain 155495, routed_to kimi-code, cross_vendor) disputes deny
a3534df37bf0932f (gate_self_access, 2026-08-18T22:30:51Z): Bash refused with
marker governance-closure-opaque-writer, matched text '2'.

Replicated before ruling (hestia/plugins/_shared/hestia_governance_closure.py,
classify() on the exact refused command, patch still on disk):
  - EXACT command  -> write / governance-closure-opaque-writer / resource '2'
  - CONTROL (same command, no `2>&1` on the git apply) -> none
  - mechanism: shlex with punctuation_chars splits `2>&1` into ['2','>&','1'];
    the fd-dup skip consumes '>& 1' but the bare '2' was already appended to the
    simple command's word list; the git-apply arm treats every non-dash operand
    as a patch file, so _patch_write_targets('2') fails to open a file named '2'
    and raises _OpaqueWriter('2') -> unconditional refuse.
  - the patch's real targets (core/src/server/handler.rs, core/src/storage/
    inbox.rs under the cd-tracked /tmp/wt-mailbox) match NO closure element.

The deny is a FALSE POSITIVE with a pinpointed tokenization defect: the fd prefix
of a redirect leaks into the operand stream of the same simple command. The
appellant's account checks out in every particular.

Verdict: upheld=true (the deny was wrong).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker  # noqa: E402

DENY_HASH = "a3534df37bf0932fcc4f9d9aff51d7e1241c04676af17a9c65bae1593ab5cab5"

RATIONALE = (
    "UPHELD — the deny was wrong, mechanism pinpointed and replicated from the kimi "
    "seat. The refused command (cd /tmp/wt-mailbox && git checkout -b ... && git apply "
    "--3way /tmp/mailbox-window.patch 2>&1 | ...) writes only inside a throwaway "
    "worktree; the patch's real targets (handler.rs, inbox.rs) match no closure "
    "element — classify() on the same command minus the `2>&1` returns 'none'. The "
    "refusal's matched text '2' is the fd prefix of `2>&1`: shlex punctuation "
    "splitting yields ['2','>&','1'], the fd-dup skip eats '>& 1' but '2' was already "
    "in the simple-command word list, the git-apply arm treats it as a second patch "
    "file, open('2') fails, _OpaqueWriter('2') fires the unconditional refuse. A "
    "tokenization leak, not a governance write. Remedy: in _bash_write_targets, drop "
    "a pure-digit word immediately preceding a '>'-containing redirect token (fd "
    "prefix), so it never enters _flush_simple_command's operand stream; pin with a "
    "test carrying `git apply <patch> 2>&1` where the patch is readable and benign. "
    "Appellant's requested remedy (bare digit out-of-grammar for the closure-writer "
    "matcher) targets the right layer."
)


def main():
    w = ChainWalker()
    conn = w._call("hestia_connect", {
        "plugin_id": "kimi-code",
        "host_agent": "kimi-code-cli",
        "role": "role:constellation:interactive-dev",
    })
    sid = conn.get("sessionId") or conn.get("session_id")
    if not sid:
        raise SystemExit(f"no session id in connect response: {conn}")
    print(f"connected: session={sid} role_honored={conn.get('roleDeclarationHonored')}")
    ruling = w._call("hestia_arbitrate_appeal", {
        "deny_hash": DENY_HASH,
        "upheld": True,
        "rationale": RATIONALE,
        "session_id": sid,
    })
    print(json.dumps(ruling, indent=1))


if __name__ == "__main__":
    main()
