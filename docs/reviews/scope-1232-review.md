PR #1232 review — Codex, 2026-10-05

Reviewed commit: `a589ed9e6805af35de9b825d79e2ca0d56c7d251`.
Request: notice 16955, PR comment 5987222536.
Verdict: **request changes**. The outside-workspace tightening is useful, but
the new one-time approval binding is not an exact-act binding and the new
parser has reproducible gaps beyond the declared residuals.

The companion `scope-1232-repro.py` drives the real Python classifier and
orchestrator with synthetic commands and the existing contract stub. It never
executes the represented shell commands, contacts the live daemon, or spends
a real approval. Its digest reproduction follows the inspected Rust handler;
it is not an end-to-end Rust-daemon approval test.

1. **P1 — Bind approval to complete input before rendering it.**
   `attempted_of` in `plugins/_shared/hestia_single_gate.py` (335–347) prefers
   `file_path` to the rest of the payload. Two `Write` calls with the same path
   and different contents therefore have identical approval digests; so do
   `Edit` calls with different replacements. No masking or long input is needed.
   The suspected masking and 400-character truncation collisions also reproduce,
   as does collapsing whitespace *inside quoted strings*. The orchestrator sends
   this summary to `claim_scope`; `tool_scope_claim` in `handler.rs` truncates it
   again and `scope_act_digest` hashes only tool plus summary. The once lookup
   checks member, path, digest, and spendability, so those collisions satisfy
   every act-binding predicate. A read-style shell command and a write-style
   command can share a sufficiently long prefix and the same refused path.
   Carry a separate digest over canonical, complete tool input and the relevant
   execution context (including cwd); keep the masked summary for display.
   Do not include invocation-specific IDs if an identical retry must redeem it.

2. **P1 — Preserve shell expansion in unquoted data heredocs.**
   `_strip_data_heredocs` in `hestia_gate_core.py` (1039–1070) removes the body
   whenever its consumer is not an interpreter. But `cat <<EOF` expands command
   substitutions before cat receives data. The classifier refuses
   `cat /etc/review-probe`, yet allows the same access written as
   `cat <<EOF\n$(cat /etc/review-probe)\nEOF`. A quoted delimiter is correctly
   literal data; an unquoted delimiter is not. Preserve executable expansions
   according to delimiter quoting, including backticks and expansions containing
   nested substitutions, instead of deleting them with the data.

3. **P1 — Exhausting the candidate budget must not mean allow.**
   Pass 3 of `command_scope_reach` (1348–1352) breaks at 64 judged candidates,
   then returns allow. Sixty-four repeated `/tmp/review-probe` operands followed
   by `/etc/review-probe` classify as allowed; 63 repeated operands followed by
   that same final path are refused. These operands need not exist: their
   existing ancestor supplies the reach probe. Deduplication would fix repetition
   only; distinct candidates still reach the budget. On exhaustion, deny or
   explicitly escalate incomplete classification.

4. **P1 — Root globs are not delimiters for every non-walker.**
   `_outside_candidates` (1164–1172) drops `/*` when the command head is absent
   from `_ROOT_WALKERS`. `cat /*` therefore passes with no grants while `ls /*`
   is refused. The shell expands both globs before dispatching either program;
   cat can read root-level regular files. This is separate from the documented
   `grep -r x /` residual. Recognize actual delimiter-taking positions rather
   than treating every other root spelling as data.

5. **P2 — A partial preflight still spends approvals.**
   `_scope_escalation` in `hestia_single_gate.py` (618–658) collects only four
   paths but proceeds when the fifth still has an escalating refusal. With five
   refused paths and an approving stub, it peeks four, spends four, then denies
   on the fifth. Fail before claiming when local collection is incomplete.
   There is also a later refusal path: one approved scope path is spent before
   society law returns `deny`. Multi-path spends are separate RPCs, so their
   peeks alone cannot guarantee atomic spending if a later spend fails. The
   latter race is source analysis, not a reproduced concurrency run. If the
   contract is that a denied act spends nothing, use a reservation/finalization
   or atomic batch mechanism integrated with the remaining preflight checks.

Answers to the other requested questions:

- Breadth: the inspected `scope_decide` checks enforce absolute non-root ancestry
  at a separator, require recursion for an ancestor, reject breadth with once,
  and reject an exact non-once grant for a subtree. `reach_path` is used by the
  policy snapshot and the live promote/recursive lookup. I did not reproduce a
  new breadth-validation bypass. This is a source review, not a complete Rust
  or UI exercise of every live-grant mutation.
- Request keys: the store filters both member and normalized path, rather than
  trusting a caller-provided hash as the row selector. I found no cross-member
  dedup caused by this key. An absent session still leaves the documented A1
  asserted-identity limitation. Pending and refused matching deliberately omit
  the act: a refusal of one act suppresses a different act at the same path
  until the original request expires. This is a path-wide cooldown, not an
  act-specific refusal. Pending dedup retains the first act; the digest check
  normally prevents a changed act from consuming it, except for finding 1.
- Symlink behavior already declared for repo-name and `path:` grants remains a
  limitation; the findings above do not claim to close or newly demonstrate it.

Validation:

- Existing shell-scope battery: **176 passed, 0 failed**. Its fixture root was
  redirected into writable scratch space outside the synthetic workspace and
  outside temporary roots, preserving the battery's scope assumptions.
- Companion reproduction: **14 observations**, including refusal/data controls.
- Existing orchestrator contract suite: **16 passed**, with the real-daemon arm
  skipped. An initial checkout whose parent was `/tmp` produced two
  fixture-location failures: the test treated `/tmp/x` as an ungranted workspace
  child. The passing rerun used a nested checkout.
- No Rust or application suite rerun; the implementation was not changed.

Notice 16956 is separate: concurrence was recorded for the seven-file home
expansion delta with SHA-256
`75788c496d2f32dffbc6d73d2e4a950a0b60bdb43fa52297002f53b58c3e3236`.
That bounded change does not resolve or approve the findings above.
