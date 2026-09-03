# The remedy every refusal names is refused as typed

**Seat:** claude-code (CBP) · **2026-09-01** · specimen escalation `4ea163f9db88ec75` ·
fix in `core/src/server/handler.rs` (`how_to_decide`, one function, both opening doors)

## What happened

A read-only `ls` of a scratch-worktree test file, batched into a compound Bash with `&&`/`;`,
carried a governance-marker basename in out-of-grammar text and was classified WRITE — the
already-ruled class ([[fb_marker_path_in_compound_shell_pages_operator]], third instance in
two wakes, and the interactive `claude -c` session did the same 20 minutes earlier on
`a6f3a4d21388989b`). The gate opened a petition and the hook printed, verbatim from the
daemon's `how_to_decide`:

```
To allow:  hestia gate approve 4ea163f9db88ec75 --reason '...'   (or: hestia gate deny 4ea163f9db88ec75)
```

I typed the deny leg as printed. The daemon answered:

```
identity ASSERTED as 'hestia-cli' … you may not rule this: Refused { reason: "'hestia-cli' is
not a recognised reasoning harness — an appeal needs an entity that can read it and rule …" }
```

Then the approve leg as printed (on the same, by then decided, row): the **same refusal**, and
it fires **before** the decided-state check — identity is the first gate. So neither command
the text hands out can succeed for anyone who types it as given.

The retire that worked was `hestia gate deny <id> --as claude-code --reason …`, i.e. the flag
the recipe never mentions, remembered from a memory file rather than read from the text.

## Why it is this way — and why nobody filed it

- The two `how_to_decide` strings were written in `5e15636` (#114, stage 2), **before
  `hestia gate` existed** — `gate_cli.rs`'s own header says "That subcommand had never been
  written". The recipe was aspirational text naming a command to be built.
- When the CLI was built it made a deliberate, documented choice: assert `hestia-cli` unless
  told `--as <seat>`, "so an unnamed caller is visibly a CLI, not silently a peer". Correct
  ruling. But `arbiter::is_recognised_reasoner` is `lineage(id).is_some()`, and `lineage`
  recognises only `claude*`/`codex*`/`kimi*`/`gemini*`. `hestia-cli` matches nothing, so the
  CLI's default identity is refused by every ruling path. The recipe was never revisited
  when the default was chosen — a cutover that did not rewrite the text it invalidated
  ([[fb_read_path_beats_recall_path]]).
- The two sites had also drifted from each other: `handler.rs:15929` put `--reason` on the
  deny leg, `:16644` on the approve leg. Two copies, no shared source.
- All three seat hooks print the daemon's string unchanged (`claude-code` `pre_tool_use.py`
  line ~2215; `codex`/`kimi` fall back to `hestia gate approve {id}` — the same dead form).
  So this is the gate's *read path*: the one line a seat sees at the moment it needs to act.
- Nobody filed it because the operator never types it. The operator rules through the
  dashboard (`operator_session`: 267/267 approvals in the 08-16..08-31 corpus). The seats
  that did rule from the CLI had `--as` in memory. The dead text was load-bearing for nobody
  who could report it — [[fb_absent_failloud_artifact_is_not_health]] in the other direction:
  a remedy nobody uses looks healthy because no failure is ever recorded against it.
- There IS a standing guard for this class — `tools/gate_remedy_surface_test.py`, "a sentence
  against a subcommand table", written 2026-07-31 when the same line advertised a `gate`
  subcommand that did not exist. It is green today (6 CLI advertisements resolve) and it is
  honest about its domain: *"It does not check ARGUMENTS or flags — `--reason` is unverified
  even where the subcommand resolves."* This finding is the next rung down: the subcommand
  resolves, and the invocation as printed is refused anyway, on the flag the guard does not
  read. A guard is as strong as its domain ([[ref_petition_frame_index]]); this one said so
  in its own docstring, which is why the pin for the flag lives beside the string in Rust
  (predicate test) rather than as a seventh property there.
- Searched before filing ([[fb_grep_for_the_ruling_before_filing_a_divergence]]): issues
  #685/#261 cover the *appeal* CLI verb, not the escalation recipe; no issue or PR mentions
  `how_to_decide` or the missing `--as`. Not a ruled design — a stale line.

## The fix

One function, `how_to_decide(id, asker)`, used by both opening doors. It names three things
the old text did not: that a ruling needs `--as <seat>`; that the asker can retire its own
petition (`hestia gate deny <id> --as <asker>` — the modal CLI use, `self_withdrawn`); and
that the approve leg must NOT name the asker (NOT-SAME). Pinned by a predicate test, not a
golden string: every `hestia gate` command in the recipe must carry `--as` and the id, the
deny leg must name the asker, the approve leg must not. A rewording that keeps the property
passes; one that drops it goes red.

Not changed: `DEFAULT_ASSERTED_ID = "hestia-cli"` (the ruling stands — an unnamed caller
should be visibly a CLI); the seat hooks' local fallback strings (marker files; the daemon
string is what they print when the daemon answers, which is the live path).

## What this does not claim

- That the fix is in force. It is a daemon change: committed → reviewed → merged → rebuilt →
  **restarted** before any seat sees the new line ([[ref_deployment_index]]).
- That the marker-mention class is fixed. It is not, and it is ruled design (any closure
  mention in out-of-grammar text is a WRITE). The read-path fix for *that* is the one-line
  BASH TRAP guard now at the top of this seat's MEMORY.md, because the topic-index memory
  that held the rule did not load this wake and the trap fired anyway.

## Also this wake (informational, no action)

- `22efdfbde889c11a` withdrawn (my own self-deny from the previous wake); `3d56a83125c9f2b9`
  operator-approved, reason `"h"` — a keystroke, the matcher finding again
  ([[ref_petition_frame_index]]).
- Seven watcher bounces: codex `why=timeout` at 07:00:54 then `why=out-of-credits` at 07:07:21
  for the same dead seat; kimi `out-of-credits` throughout. Both peers are out of credits; this
  mesh is single-seat. Every auto-invitation to them is published as a decline
  ([[ref_liveness_is_the_watcher_not_the_member]], PR #755 still open).
- Measured open petitions (per-wake probe file, `stat`ed before the fold): `asked:true`,
  `mine:[a6f3a4d21388989b, 54d9e9691134e3bf]` — both opened by the interactive session
  `888f190a` (pid 10349, `/tmp/wt-collapse`, `cbp/collapse-claude-shim`), not by a mesh wake.
  Left alone: a co-seat cannot tell whether that session is waiting on them (#732).
