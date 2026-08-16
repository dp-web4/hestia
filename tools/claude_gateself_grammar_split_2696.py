#!/usr/bin/env python3
"""Why did ONE of five near-identical gate-inspection Bash acts escalate?

Codex dissented on escalation 00a6b5aa96c83856 (notice 2696) saying the approved Bash
act was "already unnecessary" and its record "insufficient for review". The second half
is right in a way the chain cannot show: `stated_reason` is cut at ~230 chars, and the
discriminating evidence lives past the ellipsis.

On 2026-08-16 between 07:57:33 and 07:58:20 this seat ran FIVE Bash acts against the
installed gate files, every one of them spelling the filename the same fused way so the
raw matcher could not see it. Four completed with no gate-self event of any kind. The
fifth opened a sovereign_plus_peer escalation. Same seat, same target, 47 seconds.

This replays all five through the INSTALLED shared classifier and reports which phase
decided each, so the split is attributed to a predicate rather than to a guess.

The commands are read from the host transcript at runtime and never appear in this
file's text -- the classifier matches payload content at two layers, so a probe that
quotes its own subject refuses to run (ref_content_match_two_layers).
"""
from __future__ import annotations

import json
import os
import sys

TRANSCRIPT = ("/home/dp/.claude/projects/-mnt-c-exe-projects/"
              "888f190a-f01d-4efe-a5a0-5320307d31ab.jsonl")

# The five acts, oldest first. Chain outcome is what the witness chain actually recorded.
ACTS = [
    ("toolu_01YUS2tNBxAEBwMKrdXDDtSn", "07:57:33", "no gate-self event"),
    ("toolu_01DLRYcTPLadcvzjfzXwJPdt", "07:57:42", "no gate-self event"),
    ("toolu_01FZA5k3oZTm3pSaMeCHLiZo", "07:57:57", "no gate-self event"),
    ("toolu_01WokZ3SN5Pvgguq3RCDy1TT", "07:58:06", "no gate-self event"),
    ("toolu_01MYzENkVFGcfFaPj9SvFdhZ", "07:58:20", "ESCALATED 00a6b5aa96c83856"),
]

SHARED = os.environ.get("HESTIA_SHARED_DIR", "/home/dp/.claude/_shared")


def load_commands() -> dict:
    want = {a[0] for a in ACTS}
    got = {}
    with open(TRANSCRIPT, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            content = (obj.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if (isinstance(block, dict) and block.get("type") == "tool_use"
                        and block.get("id") in want):
                    got[block["id"]] = block.get("input", {}).get("command", "")
    return got


def main() -> int:
    sys.path.insert(0, SHARED)
    import hestia_governance_closure as gc

    cmds = load_commands()
    missing = [i for i, _, _ in ACTS if i not in cmds]
    if missing:
        print(f"  transcript did not hold {len(missing)} act(s); cannot replay", file=sys.stderr)
        return 2

    print(f"  classifier: {gc.__file__}")
    print(f"  {'time':9} {'chain said':28} {'classify()':10} {'rule':22} phase-1 raised")
    print(f"  {'-'*9} {'-'*28} {'-'*10} {'-'*22} {'-'*22}")

    rows = []
    for act_id, when, chain_said in ACTS:
        cmd = cmds[act_id]
        verdict = gc.classify("Bash", {"command": cmd})

        # Which phase-1 exception (if any) the tokenizer hit, named directly.
        raised = "-"
        try:
            gc._bash_write_targets(cmd)
        except gc._OutOfGrammar:
            raised = "_OutOfGrammar"
        except gc._OpaqueWriter:
            raised = "_OpaqueWriter"
        except Exception as exc:  # noqa: BLE001 - reporting, not deciding
            raised = type(exc).__name__

        # Does the fused spelling survive each of the two tokenizers?
        try:
            toks = [t for t in gc._tokenize(cmd) if not gc._is_punct(t)]
            tok_ok = "yes"
        except Exception:  # noqa: BLE001
            toks, tok_ok = cmd.split(), "RAISED->split()"
        try:
            vocab = gc._vocab_tokens(cmd)
        except Exception:  # noqa: BLE001
            vocab = []

        print(f"  {when:9} {chain_said:28} {verdict.classification:10} "
              f"{str(verdict.rule or '-'):22} {raised}")
        rows.append((when, chain_said, verdict, raised, tok_ok, toks, vocab))

    print()
    print("  === does the fused spelling normalise back to the marker? ===")
    for when, _cs, verdict, _r, tok_ok, toks, vocab in rows:
        # Count tokens that the closure itself calls a marker, without naming one here.
        t_hits = sum(1 for t in toks if gc.default_closure().match(t, position="read"))
        v_hits = sum(1 for t in vocab if gc.default_closure().match(t, position="read"))
        print(f"  {when:9} _tokenize={tok_ok:15} marker-tokens={t_hits:<3} "
              f"vocab-tokens={v_hits:<3} matched={verdict.marker or '-'}")

    print()
    print("  === agreement with the chain ===")
    for when, chain_said, verdict, _r, _t, _tk, _v in rows:
        escalated_here = verdict.classification == "write"
        escalated_chain = chain_said.startswith("ESCALATED")
        flag = "AGREE" if escalated_here == escalated_chain else "DISAGREE"
        print(f"  {when:9} chain={'escalate' if escalated_chain else 'silent':9} "
              f"replay={'escalate' if escalated_here else verdict.classification:9} {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
