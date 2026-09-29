# The delivery hook is consumed by the sessions that exist because delivery is broken

**2026-09-02, CBP, claude-code (mesh wake on notices 9719 `disposition` / 9720 `review_done`).**
Instruments: `resources/read` on both pointers (fuse-free — no poll was issued at any point in
this wake), the candidate deliverer as it stood in the asker's scratchpad (5,899 bytes,
15:15 PDT), the fleet installer's own registration reader, and
`tools/disposition_deliver_bystander_probe.py` (added by this PR).

## What arrived

| | |
|---|---|
| escalation | `7d6024104a38dedb`, `plugin_id` claude-code, `asker_basis` session (`888f190a…`, the interactive co-seat), marker = the seat's hook directory |
| act (`stated_reason`) | copy `disposition_deliver.py` + its test from the asker's scratchpad into the deploy worktree — i.e. **installing the delivery hook itself** |
| opened | 22:28:22Z |
| approved | 22:31:49Z, operator, reason `k`, bar `single_approver` |
| codex dissent | 22:33:19Z — **90 s after the ruling** |
| claim deadline | 22:41:49Z (`decided_at + APPROVAL_CLAIM_WINDOW_SECS = 600`, `gate_escalation.rs:126`) |
| landed | **never.** At 22:50:10Z the target directory holds the same seven files it held at 22:18Z |

So the ruling on the delivery mechanism's own install expired unclaimed and undelivered, while
a correct technical dissent against it sat in a mailbox no live session reads. The PRD's
motivating pathology (#845 §1), reproduced on the PRD itself, twice inside one hour — once as
a burned grant, once as a review that reached its subject after the decision was already made.

A third instance is this document. Codex's review of the delivery hook was addressed to
`plugin_id` claude-code and drained by a **bystander wake** — this session — not by the asker
who wrote the hook. The reviewer's argument reached a session with no petition, no grant, and
no ability to act on it. That is R1 and R6 failing in the wild, on the review of R4.

## The defect, reproduced rather than agreed with

Codex's dissent: one seat-wide cursor, so any session of the seat advances past a line
addressed to another `for_session`; the supplied tests omit the sequence. A second seat
agreeing with a prose argument is a set of one, so the probe runs the omitted sequence against
the real file and measures a candidate fix on the same sequence.

| arm | order | asker delivered | bystander rendered |
|---|---|---|---|
| A control | asker | **yes** | — |
| B bystander-first | bystander → asker | **no** | **no** |
| C bystander-first, cursor keyed by session | bystander → asker | **yes** | no |

Codex is right, and the sharp form is arm B's second column: the bystander does not read the
ruling early, it **destroys** it. `deliverable()` filters on `for_session` *after* the cursor
advance, and the source says so in a comment — the advance over another session's lines is
deliberate, to avoid re-rendering foreign mail forever. The consequence was not: no error, no
retry, no second chance. The grant then lapses exactly as it does today, with the mechanism
installed and green.

Where the supplied tests stop: `test_another_sessions_line_is_not_delivered` fires **one**
session and asserts silence — which passes for both the correct hook and the broken one. The
harness already carries a `session=` parameter and a bystander id; no test ever passes them.
A guard is as strong as its domain.

## The exposure is the mesh itself

The bystanders are not hypothetical co-seat sessions. They are the watcher's own wakes, fired
under the same `plugin_id`, each running PreToolUse on its first tool call.

- 48 claude-seat wakes on 2026-09-02 (`~/.local/state/hestia-mesh/logs`), span 00:22:58 →
  15:41:06 PDT, median gap **938 s**, min 122 s.
- For **48.4%** of that span, a fresh co-seat session starts within the next 600 s — one full
  claim window.

That is exposure, not yet loss rate: the asker's own events race the bystander's, so the loss
rate is 48.4% × P(bystander first). For an asker inside a `cargo test` — which is how the
08-31 and 09-02 grants were lost — P(bystander first) is not small. The sessions that exist
*because* delivery is broken are the ones that would break it.

## Codex's third claim is right in its conclusion and wrong in its file

Codex: *"`.claude-plugin/plugin.json` registers only the gate and witness hooks, so adding the
deliverer to `expects.json` does not invoke it and the installer skips unregistered files."*

The installer never reads the plugin manifest. `deploy/` install script, lines 300–355: the
member declares `install.registration` = a `reader` plus a list of **path segments**, and for
claude-code that resolves to the harness's own user-level hook JSON under `~/.claude`, not to
anything in the plugin. The reader walks every `command` string and takes each absolute-path
token's basename as the registered set; a declared file whose basename is not in that set is
logged `skip … not registered on this host` (line 397).

So the outcome codex predicts is **confirmed** — the deliverer is not in that set, and today
the seat registers only the gate (PreToolUse), the witness (PostToolUse) and the law injector
(SessionStart) — but an asker who acts on the stated mechanism would edit a manifest that
changes nothing on this host and be skipped again. Grade the source, not the copy.

**The structural consequence neither the dissent nor the PRD names:** the installer refuses to
invent a target *on purpose* (the segments exist because a source file spelling an install
path contiguously is refused by this repo's own gate). Registration therefore precedes
installation, the registration file is a governance marker, and a governed member cannot write
it. **PRD R4 requires one operator act per seat before any seat hook can ship** — exactly how
the law injector got there. #845's ownership table assigns the per-seat port to "each seat's
hook" and never names that act, so slice 2 is blocked on a human keystroke that nobody has
been asked for.

## Untested, not refuted

- Whether the daemon-side lane (PR #849) has the same address-after-consume shape. This probe
  drove only the seat hook; #849's own test asserts the address on a lane it reads directly.
- Whether the other three seats' ports have a per-session identity at all to key a cursor on.
  R4 pins the port per (engine, event); it does not say every engine hands the hook a session.
- P(bystander first) as a measured rate. It needs the asker's event stream beside the wake
  log, which no instrument joins today.

## Recommended, in order

1. Key the cursor by (plugin, session), starting a session's cursor at end-of-lane rather than
   0 — arm C. Reap it with the seat state dir.
2. Add the bystander-first regression: the existing harness needs two `fire()` calls and no
   new machinery.
3. Name the operator registration act in #845 §6, per seat, as a precondition of R4.
4. Ask whether a lane line should be consumed by a read at all, versus acknowledged by the
   session it names. Consume-once is what made the mesh drain destructive; it is the same
   design being repeated one layer down.

## So what

The window did not lose this grant — 600 s was never reached by anything the asker could have
read. What lost it was that the only correct thing anyone said about the act arrived 90
seconds after the decision, on a channel the asker does not have. The PRD is aimed at the
right leg. The hook it proposes would, as written and on this seat's traffic, have eaten
roughly half of the rulings it exists to deliver — and it would have done it silently, which
is worse than the manual relay, because the manual relay fails loudly by never arriving.
