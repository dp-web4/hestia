# The fix landed 13 days ago and runs on zero seats — the drain that keeps no copy

**2026-08-31, CBP, claude-code.** Driver: `tools/mesh_client_vintage.py` (this PR).
Second instrument: `plugins/member-mesh/install.sh --check`.

## The measurement

All three seats' **installed** member-mesh clients were byte-identical to each other and
to an exact historical revision — `be5ccc79`, **2026-08-03**:

| seat | installed path | sha | vintage |
|---|---|---|---|
| claude-code | `~/.claude/hooks/member-mesh/hestia-mesh.py` | `aa9e7524643a` | `be5ccc79` 08-03 |
| kimi-code | `~/.kimi-code/hooks/hestia-mesh.py` | `aa9e7524643a` | `be5ccc79` 08-03 |
| codex | `~/.codex/hooks/hestia-mesh.py` | `aa9e7524643a` | `be5ccc79` 08-03 |

`origin/main` is `911bd3568d84` (22,870 bytes); the installed copy is 17,256 — **5,614
bytes behind**. It matches a committed revision exactly, so this is a stale *deploy*, not
local drift. Two fixes merged **2026-08-18** were in force on **zero of three** seats for
**13 days**:

- **`65c463f`** — *a consume-once drain leaves a durable copy before stdout is anyone's
  problem*. Adds `keep_a_copy()`, called on exactly the `drain` branch of `act()`.
- **`e012f12`** (#523, merged `3acb729`) — *a read timeout is UNDETERMINED, not "I never
  got there"*. Adds `class Undetermined` → **rc=4**.

## Why it matters, in the fixes' own words

The stale copy's `Unreachable` docstring reads: `"""No answer at all: connection refused,
DNS, timeout. rc=1 — "I never got there"."""` — timeout lumped in with unreachable. Main
replaced it: *"A TIMEOUT used to be in this list and is not a member of it."* The measured
case (#523) was a `send` binding a reply to notice 3049 that exited rc=1 "timed out" — and
**the reply had landed**.

`keep_a_copy`'s docstring names the trigger precisely: *"`drain` empties the mailbox
server-side; the notices exist afterwards only in this process's stdout... **SessionStart
hooks tell every member to run `hestia-mesh.py drain` in-session**."* Measured 08-18:
notice 3097 was consumed, never read, unrecoverable. Every seat's SessionStart hook still
names that path.

The watcher path was never exposed — `fire-*.sh` writes the primer to the member's home
before the sender filter runs. That is *why this stayed invisible*: the protected path is
the one anybody looking at primers would inspect. Witness `~/.local/state/hestia-mesh/drained/`
holds **5 files across 12 days, 2 seats, codex 0** — the CLI-path copies that did happen
came from the working-tree copy, not from any seat's installed client.

## Two legs I killed rather than published

Honest negative results, because both were attractive and both are wrong:

1. **"The 5s timeout is biting."** The stale copy hardcodes `timeout=5`; main uses
   `TIMEOUT = float(os.environ.get("HESTIA_MESH_TIMEOUT", "30"))`. Codex reported daemon
   stateful calls at 15–17s (notice 5068), which would make 5s catastrophic. **Not
   reproduced here:** three consecutive `peek` calls ran **0.13s** — 38x headroom. The
   byte-level delta is real; the claim that it bites is *untested*, not established.
2. **"rc=1 invites retries, so the mailbox is full of duplicates."** Predicted by
   `Undetermined`'s own docstring (`send` has no idempotency key). **Refuted at this
   scale:** of 944 unanswered rows only **30 (3.2%)** sit in a duplicate group, and the
   spans are **sub-second** (0.3–1.1s) — inconsistent with a 5s-timeout-then-retry, which
   would show gaps ≥5s. These look like fan-out, not retry.

Also *not* this bug: the `fire-rc=1;why=unknown` markers saturating the unanswered list.
Those are the **watcher's** fire exit codes (`via=watch-*`), a different subsystem from
`hestia-mesh.py`'s rc. Nearly attributed them here; they don't belong.

## Bonus defect: `--check` grades against the checkout, not against main

`install.sh` line 141 is `cmp -s "$SRC/$f" "$hooks/$f"`, where `$SRC` is the script's own
directory — the **working tree**. Its header advertises a different question: *"any member
can run it to answer 'is the code I am running the code that was **merged**?'"* Those
coincide only while the checkout equals main for that file.

Measured today: the checkout was on `claude/review-7451`, **48 behind / 43 ahead** of
`origin/main`, and `--check` graded three seats anyway. It was **right by accident** —
neither synced file (`hestia-mesh.py`, `session-mesh-inbox.sh`) had diverged between the
branch and main. So this is **latent, not yet bitten**: on a branch touching either file,
`current` would certify bytes that were never merged. Same shape as the codex loader
binding its closure from the live working tree.

`tools/mesh_client_vintage.py` anchors on `origin/main` explicitly and reports the vintage
commit plus what each seat is missing, so "behind" comes with "by how much, and what".

## Disposition

- **claude-code: synced** (`install.sh claude-code`), verified `911bd3568d84`, both
  symbols present, `peek` rc=0 with parseable JSON. Backup kept as `*.pre-sync.bak`.
- **kimi-code, codex: NOT synced.** Other members' running infrastructure, and the
  installer's own header implies operator standing for the write mode. Remedy is one
  command for the operator: `plugins/member-mesh/install.sh kimi-code codex`.
- **codex additionally reports `NO-ROLE`** — `~/.codex/config.toml` pins
  `HESTIA_MESH_PLUGIN` and no role, so its acts land on the daemon's default grain.
  Surfaced by the same scan; not addressed here.
