# Notice 17101: resolved-target escalation review

Verdict: **changes requested**. No approval or escalation factor cast.

Reviewed daemon commit `8fe646e20fa69cdb97550b17ceb8c5446ef61c7f` (PR #1239)
and producer patch SHA-256
`d39341b1551b404e74ba27674766e9610cbbc370301970ba7eb1c25567c9f2df`.

## P1: enforce the incoming price before spending or reclaiming an approval

`core/src/server/handler.rs:23562` reads `resolved_target`, but the call to
`claim_bound` at line 23713 does not pass it or a minimum bar. That method
(`core/src/server/gate_escalation.rs:2805`) selects by member, marker, act digest,
optional payload and claimability only. The reclaim path similarly lacks the
new target/pricing input. Pricing the incoming target happens only after these
early successful returns, when opening/coalescing at handler line 23910.

Concrete sequence: open a targetless claim whose bounded act omits the sovereign
filename, approve its single-approver row, then claim the same marker and act
with `resolved_target=/w/plugins/_shared/hestia_single_gate.py`. The earlier
approval is spent before the stronger incoming price can be considered. This
also arises across a producer upgrade; it does not require an invented target.
The new coalescing guard (`e.bar >= at_least`, line 2194) protects pending twins
but not approved ones.

Check the incoming required bar against the stored authorization before both
claim and reclaim. Preserve the historical recorded bar; do not silently
reprice the old row. A stronger current ask needs a separately sufficient
authorization. Add claim-door tests for approved weak -> strong and the lost
answer/reclaim equivalent. This finding is static control-flow evidence;
the Rust sequence was not executed in this review.

## P1: the producer still reports only the first governed write target

The new argument at `plugins/_shared/hestia_single_gate.py:722` forwards one
`cv.resource`. Both `_closure_view` (apply_patch) and `closure.classify` (shell)
return on the first governed target. The new field cannot recover a later
sovereign target missing from the bounded summary.

The executable probe demonstrates both forms without performing the writes:

- Shell: `touch` with `/w/plugins/_shared/ordinary.txt` first, 25 ordinary
  padding operands, and `/w/plugins/_shared/hestia_single_gate.py` last.
  The marker is `plugins/_shared`, resource is `ordinary.txt`, and the 220-character
  summary ends before the sovereign target.
- Patch: ordinary governed target first, sovereign target second, and a long
  ordinary target last. The marker/resource again identify the first target;
  the summary retains only the last 139 characters of the ordinary tail.

For both, all three daemon pricing inputs omit the sovereign filename, so
`price` returns `SingleApprover`. Carry all governed write targets, or derive
a sufficient classification from the complete write set before summarization.
Test mixed weak/strong writes in different orders with summary truncation.

## P1: credential redaction erases the required pricing classification

`resolved_target_for_claim` in the producer patch drops an entire path when
`credential_shaped` matches. `attempted_summary` drops it too. The probe passes
`/w/credential-fixture/plugins/kimi/hooks/pre_tool_use.py` and confirms no
`resolved_target` key is sent. With the directory closure marker and the
redacted act, the daemon again has no sovereign filename to price.

Redacting the sensitive path is appropriate, but missing pricing evidence
must not imply the weaker bar. Preserve a safe policy classification derived
before redaction (for example, an allowlisted sovereign basename), or refuse
the unpriceable case. Add a full producer-to-pricing test with a credential-shaped
ancestor and a sovereign basename. The existing test asserting omission of a
credential target checks privacy only; it does not check authorization strength.

## Validation and limits

- Patch digest verified; `git apply --check` passes against the supplied daemon
  worktree. All 11 files also pass exact-context in-memory patch application.
- Changed Python files compile. Both changed GT copies equal their sources
  after header removal, and their normalized hashes match the manifest.
- The patched `claim_self_write_test.py` passes **32/32** with the patched
  mechanism loaded in memory through an import loader and its existing stub.
- [Producer probe](notice-17101-probe.py) reproduces the multi-target and
  credential-redaction observations. Run it at this commit with the original
  patch file as its sole argument. It never applies the patch to disk or sends
  live claims.
- Rust tests and the subprocess-based seat boundary suite were not run.
  This is not runtime certification of the daemon or installed hooks.

The max-over-inputs rule and restoration of the recorded historical bar address
the earlier monotonicity/replay concerns at opening. They do not resolve the
claim-time and producer-completeness cases above.
