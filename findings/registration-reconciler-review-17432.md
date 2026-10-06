# Registration reconciler re-review — notice 17432

Verdict: no remaining blocking findings in the requested fixes. The two blockers
from review 17401 and its installer exit-status failure are resolved in PR #1245
at `df952b1c4d5296a9a536f25b66846b9036fcb868` **combined with** patch
`eace9341cc8176f3ddf7a2923b1243acd735da8115d43b7b90dc3cec9bce2346`.
This verdict is conditional on that exact patch accompanying the commit. The
branch alone still lacks the template and installer changes it requires.

The supplied patch's SHA-256 matched its name and notice. It applied cleanly in
an isolated worktree of the stated commit. The open PR still named that commit
when checked. No live registrations were changed.

## Disposition of the earlier findings

- **P1 resolved:** `prepare_member()` now performs the complete side-effect-free
  preparation shared by `register_member()` and `reconciled_commands()`, including
  TOML edit placement, verification, required settings and parse-back. The real
  preflight regression now reports the unplaceable inline-array fixture as
  `unmeasured` instead of certifying it; the config stays unchanged.
- **P2 resolved:** matcher reconciliation counts all entries in the actual group,
  excluding removed duplicates, rather than counting only indexed commands.
  JSON and nested TOML regressions confirm that an owned hook moves out while a
  foreign prompt hook retains its original group and matcher. The TOML test also
  checks preservation of the foreign entry's literal text.
- **Installer refusal resolved:** the supplied patch checks locator characters
  before planning or writes. The existing shell-special-character regression now
  passes, including its required nonzero exit.
- **Test isolation resolved:** the rendered-line preflight test saves, removes
  and restores the ambient launcher role around its default-role assertion.

## Validation on the combined bytes

- `python3 tools/register_members_test.py`: **53/53 passed**.
- `python3 deploy/from-main/gate_preflight_test.py`: **15 checks passed**.
- `python3 -m pytest -q deploy/from-main/gate_preflight_test.py`: **16 passed**.
- `python3 tools/hooks_gt.py check`: every published hook matches its digest and
  source.
- `git diff --check`: passed.

The registration suite also exercises both TOML readers, idempotence, restoration
after write failure, role rendering and isolated installer integration. These
results establish the tested configuration behavior; they do not establish a
live deployment or an atomic daemon-and-hooks switch.

Review by Codex. This is a code-review verdict for the stated commit plus digest,
not a governance ratification or deployment authorization.
