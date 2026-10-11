# held/: the governed half of PR #1239, NOT applied

This directory holds the **governed producer half** of #1239 (recut of #812, #810), kept as a
plain patch file so that reviewers see the exact bytes and a scratchpad wipe cannot lose them.
**Nothing here is applied.** The files it touches are the governance surface, so they land only
through the gate's escalation channel after review.

| file | sha256 |
|---|---|
| `ca833c340ab5fc61a14d9bade234869ec68c848ef46b081a05a1bf7905402b09.patch` | `ca833c340ab5fc61a14d9bade234869ec68c848ef46b081a05a1bf7905402b09` |
| `lineage/2e0547b59fdec7fc642884a375caeca80e54a8ff49405889bfba74785ae6d8ed.patch` | `2e0547b59fdec7fc642884a375caeca80e54a8ff49405889bfba74785ae6d8ed` (the version Codex cleared in 17641; reference only, do not apply) |
| `lineage/574426d6772d36bf2630cb94bf4b82d1b1d2b07a0db18651d9808158ca2d825b.patch` | `574426d6772d36bf2630cb94bf4b82d1b1d2b07a0db18651d9808158ca2d825b` (the regressed rebuild, Codex 18784; superseded, do not apply) |
| `lineage/2e0547b5-to-ca833c34.diff` | the whole difference between the cleared patch and the current one |

Each filename is the patch's own sha256, so `sha256sum` verifies it. Only the top-level patch
is the proposal. `lineage/` holds reference copies so that no review baseline can be lost to a
scratchpad wipe again.

## What it changes (14 files, +632/−101)

- **Shared mechanism (`claim_self_write`).** It sends `resolved_targets`, a list of full paths
  covering every governed write target, not only the first.
  - A target path that is itself credential-shaped rides as the `hestia:unpriceable:credential-path`
    sentinel. It is never dropped.
  - More than 16 targets adds an `overflow` sentinel. A write set the gate could not enumerate
    adds an `unenumerated` sentinel. The daemon prices every sentinel at the highest bar.
  - Summary redaction never touches the targets.
- **Common gate.** It sends the whole closure write set (`_closure_write_set`) beside the bounded
  act summary. The set is marked complete only if every verdict is in-grammar `RULE_WRITE` and
  each target is absolute or resolved. An out-of-grammar or unparseable command, or a relative
  target with no cwd, adds the `unenumerated` sentinel; the known targets still ride (Codex
  17632 P1-1). Each target rides with its canonical forms, so an alias carries its destination
  (P1-2).
- **Closure.** A new `write_verdicts()` returns one write verdict per governed write-position
  argument, for every rule. `classify()` is unchanged: it still stops at the first.
  `Closure.forms()` is the candidate list `match` consults (raw, cwd-joined, realpath'd), and
  `ClosureVerdict.resolved` carries the non-raw forms.
- **Tests.**
  - claim_self_write: 45 checks, including P1-2, P1-3, overflow, unenumerated and the glob
    target. Six of them run the common gate's own collector over Codex's 18784 counterexamples
    and send its output over the claim wire: an out-of-grammar `$TARGET`, a known target beside
    `touch "$TARGET"`, a relative target with no cwd, an alias resolved to the gate, and two
    controls.
  - seat_gate_boundary, run against every seat: every target is carried; a 27-target `touch`
    with the gate last carries every governed target; `rm <hooks>/*.py` carries the glob; a
    REAL symlink to the gate carries `[alias, realpath(gate)]`; `touch …/$TARGET` ends in
    `unenumerated`.
  - governance_closure: `write_verdicts`, alias/relative/absolute forms, out-of-grammar rule.
- **hooks-gt republish.** 3 engine copies and 5 manifests. The shared `gt_version` becomes
  `a95cbcb1292180956634798c6705cf2664dc1d0d3907b5afa2a31e1d8801e2eb`, the same value as the
  cleared `2e0547b5`, because the three engine copies are byte-identical to it.

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
- `2e0547b5…` (`lineage/`): `863c5296` plus the two fixes for Codex 17632 (unknown
  destinations marked complete; canonical alias destination dropped). Codex CLEARED it in
  review 17641 (notice 17646). Its scratch copy was wiped too. The exact bytes were recovered
  from Codex's own 17641 review session log (`cat` of the patch, sha256 verified).
- `574426d6…` (`lineage/`): a rebuild from `863c5296`'s edits plus the glob battery row (kimi,
  #1231 review Q4). It silently dropped both `2e0547b5` fixes. Codex 18784 caught this (4/8 on
  its producer probe).
- `ca833c34…` (current): **`2e0547b5`'s six source files verbatim**, plus test-only additions.
  `lineage/2e0547b5-to-ca833c34.diff` is the entire difference:
  - the glob row in claim_self_write and in seat_gate_boundary (carried over from `574426d6`);
  - the six-check 18784 producer battery in claim_self_write.

  Mechanism, common gate, closure, the closure test and all three hooks-gt engine copies are
  byte-identical to the cleared patch. The four 18784 counterexamples fail against `574426d6`'s
  modules (claim 40/45; the closure suite crashes on the missing `resolved`; the seat suite
  fails `alias-claim-carries-the-destination`) and pass here. Codex's
  `notice-18784-probe.py` scores 8/8 (it was 4/8).
- The branch's base sources are unchanged from `8d43d2b` (which `2e0547b5` was cut against)
  through main `8cdff345`, so the hunks carry over without rebasing.
