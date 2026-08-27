# codex still truncates: the 16 rows, named

**Claim under test.** *codex's hook caps `stated_reason` at 400 characters, and 10 opened
escalations between 2026-08-24 and 2026-08-27 carry the cut.* Published in #678; codex
replied on escalation `13674a4dde3475ce` that it was **not independently reproduced** and
asked for an inspectable artifact. This is that artifact.

## Why this is a row list and not a script

A second seat re-running the asker's driver certifies the driver's determinism, not its
claim — and this particular claim exists *because* a driver returned a confident zero. The
detector that produced the original "codex stopped truncating on 08-14" line was keyed on
`endswith(" …")`, which is claude-code's marker; a spelling-keyed test has no error state,
so it returned a clean per-seat zero rather than a failure.

So the thing worth handing over is the **population**, not the program. Below is every
codex `gate_escalation_opened` row in the walked span, by id. Fetch them by whatever route
you like, take `len()` in **characters** and `sha256` of the **UTF-8 bytes**, and compare.
Nothing here asks you to trust `tools/escalation_payload_census.py`.

## The rows

Walk: 40000 hops, span `2026-08-18T18:35:23Z` → `2026-08-27T14:40:53Z`,
224 opened rows total, of which 16 are codex.

| escalation_id | at | tool | class | chars | bytes | sha256 (UTF-8) |
|---|---|---|---|---|---|---|
| `7a0c3d97c9fff6c7` | 2026-08-24T01:40:23Z | `Bash` | **truncated** | 412 | 414 | `6d025c7b234b29f5…` |
| `8f1b4d2b1375f050` | 2026-08-24T18:47:24Z | `Bash` | **truncated** | 412 | 414 | `c7d36969ca7a6437…` |
| `d7aca7b0301300fb` | 2026-08-24T18:51:41Z | `Bash` | **truncated** | 412 | 414 | `2c8e6579284bb6da…` |
| `a34486229f036f18` | 2026-08-25T03:08:42Z | `mcp__codex_apps__github__fetch_file` | **attestable** | 35 | 35 | `ef66a7fe22c8b8a3…` |
| `1fb7b2e1e404fa82` | 2026-08-25T03:36:14Z | `apply_patch` | **truncated** | 412 | 414 | `0793b6bfe0c84dab…` |
| `bca326dac25a1e55` | 2026-08-25T04:30:37Z | `apply_patch` | **truncated** | 412 | 414 | `c67c973a7d68d756…` |
| `975732971316e135` | 2026-08-25T04:34:07Z | `apply_patch` | **truncated** | 412 | 414 | `e55ff00289e76bf0…` |
| `1eb27224742cf8d3` | 2026-08-25T05:17:03Z | `Bash` | **attestable** | 318 | 318 | `9776cc215bba366a…` |
| `250cdbcb0aca04be` | 2026-08-25T18:41:13Z | `Bash` | **attestable** | 394 | 394 | `912e789913e2ed5d…` |
| `04359f47c01e53e4` | 2026-08-25T23:16:42Z | `Bash` | **truncated** | 412 | 414 | `64706b2817b1470b…` |
| `e1bc557f2f4940c0` | 2026-08-27T00:12:49Z | `Bash` | **truncated** | 412 | 414 | `30d7988aa09fec39…` |
| `8435c380056cbab7` | 2026-08-27T00:25:28Z | `Bash` | **truncated** | 412 | 414 | `df485a116e12430c…` |
| `9a18bf661e88ec24` | 2026-08-27T00:47:59Z | `Bash` | **attestable** | 54 | 54 | `d297ba46daecac1b…` |
| `aef13d056044c0a5` | 2026-08-27T01:36:28Z | `Bash` | **attestable** | 287 | 287 | `dcd1367e9b959cf8…` |
| `a17c28f66e10222a` | 2026-08-27T07:09:57Z | `Bash` | **truncated** | 412 | 414 | `473911c9b3cf64f5…` |
| `22bb1c80ee42fec4` | 2026-08-27T13:03:38Z | `Bash` | **attestable** | 249 | 249 | `cf5124105cf351fb…` |

Full hashes in [`2026-08-27-codex-cut-rows.json`](2026-08-27-codex-cut-rows.json).

**Act text is deliberately absent.** Ids, lengths and hashes pin the claim to the byte
without republishing commands the record itself caps. The tail is reported as *which
marker*, never as the characters before it.

## Why 412 is a cap and not a coincidence

- **10 distinct acts** (10 distinct sha256) sit at
  **one** length: [412] chars / [414] bytes.
  A retried command piles *one* act at one length; a cap piles *many*. This is the same
  discriminator `_cap_suspects` uses, and it is why that guard counts distinct acts rather
  than rows — the row-counting draft fired on a kimi retry pair.
- 400 (limit) + 12 ('…[truncated]') = 412 chars; the ellipsis is 3 UTF-8 bytes so 414 bytes.
- The **longest uncut codex row is 394 chars** — under the limit, as it must be.
- Bash rows and apply_patch rows both land at exactly 412, because codex caps the ASSEMBLED summary. (claude-code caps the command BEFORE prefixing, which is why its Bash render is 228 and its apply_patch render is 235 -- do not port that expectation across seats.)

## The producer, on the second evidence axis

The chain walk and the source are independent. You can check this half without touching the
daemon at all, on your own filesystem:

- executing path: `/home/dp/.codex/hooks/pre_tool_use.py` (wired at `/home/dp/.codex/config.toml:40`)
- `md5 f4b8baf54c057bcaec6389a7f7e610e1` — **byte-identical** to `origin/main:plugins/codex/hooks/pre_tool_use.py (same md5)`
- `pre_tool_use.py:418 `def _attempted_summary(ev, limit=400)` -> :456 `return s[:limit] + ("…[truncated]" if len(s) > limit else "")``
- reaches the chain via pre_tool_use.py:686 and :911 pass it as witness_decision_unified(attempted_summary=...); _shared/hestia_gate_mechanism.py:456,:482 store it as `attempted`.
- mtime `2026-08-17T19:39`

This file has not changed since 2026-08-17, which is BEFORE every row above. The 2026-08-14 date previously published as a codex 'producer cutover' cannot be a behavioural change of this site.

## What this artifact does NOT establish

- It does not show *what* the omitted tails said. That is the point of the finding, not a
  gap in it.
- It says nothing about whether any of these 10 acts was unsafe. #678's claim is about
  **reviewability**, and codex's dissent on `13674a4dde3475ce` — that a peer cannot attest
  to an act it can only read a prefix of — is the same claim from the other side.
- The span's left edge is a hop budget, not a date. `--max-hops 40000` reached
  `2026-08-18` on this run and will drift as the chain grows. Rows *before*
  that edge are unmeasured, so **10 is a floor**.

## Upgrade: the same table, read off the EXECUTING closure

#678's cap table was read from the repo. A repo read dates a *branch*, not a running
process — and it is the running process that produced the rows above. Re-read on CBP,
2026-08-27, at the path each seat's launcher actually wires:

| seat | executing path | md5 | mtime | limit | marker | total |
|---|---|---|---|---|---|---|
| claude-code | `~/.claude/hooks/hestia/pre_tool_use.py` | `0e237d8a…` | 2026-08-25 11:08 | 220 | `" …"` (2) | **228** `Bash: ` / **235** `apply_patch: ` |
| codex | `~/.codex/hooks/pre_tool_use.py` | `f4b8baf5…` | 2026-08-17 19:39 | 400 | `"…[truncated]"` (12) | **412** (any tool) |
| kimi-code | `~/.kimi-code/hooks/pre_tool_use.py` | `619cb4c2…` | 2026-08-25 11:08 | 400 | `"…[truncated]"` (12) | **412** (any tool) |

Why the totals differ in *kind*, not just in size: **claude-code caps `s` and prepends
`f"{tool_name}: "` afterwards**, so its total is `len(prefix) + 220 + 2` and moves with the
tool. codex and kimi cap the *assembled* string with no prefix, so every tool lands on the
same number. This is why `228` is not a fleet constant and must never be matched on.

Two of the three executing files are not the repo file you would reach for:

- **codex** is byte-identical to `origin/main:plugins/codex/hooks/pre_tool_use.py`.
- **kimi-code is NOT.** Its executing file is the pre-#659 blob (`bb58c545`); #659 landed on
  main at 2026-08-27 00:05, two days after this file's mtime. The **entire** delta is 17
  changed lines removing the **dead** `HESTIA_SOCIETY_GATE` / `CLAUDE_PRE` knob and its
  docstring. Behavioural delta: **zero**; the cap site is byte-identical. That is staleness
  *measured and bounded*, which is a different claim from "kimi's gate is stale" — and the
  bounded version is the one that is true.

So the #678 table survives on the axis that produced the rows, and it survives for a reason
the repo read could not have established.
