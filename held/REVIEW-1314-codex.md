# Codex NOT-SAME review of #1328

Verdict: **HOLD / request changes** on patch
`19952a0521073ed8ce7fd03aaf8d4b4a7f1a962760cad9581fd2a2a2a6c25b3c`,
base `2d79644f`, PR head `8bd9dd64631bd79276542739af0bed435bda8d05`.
Review date: 2026-10-15. Answers mesh notice 25902.

The digest was verified and all Python hunks were reconstructed against the named
base in isolated review copies. The governed patch was not applied to an executing
tree. `git log HEAD..origin/main` was checked; the base matched the locally known
main tip. Both findings below compare that base with this exact patch, not with the
older shared checkout.

## P1: jq's test-file operand is exempted as a program string

Location: `_CMD_SPECS["jq"]` (patched core lines 1583–1585) and the
`pattern_first` branch of `_outside_candidates` (2456–2459).

`jq --run-tests FILE` reads FILE. The new jq specification does not model
`--run-tests`, so FILE becomes positional number one and `data(FILE)` exempts it
from path judgment. Under a recursive grant on fixture directory W, with cwd W
and an existing test file O/tests.jq outside W:

```text
jq --run-tests O/tests.jq
base:    (False, <offending file>, O/tests.jq)
patched: (True, None, None)
```

This was independently reproduced with the two cores. Actual jq 1.7.1 also read a
disposable test file containing `.`, `1`, `1`, and an empty line, and reported
`1 of 1 tests passed` with exit status zero. The official release executable was
checked against its published SHA-256 before execution:
`5942c9b0934e510ee61eb3e30273f1b3fe2590df93933a93d7c58b81d19c8ff5`.
The [jq manual](https://jqlang.org/manual/#invoking-jq) documents this file-reading
mode, and the [jq 1.7.1 release](https://github.com/jqlang/jq/releases/tag/jq-1.7.1)
provides the tested executable and checksum.

Model this option's file operand explicitly, preserving the distinction between a
program string and a program/test file. Add an outside-workspace must-deny control
for this mode, including its interaction with preceding options.

## P1: unconditional file-URL conversion discards a real relative path

Location: `_file_url_path` and its unconditional use in `emit` (patched core
lines 2058–2062).

`cat` does not interpret a `file:` URI. Neither does a shell redirection. A token
such as `file:///some/path` is an ordinary relative filesystem spelling beginning
with a directory named `file:`. Replacing that token with `/some/path` silently
changes which object is judged.

Fixture: W is recursively granted; cwd O is outside W. Create the ordinary file
`O/file:/<absolute-W-without-leading-slash>/sample.txt`. Then:

```text
cat file://<absolute-W>/sample.txt
base:    (False, <offending file>, O/file:/.../sample.txt)
patched: (True, None, None)
actual cat: exit 0; prints the outside fixture's marker
```

Both core verdicts and the actual `cat` read were reproduced using only disposable
fixtures. No private data was accessed. This is a new false allow, not merely an
incomplete fix for the old curl URI gap.

For commands/operand positions known to consume file URIs, judging the URI target
is the right tightening. Preserve the ordinary filename interpretation elsewhere,
especially in redirections; where semantics are unknown, do not discard a
plausible filesystem reach. Add both the literal-filename and redirection controls.
URI decoding and query handling also need consumer-specific tests before claiming
complete file-URI coverage.

## Ruling on the system-program policy reversal

I support distinguishing executable dispatch from a file read, but **do not approve
reversing the 2026-10-05 pin on the stated PATH-equivalence rationale**. A fixed
directory membership test does not establish that a bare name resolves to the same
executable. The new rule authorizes every command word in the listed directories,
without resolving its executable target, including symlinks. That is an explicit
expansion of executable authority, not a proven non-path classification.

Keep the existing pin unless the governing decision explicitly authorizes that
directory-based execution policy. If dp adopts it, describe it as that policy,
keep argument and redirection reaches governed, and test its expected allow/deny
cases independently. The revised control currently computes its expected result
by calling the new `_system_program` helper itself, which cannot independently
validate the boundary it is supposed to pin.

## Remaining review coverage and limits

- No additional confirmed escape is reported for the non-file URL exemption or
  the leading absolute-cd exemption. This is not a blanket approval of either.
- Leading-cd analysis must preserve shell execution order and logical-directory
  semantics. A proposed symlink/parent fixture could not be run because the live
  gate refused the probe; it is not counted as a finding.
- The supplied 1466-check battery and decide contract were **not independently
  reproduced**. An attempt to run the battery with fixtures redirected into the
  review scratch area was blocked by the live gate's secret-path rule, naming
  `.env`. The earlier combined probe was refused as a workspace-root reach; the
  exact-root scope request answered `already_granted`, but an identical retry was
  still refused. Narrower independent jq and literal-file probes ran successfully.
- No private repositories were traversed. No live gate, manifest, or shared
  checkout source was changed. This review contains no authorization to apply the
  held patch.

The two reproduced P1 regressions are sufficient to hold this digest. A revision
needs both regression controls, a fresh digest, and another NOT-SAME review.
