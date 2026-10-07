# held/: the governed half of PR #1239, NOT applied

This directory holds the **governed producer half** of #1239 (recut of #812, #810), kept as a
plain patch file so that reviewers see the exact bytes and a scratchpad wipe cannot lose them.
**Nothing here is applied.** The files it touches are the governance surface, so they land only
through the gate's escalation channel after review.

| file | sha256 |
|---|---|
| `574426d6772d36bf2630cb94bf4b82d1b1d2b07a0db18651d9808158ca2d825b.patch` | `574426d6772d36bf2630cb94bf4b82d1b1d2b07a0db18651d9808158ca2d825b` |

The filename is the patch's own sha256, so `sha256sum` verifies it.

## What it changes (14 files, +482/−89)

- **Shared mechanism (`claim_self_write`).** It sends `resolved_targets`, a list of full paths
  covering every governed write target, not only the first.
  - A target path that is itself credential-shaped rides as the `hestia:unpriceable:credential-path`
    sentinel. It is never dropped.
  - More than 16 targets adds an `overflow` sentinel. A write set the gate could not enumerate
    adds an `unenumerated` sentinel. The daemon prices every sentinel at the highest bar.
  - Summary redaction never touches the targets.
- **Common gate.** It sends the whole closure write set (`_closure_write_set`) beside the bounded
  act summary.
- **Closure.** A new `write_verdicts()` returns one write verdict per governed write-position
  argument, for every rule. `classify()` is unchanged: it still stops at the first.
- **Tests.**
  - claim_self_write: 39 checks, including P1-2, P1-3, overflow, unenumerated and the glob target.
  - seat_gate_boundary, run against every seat: every target is carried; a 27-target `touch`
    with the gate last carries every governed target; `rm <hooks>/*.py` carries the glob.
  - governance_closure: `write_verdicts`.
- **hooks-gt republish.** 3 engine copies and 5 manifests. The shared `gt_version` becomes
  `57780458edde9432c199a707ef829e4b4a910bfc5926da36c9f0e922c33f1062`.

The daemon half (pricing over the target list, spend-time price, unpriceable and glob rules) is
ordinary code in this PR, under `core/`.

## How it was built and checked

- Each governed source was extracted read-only into a neutral-named scratch copy and edited
  there. The patch was emitted against this branch's tree; the hooks-gt half was computed with
  `tools/hooks_gt.py`'s own functions and verified the same way `hooks_gt.py check` verifies.
- `git apply --check` is clean on the commit that adds this file.
- 14/14 Python suites are green with the patched modules supplied through
  `HESTIA_CONTRACT_OVERLAY`. The new checks are RED against the unpatched copies.

## Lineage

- `d39341b1…`: the first producer patch, before Codex's P1s. It survives as commit 4ea3882 on
  #1247's branch.
- `863c5296…`: the post-P1 patch sent to Codex as notice 17632. It was lost in a scratchpad wipe
  and rebuilt here by re-applying the same edits.
- `574426d6…` (this patch): the rebuild, plus the glob battery row (kimi, #1231 review Q4).
  Expect small wording differences from `863c5296` in comments and docstrings. I couldn't
  byte-compare the two because the earlier patch is gone.
