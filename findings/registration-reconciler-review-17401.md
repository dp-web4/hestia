# Registration reconciler review — notice 17401

Verdict: changes requested before escalation/merge. Reviewed PR #1245 at
`2fe3a27da57658396344fa758f8574ff3f02696e` together with patch
`052b0e583ce5b3b0be419aecc082ef970a40be99c2b031b9c32dfeac148972c1`.
The supplied patch's SHA-256 matched. It applied cleanly to an isolated archive of
that commit. No live registrations were changed.

## P1: preflight certifies a TOML rewrite the installer cannot perform

`deploy/register-members.py:1120–1125`, `reconciled_commands()`, computes
`apply_structural()` and returns `ok` without running the TOML placement and proof
checks used by `register_member()`. A valid inline hook array is enough:

```toml
[[hooks.PreToolUse]]
matcher = "*"
hooks = [{type="command", command="python3 /example/hooks/pre_tool_use.py", timeout=10}]
```

With that command targeting the member's declared destination and a template
adding `HESTIA_HOME`, the actual `gate_preflight.run_probes()` returned:

```text
True [{'member': 'alpha', 'probe': 'read', 'status': 'ok'}]
```

Calling `register_member()` on the same fixture returned `refused`; the config
remained byte-identical. Its diagnostic was that the text's groups/entries do not
match the parse. This is already an explicitly supported refusal case in
`test_a_rewrite_the_text_cannot_place_is_refused_not_guessed`.

The preflight therefore proves availability under an environment that will not be
installed. Replacing hook code before the subsequent registration refusal can
leave the new gate running under the stale locator-less line, recreating the
outage this change is meant to fix.

Share the complete side-effect-free registration preparation between installer
and preflight: plan, place the text edit, ensure required config, validate and
prove it, then extract commands from the result. An unplaceable edit must produce
an unmeasured/refused preflight row. Add a regression joining the existing inline
array refusal fixture to the preflight path.

## P2: group ownership ignores foreign hooks without a command field

`deploy/register-members.py:631–636` counts group members from `regs`, but
`index_hooks()` skips entries without a string `command`. Consequently a foreign
prompt hook sharing a group with an owned command is invisible when the
reconciler decides whether it owns the entire group's matcher.

Reproduced directly through `plan_reconcile()` and `apply_structural()`:

```python
owned = {"type": "command",
         "command": "python3 /safe/hooks/pre_tool_use.py", "timeout": 10}
foreign = {"type": "prompt", "prompt": "Review this read request."}
hooks = {"PreToolUse": [{"matcher": "Read", "hooks": [owned, foreign]}]}
# Desired template: the owned hook above, under matcher "*".
```

The sole operation was `gmatch`; the resulting group still contained both hooks,
now under `matcher="*"`. The unrelated prompt therefore starts running for every
tool. This violates the stated guarantee that a foreign hook's matcher never
changes.

Count every surviving entry in the actual group when proving exclusive
ownership. If any entry is not an owned hook requiring the same matcher, move the
owned hook out, preserving the foreign entry and its original matcher. Extend
the mixed-group test with a prompt or agent hook lacking `command`.

## Validation and limits

- Combined commit plus patch: `python3 tools/register_members_test.py` reports
  **51/52 passed**. The remaining failure is
  `test_install_refuses_a_home_path_with_shell_special_characters`. The registrar
  refuses the unsafe locator with rc 7, but the installer subsequently takes its
  zero-installed-members exit and returns 0. The test's required nonzero exit is
  lost. This needs resolution before calling the combined change green.
- `env -u HESTIA_ROLE -u WANT_ROLE python3 deploy/from-main/gate_preflight_test.py`
  passes all **14 direct-run checks**. With an ambient launcher role, the new test
  first fails because its initial assertion assumes the default role. The
  explicit environment cleanup above isolates that test assumption.
- Separate shell execution checks confirmed role defaulting, launcher override,
  and literal preservation of a launcher value containing `$(...)`; that value
  was not executed. Existing unsafe declared-default rejection tests passed.
- Existing TOML preservation, both-reader agreement, restoration, duplicate
  removal, and ordinary mixed-command-group tests passed. Those results do not
  cover the two reproduced counterexamples above.

Review by Codex. Scope: the referenced commit and digest, not authorization to
deploy them. The open-PR metadata still named the reviewed commit when checked.
