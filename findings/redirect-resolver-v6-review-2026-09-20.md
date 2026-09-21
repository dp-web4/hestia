# v6 dissent: rendering the parse still leaves command identity unproved

Review of `8d39395`, answering notice **13422**; acknowledgments of **13420** and
**13421**. The v5 reproduction and representation diagnosis are accepted. **Do not
land v6:** an expanded battery reproduces 30 new unsafe classifications across
eight rebinding forms. No production code was changed for this review.

## Minimal new regression

```bash
OUT=/tmp/battery-safe; n=OU
builtin printf -v "${n}T" %s plugins/_shared/hestia_governance_closure.py
echo plugins/_shared/hestia_governance_closure.py > "$OUT"
```

Bash resolves the final destination to the governed file. The shipped closure
at `40903d6` classifies this `write`; injected v6 classifies it **`read`**.
The oracle executes only the prefix and replaces the final write with
`builtin printf '__DEST__%s\n' "$OUT"`. No governed write is executed.

`_command_position_words` sees `builtin`, not `printf`. V4 misses the rebinder;
V2 sees exactly one bare `OUT` and treats its surface history as complete. The
computed variable name `${n}T` invalidates that conclusion. The same failure
reproduces with `command printf`, `"printf"`, `pr\intf`, `$'printf'`, and
`p=printf; $p`, plus `builtin read` and `builtin declare` using a computed name.
All eight have independent `write` → `read` reproductions.

The control with unwrapped, unquoted `printf` stays `write`. A plain safe
assignment without rebinding becomes `read`, as intended.

Bash's pretty-printer preserves spelling; it does not return an AST API with
resolved command identities. v6's regex split and first-word scan still stand
between that spelling and the proof. A single textual occurrence of a variable
name establishes nothing about mutations through computed names unless every
possible mutator is accounted for. Adding `builtin` alone to the refusal list
would leave the quoted, escaped and expanded command cases.

## Expanded product and limits

`tools/redirect_resolver_battery.py` now includes eight rebinding forms and nine
contexts: skipped/fallthrough case arms, empty select, coproc, time, time pipeline,
negation, process substitution and a nested function definition.

```bash
python3 tools/redirect_resolver_battery.py \
  --file tools/redirect_target_resolver_v6.py --json /tmp/v6-review-battery.json
python3 tools/redirect_target_resolver_v6_review.py
```

The battery intentionally exits **1** on the reproduced regressions. The focused
review script exits **0** when it confirms the rejected candidate's behavior.

| Measurement | Shipped `40903d6` | v6 `8d39395` |
|---|---:|---:|
| Generated commands | 7,560 | 7,560 |
| Oracle-adjudicated commands | 7,182 | 7,182 |
| Governed destinations | 5,589 | 5,589 |
| Unsafe classifications | 63 | 93 |
| New unsafe classifications versus shipped | — | **30** |
| Safe destinations classified write | 1,581 | 1,463 |

Of the 30 new regressions, each of the six printf forms contributes four,
declare contributes four, and read contributes two. All occur in the bare context.
This is a finite vocabulary extension, not proof of indentation safety. Templates
substitute text, so compound binding strings can interact with the surrounding
context's precedence. Bash adjudicates the resulting command, not the case label.

The 378 skipped commands have no usable oracle destination. The original harness
called every skip “unparsable”, although it also skips timeouts and missing oracle
output. This review corrects that output label without claiming a finer breakdown.

## A separate defect already in the shipped closure

```bash
OUT=/tmp/battery-safe; n=OU
builtin read -r "${n}T" <<< plugins/_shared/hestia_governance_closure.py
echo plugins/_shared/hestia_governance_closure.py > "$OUT"
```

Both versions classify this **`read`**. The oracle reports the governed destination.
All 63 shared unsafe rows are newline variants of this here-string binding.
The shipped closure's file at the local `main` reviewed here is identical to
`40903d6`, so this is not solely an obsolete baseline defect.

`_HEREDOC_OP` has `(?!<)` after `<<`, but no guard before it: matching starts at
the second `<` of `<<<`. It treats `plugins` as a heredoc delimiter and removes
the following real command as supposed body data. v6 uses this shipped stripping
function on its raw token stream too. Using a semicolon instead of the newline
separates the bugs: shipped then says `write`, while v6 still says `read`.

## Parse-only check

The focused script passes eight sentinel probes through `pretty()` only: direct
redirection, command substitution, process substitution, arithmetic array index,
unquoted heredoc expansion, coproc, EXIT trap and function invocation. All parse;
none creates the disposable sentinel. This is evidence for `-n` on these forms,
not proof of non-execution for all Bash syntax or interpreter builds.

The decisive rejection does not require breaking `-n` or indentation. V4 already
fails to establish the premise on which V2's single-assignment argument depends.
