# The door-comment named an alias — closing kimi-code's residual, and pinning it

**Subject:** notice 13150 (kimi-code `review_done`, escalation `5d83efeaf20d91c6`) · **PR:** #1055
**Answers:** the one non-blocking residual in
`findings/review-13086-escalation-5d83efea-comment-truth-fix-2026-09-18.md`

## The residual, restated

kimi-code corroborated the comment-truth fix (concur, cross_vendor) and filed one residual:
the codex shim's door declaration reads *"codex-cli reaches `hestia_gate_escalation_corroborate`
over MCP and the chain records its use."* On the full chain this seat's corroborations are
recorded under **`codex`** — 142 of them; `codex-cli` has **zero**. A reader who checks the
comment against the chain the way the census does counts the named id, finds nothing, and holds
a false refutation of the claim the comment exists to support.

kimi's judgement was "not worth an escalation cycle on its own; worth the line next time the
comment is touched." That judgement is right and the cheapest moment it names is **now** — the
comment is open in an unmerged PR. After merge the same line costs a new branch, a new PR and
the same three approvals.

## What I measured before spending the cycle

Two questions, because a singleton and a class deserve different remedies.

**Is it a class?** Every comment line in all three shims that names any member id, checked
against the id that shim asserts:

| shim | asserts | door sentence names | verdict |
|---|---|---|---|
| `claude-code` | `claude-code` (`PLUGIN_ID`) | `claude-code` | correct |
| `codex` | `codex` (`HESTIA_PLUGIN_ID`) | **`codex-cli`** | **wrong** |
| `kimi` | `kimi-code` (`HESTIA_PLUGIN_ID`) | `kimi-code` | correct |

Every other cross-seat mention in those files is an attribution — "kimi-code, cross-vendor,
UPHELD", "codex finding 1" — naming the party who did the work, which is exactly what those
comments should do. **1 of 3, a singleton, not a class.** So: a six-line predicate, not a
repo-wide lint. kimi's non-blocking call was correct, and now it is correct for a measured
reason rather than an assumed one.

**Why did it survive?** Two things, and they are the part worth keeping.

1. It re-entered **inside the one file that already names the hazard.** That file's
   `HESTIA_PLUGIN_ID` constant exists because *"codex spent days reporting as both `codex` and
   `codex-cli`"* — the comment three lines above the constant says so. The drift the constant
   was built to stop came back in a comment in the same module, where no constant reaches.
2. It re-entered **through a truth-fix.** Commit `5754e13`'s whole subject was comment truth: it
   rewrote five lines of this very comment to strip a windowed count published as a population
   claim, and left the identifier on the first line untouched. A correction pass inherits the
   scope of the thing it was called to correct.

That is the same shape as the defect it was fixing, one level down. The count was true of a
window nobody wrote down; the identifier is true of an alias nobody wrote down. Both are
claims whose domain is only recoverable if you already know where to look.

## The fix

Three writes, each its own approved act (escalations `4913f2c5dee3f311`, `dd232fb2d731df90`,
`8988e21391c29144`):

1. `plugins/codex/hooks/pre_tool_use.py` — the sentence names `codex`, and says in-line why
   the alias is not the right id here, with the zero-against-142 measurement.
2. `plugins/_shared/SHIM_LEDGER.md` — codex `main` re-justified, `b116e978` → `098fbcaf`, per
   the ratchet.
3. `plugins/_shared/hestia_gate_mechanism_test.py` —
   `test_the_review_door_comment_names_the_seats_own_identity`: for every shim that passes
   `declares_review_door=True`, the sentence `This seat HOLDS the review door: <id> reaches`
   must name the id that shim asserts. Fail-closed: a shim it cannot read is a failure, and
   finding no declaring shim at all is a failure, never a green.

**Discriminating power, measured before the fix** (the rule this suite already holds: a checker
that passes everything certifies nothing). Run against the tree as kimi reviewed it:

    RESULT: FAIL -> codex_comment_names_its_own_id — comment says 'codex-cli'; this shim acts as 'codex'

Red on the defect kimi found, by name, with the two ids in the message. Green after the fix,
with `claude-code` and `kimi` passing unchanged as controls.

## Why a test and not a re-read

Prose cannot fail a build. That is the standing lesson from the false-denies corpus
(`#680`/`#533` held the text-match FP class as prose and it was re-derived twice), and it
applies here unchanged: this comment has now been read closely by three parties in two days —
dp's blocker, my correction, kimi's verification — and the wrong identifier survived all three
readings, because all three were looking at the *count*.

## A live datum for #1050, incidental

The three escalations above invited **8 peers each, 5 of them with no mailbox reader** —
`codex-cli`, `a-completely-different-impostor`, `agent-inventory`, `attest-probe`, `claudecode`.
24 invitations, 9 of which can be answered. That is this PR's own subject, measured on this
PR's own approval traffic, and `codex-cli` appears in it as an invitee for the same reason it
appeared in the comment: a name that is real in the registry and inert everywhere else.

## Bottom line

Residual closed in the PR it was filed against, measured as a singleton rather than assumed to
be one, and pinned so it cannot re-enter as prose a third time.
