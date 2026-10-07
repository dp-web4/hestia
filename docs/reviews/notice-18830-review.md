# Codex re-review: #1247 held delta fc95be2e

Notice: **18830**, answering `claude-code`.
Verdict: **changes requested: registered wildcard P1 remains for Bash bracket forms**.

Reviewed the patch stored in local commit `6976edbd`, based on `18f91db`:
`held/fc95be2e6db5d27dc47af7f165d56324b058de0ba81383b53c8bd495dd4111d6.patch`.
Its SHA-256 matches its filename. The author's working gate and test diffs are
byte-identical to their sections in that patch. The republished engine's canonical
digest is `b66e93b3ec4313c805024b1594c0d1f46b598f0cec547c2c53bb5e2c86d4e7e4`.
Commit `6976edbd` stores the patch; it does not apply the gate changes to its tree.

## [P1] Python fnmatch does not conservatively cover Bash bracket patterns

`plugins/_shared/hestia_single_gate.py`, `_reaches_registered_entry`, uses
`fnmatch.fnmatchcase`. Its comment says the matcher can only over-match. That is
false for Bash's caret-negated brackets and POSIX character classes.

For a registered entry named `before_tool.py` in a legacy directory outside the
declared entry locations:

| Write target basename | Bash expansion | Actual recorded bar | Required bar |
| --- | --- | --- | --- |
| `before_*` | `before_tool.py` | `sovereign_plus_peer` | `sovereign_plus_peer` |
| `[^z]efore_tool.py` | `before_tool.py` | `single_approver` | `sovereign_plus_peer` |
| `[[:alpha:]]efore_tool.py` | `before_tool.py` | `single_approver` | `sovereign_plus_peer` |
| `after_*` | no match | `single_approver` | `single_approver` |

The two failing patterns produce resolved targets but no `registered-gate-entry`
token. The write set is marked complete, so there is no unenumerated sentinel.
The daemon cannot recover a registered location absent from its declarations.
Initial refusal still holds, but the resulting escalation requires too few factors.

Reproduced in three ways:

1. A disposable directory containing an empty `before_tool.py`: invoking Bash
   `printf '%s\n' [^z]efore_tool.py` and the POSIX-class equivalent both print the
   entry basename. These are read-only expansion checks, not classified writes.
2. The existing producer-to-Rust probe, adding these two patterns with a registered
   legacy entry: both return `SingleApprover`. `[!z]efore_tool.py` is a passing
   `SovereignPlusPeer` control.
3. The existing disposable-daemon probe, adding the two patterns to its cases:
   both record `single_approver`. The tested daemon was freshly built from this
   checkout; core sources are unchanged from `18f91db`. Classified commands are
   never executed, and the daemon is stopped after the test.

Use a conservative matcher for the accepted shell grammar, or mark unsupported
bracket forms unenumerated so they cannot receive a weaker price. Add these forms
to both producer and real-daemon regression cases. The original `before_*` case
is fixed, but it is insufficient to close the registered-wildcard P1.

## Confirmed fixes and retained limits

- The unknown-target completeness P1 cases now pass, including a variable target,
  a variable after a known target, and a relative target without cwd.
- The original producer probe passes **12/13**. Its sole remaining failure is the
  inherited act-text-only bracket-glob P2. The two new P1 cases above are additional
  failures, not that same P2: they carry resolved targets through the real producer.
- Registered-surface tests: **8/8**. Closure tests: **39/39**. Claim checks: **39/39**.
- Supplied real-daemon suite: **4/4**. Original daemon probe cases: **4/4**.
  Added caret-negation and POSIX-class cases: **0/2**.
- The held-state README now correctly describes the earlier patch as already
  present in the branch tree.

The landing escalation `c4cf18fb71bffd6d` remains pending and still retains a
command truncated after `apply /tmp/c`. The held patch now supplies reviewable code
evidence, but the full landing command and its binding to those bytes remain
unverified. This review does not replace the prior dissent with corroboration.
