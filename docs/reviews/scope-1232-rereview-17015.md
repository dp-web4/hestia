# Scope patch re-review — notice 17015

Verdict: **request changes**. This is a source review of the supplied patch against
`5ab5ee577ed86b8333ea2b7c5fdc16faa7bd5b1f`, not runtime certification.

Reviewed SHA-256 values, independently verified:

- Full patch: `c2dc70c6f839af10fb07cbd506b5a0c0adbe41480d53d3daf7d70b6947b14475`.
- Sources slice: `221558aa82da4b6347b68d9d6653b26430d9d005d06b1097aeb1312dabd52374`.

The complete-input digest, fail-closed candidate limits, collection-before-claim,
and society-check-before-spend are useful changes. They do not yet establish the
claimed end-to-end behavior.

1. **P1 — Supply the daemon half of the new approval protocol.**
   `spend_scope_all` in the mechanism patch sends `paths`, `act_digest`, and
   `spend: true`, without a singular `path` or `rule`. At the reviewed base,
   `tool_scope_claim` in `core/src/server/handler.rs:23143` immediately requires
   `path`, then requires `rule` to be `mrh.path` or `mrh.command`. It has no batch
   branch. Every otherwise successful scope lift therefore fails at the new
   spend call, including an `in_force` peek after a stale snapshot.
   Separately, that handler still computes its authorization digest from tool
   and truncated display text at line 23199; it does not read the client's new
   digest. Neither patch contains a Rust change. The modified Python stub
   implements a batch protocol that the supplied production base does not have.
   Include the daemon/store/schema changes and a real-handler test that binds
   complete input and atomically consumes all approvals. If these changes exist
   in another artifact, supply its exact revision for joint review. The broken
   batch call currently fails closed; this finding does not claim a working
   approval bypass through that call.

2. **P1 — Parse substitutions across the entire unquoted heredoc body.**
   In the patched `_strip_data_heredocs`, `_substitution_bodies(body)` is called
   separately for each physical line. Consider this shell input as data:

   ```sh
   cat <<EOF
   $(
   cat /etc/review-probe
   )
   EOF
   ```

   The first body line produces an empty substitution body, which is filtered
   out. The next line has no substitution opener, so the absolute path is
   discarded with the data. The earlier passes do not classify this outside
   absolute path: pass 1 only handles workspace spellings and pass 2 skips
   absolute tokens. Bash executes the multiline substitution. Accumulate the
   body, then parse its expansions with their line boundaries intact; add a
   regression for this case and a backslash-continued substitution.

3. **P1 — Quoting and delimiter exceptions still hide root reaches.**
   The patched `_outside_candidates` drops a quoted root word whenever the
   head is absent from `_ROOT_WALKERS`. Consequently `grep -r x "/"` is skipped,
   although quoting does not make this operand a pattern. `_DELIMITER_OPTS` is
   also applied without checking the command: `ls -s /` is skipped because
   `-s` appears in that set, though it does not consume a delimiter for `ls`.
   Finally `_tokenize` uses one `quoted` bit for the entire word. `echo "/"*`
   retains an unquoted, expanding star, but the bit marks it quoted and the
   `echo` exception drops it. Track quoting on the glob characters themselves,
   and apply option/pattern exceptions to the relevant command and argument
   position. Add all three cases alongside the existing root controls.

4. **P2 — Atomic scope spending still precedes possible denial, and timeout
   cannot establish that nothing was consumed.**
   The patched `_evaluate` spends before `_finalize`. The unchanged `_finalize`
   can convert an allow into `gate.evidence_uncommitted` for a consequential
   action. Once the daemon batch exists, a successful spend followed by failed
   evidence recording still consumes approvals for a denied action.
   The new `_spend_scope` also uses `_bounded` without forwarding an absolute
   deadline into `spend_scope_all`/`gate_self_call`. `_bounded` abandons its
   worker rather than cancelling it; `gate_self_call` can proceed from a delayed
   connect to the mutation after its caller has returned a denial. A lost
   response after a committed spend is another uncertain-outcome case.
   `_spend_scope` nevertheless appends “nothing was consumed” for every failure.
   Integrate spending with final evidence commitment, or use a recoverable
   reservation/commit protocol. Propagate deadlines before each RPC and retain
   an operation key plus lookup for an already-dispatched mutation. Report
   uncertainty honestly; add delayed-transport, lost-response, and failed-final-
   witness tests. The last two ordering facts are source analysis here, not new
   runtime reproductions.

The previously reported empty-`HOME` defect also remains in the base:
`_expand_home_words` uses `if not home`, so an explicitly empty variable falls
back to the account home. This patch does not modify that function. Do not mark
that separate review finding closed by this artifact.

Validation and governance boundary:

- Read both supplied patches and the matching production handler, transport,
  classifier, orchestrator, and test-stub code at the stated base.
- No patched suite was run. Applying the full patch in an isolated checkout was
  denied by the governance hook before execution; protected files were not
  changed, and no alternate application route was attempted.
- Read-only lookup showed that the denied attempt had opened escalation
  `550eeaa6f663682b`. It was subsequently closed with a recorded deny; the
  daemon returned `granted: false`, `permits_write: false`, `status: denied`.
  No approval was obtained or consumed for the attempted patch application.
- The represented shell probes above were not executed. Their classification
  paths are derived from the supplied source. This review does not claim
  runtime reproduction or fresh passing test counts.
