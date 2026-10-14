# held/: hestia#1313, an unenumerable reach opens no peer scope request, NOT applied

| file | sha256 |
|---|---|
| `e98ebef4316c1b4d3696d3680c203f74cac15a77ac1690d0ec7cd749e65288d2.patch` | `e98ebef4316c1b4d3696d3680c203f74cac15a77ac1690d0ec7cd749e65288d2` (base main `5e1ba8e4`) **current** |

9 files, +121/−84: the gate core, its hooks-gt copy and manifests (emitted by `tools/hooks_gt.emit_patch` from a
scratch copy), the decide contract test and the shell battery. `git apply --check` is clean on main
`5e1ba8e4`. Nothing here is applied.

## The ruling

dp, 2026-10-14 (asked in a CBP session, option (b) of three; recorded on #1312 and #1313): an act whose reach
the gate cannot enumerate is refused with rewrite guidance and **opens no peer scope request**. Rejected: (a) keep
the once-only request; (c) allow if every command is a read verb.

Measured on claude-code's own 50,091 recorded commands since 09-20 (grant `path:<ws>/**`): 9,178 such requests
(18%). Most lapsed or were refused by a peer as noise.

## The change: one new rule, no mechanism change

- The core refuses an unenumerable reach as **`mrh.command.unenumerated`**, not `mrh.command`. It is not in
  `mechanism.SCOPE_ESCALATING_RULES` (`mrh.path`, `mrh.command`), so `hestia_single_gate._scope_escalation` never
  sees it and the daemon is asked nothing: no request for the act, and none for a concrete path refused beside it,
  since the act cannot pass as written anyway. No change to the single gate, the mechanism or the daemon.
- `REMEDIES["mrh.command.unenumerated"]` names the two rewrites that work (spell every path out literally; or put
  the expansion in a script file run by its literal path), says the rewrite is the asked-for act and not a recast,
  and says no request was opened and why. The reason no longer promises "can only be approved ONCE".
- The target still names `UNENUMERATED_TARGET`, and the core's once-only lift via a trial scope stays. Nothing in
  the gate builds that trial scope any more; a contract row pins that.

**Trade-off, stated plainly:** an unenumerable act can no longer be approved as written at all. Honouring an
approval that already exists without opening a new one would need a lookup-only scope-claim verb in the daemon
(Rust); it has none today.

**Overflow is unchanged:** a command naming more than `SCOPE_JUDGE_BUDGET` paths stays `mrh.command`, with its
once-only request. The ruling covered unenumerable reach, not size.

## Evidence (scratch copy via the tests' own seams; the governed files are untouched until the apply)

- `tools/one_gate_decide_contract_test.py` with `HESTIA_CONTRACT_OVERLAY` → the patched core: **PASS** (22 +
  shim-parity 29x4). On main's core the rewritten rows fail, so they separate old from new behaviour.
- `tools/shell_scope_reach_battery_test.py` with `HESTIA_SCOPE_BATTERY_CORE`: **1434/0** on the patched core and
  **1434/0** on main's (the `evaluate-requests` rule assertion follows whichever core it loads).
- `plugins/_shared/test_gate_core.py`: all checks pass. `plugins/_shared/sprintD_test.py`: 82/0. Both run with the
  patched core injected under its module name. sprintD checks every rule has a registered remedy whose tools exist.

## Contract tests rewritten

`test_an_unenumerated_reach_is_a_once_only_request` → `..._is_refused_with_rewrite_guidance`:
- the date-format act is refused under the new rule, with no `hestia_scope_claim` call and no escalation id;
- the remedy names the rewrite, says it is not a recast, and says no request was opened;
- even a stub daemon that would approve is never asked;
- the mixed `D=/etc/hostname; cat $D $E` is refused unescalated.

The #1287/#1289 seat rows expect the new rule and zero scope claims. The real-daemon arm expects no escalation id
on the act or its re-issue.

— cbp-claude
