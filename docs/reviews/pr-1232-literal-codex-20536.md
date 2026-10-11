# PR #1232 literal-assignment review — HOLD

Reviewed head `5ade60069cc20b46ffbd6bf8da555004391e5e9c`, held patch
`f4644ef4f71a48cda62a546d5552f5e34063c43109e73aa71e3934d7ada699a0`,
answering notice **20536**. The patch digest verifies and `git apply --check`
passes. It remains held; this review did not apply it.

**Request changes.** Three defects in the literal rule produce five new
false-allow forms. The previously reported interpreter/quoting/input holes
also remain. All reproduce through the helper, core, and four seat adapters.

## P1 — a later assignment reaches an earlier substitution

```sh
echo "$(cat $S/hostname)"; S=/tmp/review-probe
```

This ALLOWs. If the invoking shell has an unexported `S=/etc`, the substitution
reads `/etc/hostname` before the assignment. The gate's environment cannot
disqualify an unexported shell variable.

In `hestia_gate_core._outside_candidates`, `_shell_words` appends substitution
bodies after the outer tokens. `found.known` therefore already contains the
later literal when the earlier body's `$S` is inspected. `main_len` prevents
bindings inside bodies but does not preserve when those bodies use a binding.
The ordinary `cat $S/x; S=/tmp/review-probe` control correctly refuses.

Required: resolve a body's variables only against bindings proven to precede
that body at runtime, or leave them unenumerated. The current flattened order
is not evidence of shell execution order.

## P1 — a literal is not necessarily one pathname when expanded

```sh
S="/tmp/review-probe /etc"; cat $S/hostname
```

This ALLOWs. Bash passes two arguments to `cat`: `/tmp/review-probe` and
`/etc/hostname`. `_is_bindable_literal` admits whitespace; `_word_value`
substitutes the whole string; `emit` judges one path beginning with `/tmp/`.
The second argument never reaches scope judgment.

The quoted control `cat "$S/hostname"` really does have one temporary path
and correctly ALLOWs. Rejecting potentially splitting literal values from
the rule is a conservative repair; retaining them needs use-site quote and
field-splitting evidence. Do not blindly split quoted values.

## P1 — attached binding options and arithmetic writes retain stale literals

Each command below ALLOWs:

```sh
S=/tmp/review-probe; printf -vS %s /etc; cat $S/hostname
S=/tmp/review-probe; read -aS <<< /etc; cat $S/hostname
S=/tmp; : $((S=0)); cat /$S/etc/hostname
```

The first two pass `/etc/hostname` to `cat`; the third passes
`/0/etc/hostname`, an outside path whether or not that file exists.

`_literal_names` looks for the exact `-v` word, so `-vS` escapes its `printf`
exclusion. For `read -aS`, its word-level identifier collection bans `aS`,
not the array name `S`. Arithmetic assignments embedded inside an expansion
are not counted as bindings; `_word_value` treats arithmetic as a numeric
placeholder without invalidating `S`. The parser retains the earlier `/tmp`
literal through all three writes.

Spaced `printf -v S` and `read -a S`, ordinary array assignment, array-element
assignment, and the nameref-target control all correctly refuse. Required:
recognize the binding operand forms or disqualify uncertain binders wholesale;
invalidate names written by arithmetic, or make the containing act
unenumerated. Numeric expansion output does not prove absence of side effects.

## P1 — previous review blockers persist; interpreter exclusion is incomplete

The [previous regression runner](scope-1232-shell-regressions.py) still reports
**54 failures / 96 checks**: the same nine forms fail at all six layers/seats.
These are combined shell `-c` options, including wrappers; `builtin eval`;
ANSI-C quoting; and shell code delivered by here-string, pipe, or descriptor.

The new runner also demonstrates the combination:

```sh
S=/tmp/review-probe; sh -ec 'cat /etc/hostname'; cat $S/x
```

It ALLOWs. Separately, both `bash -lc true` and
`bash --noprofile -c true` between assignment and use fail to disqualify `S`.
Those two benign cases demonstrate violations of the documented rule, not
additional outside reads by themselves. `_literal_names` requires an exact
`-c`/`--command` token immediately after the interpreter; combined options and
intervening options bypass that test. Plain `sh -c true` correctly disqualifies.

## Validation and reproducibility

- Candidate battery: **821 passed, 0 failed**. The candidate core was
  reconstructed with old-hunk context and SHA verification. The battery was
  extracted into scratch; only its fixture root was moved from a read-only
  cache to a writable non-temporary directory. Its assertions were unchanged.
- [Literal runner](scope-1232-literal-regressions.py): **156 checks, 48
  failures**. Eight failing forms × helper/core/four adapters. Six forms can
  hide an outside reach; two test the interpreter exclusion alone. All 18
  positive and refusal controls pass across all six paths.
- [Captured results](scope-1232-literal-results.json) include both runners and
  all full-gate evidence flags. Each full-gate result is witnessed by the
  disposable policy stub. Transport failure cannot count as a scope fix.
- The first five literal cases were separately executed in Bash with `cat`
  replaced by a function that **only prints its arguments**, and an initial
  unexported `S=/etc`. These confirm the argv above without opening any target
  file. The scaffold and output are recorded in the result artifact; the
  scaffold is not part of the classifier inputs.

Run from a nested checkout of the reviewed head:

```sh
python3 -B docs/reviews/scope-1232-literal-regressions.py --repo "$PWD" \
  --held f4644ef4f71a48cda62a546d5552f5e34063c43109e73aa71e3934d7ada699a0 \
  --full-gate
```

The runner intentionally exits 1 while these invariants fail. Replace its
filename with `scope-1232-shell-regressions.py` to rerun the prior cases.

This is classifier and disposable-stub evidence, not a live-daemon approval
consumption test. Rust and the corpus cost estimates were not rerun. The
shared checkout's branch and deployment were not changed.
