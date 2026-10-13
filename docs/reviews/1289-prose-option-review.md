# HOLD: PR #1289 prose options consume file operands

Review of notice **21630**, 2026-10-13. PR head `2dfd1182e7b4367a1d00b8625988d04d3f1788d0`;
held patch SHA256 `78386f56e15593aab2f3695208052f935418c145c9fe85a4e723cae678c76740`;
governed base `53008a50`. The patch digest and old hunk context were verified. Sources were
reconstructed in memory; this review does not apply or deploy the governed patch.

## P1: Generic prose options erase real file operands

Location: held patch lines 240–251 (`_PROSE_LONG_OPTS`, `_string_opts`), and the
pending-option branch of `_outside_candidates` that calls `data(w)` for these options.

`_string_opts` treats `--text`, `--notes`, and `--summary` as value-taking prose options
for **every command** unless its spec claims them as file, value, or code options.
The real commands below use them as flags that take no following argument. The gate
therefore consumes a real positional filename as data, skips its scope check, and permits
a command the base correctly refuses.

Let `OUTSIDE` stand for a literal absolute filename outside the test policy's workspace:

| Classifier input | Real option meaning | Base | Held patch |
|---|---|---|---|
| `grep needle --text OUTSIDE` | Treat input as text; next token is a file | deny | allow |
| `rg needle --text OUTSIDE` | Search binary input as text; next token is a file | deny | allow |
| `diff --text OUTSIDE /dev/null` | Treat files as text; next token is a file | deny | allow |
| `readelf --notes OUTSIDE` | Display note sections; next token is an ELF file | deny | allow |
| `git diff --no-index /dev/null --summary OUTSIDE` | Summarize changes; next token is a comparison path | deny | allow |
| `grep needle --text "$PROSE_REVIEW_UNSET"` | Variable supplies a file operand | once-only request | allow |

The first five cases require neither a variable nor a glob. This is broader than the
intended relaxation for non-binding prose variables. For the sixth, the classifier cannot
know which file the inherited variable supplies; the base correctly requests enumeration.

**Repair direction:** authorize prose semantics by the command and, where necessary, the
subcommand and argument position. Absence from a spec is not evidence that an option takes
a string. Removing these three spellings would repair these examples, but would leave the
same default assumption for other commands and options. Audit the new `-m` head list for
subcommand-dependent arity too. Preserve the intended quoted `hestia --reason` case.

## Reproduction and validation

The companion [runner](scope-1289-prose-regressions.py) never executes the represented shell
commands. Its synthetic outside targets are physically inside its checkout and outside a
narrower test workspace. The four-adapter arm uses the repository's disposable policy stub;
these are not live-daemon or deployment results.

From this checkout:

```sh
python3 -B docs/reviews/scope-1289-prose-regressions.py --repo . --full-gate
python3 -B docs/reviews/scope-1289-prose-regressions.py --repo . --held 78386f56e15593aab2f3695208052f935418c145c9fe85a4e723cae678c76740 --full-gate
```

Results: **base 66 checks / 0 failures; held 66 checks / 36 failures**. Six unsafe cases
fail in each of the helper, core evaluator, and claude-code/codex/kimi/gemini adapter arms.
Each adapter returns `gate.allow` with committed stub evidence on those six held cases.
Direct-path and option-after-path controls deny; ordinary reason and quoted echo controls
allow. The intended glob-bearing reason changes from request to allow as proposed.

Installed CLI help confirms the flag arities. Additional real CLI probes using disposable
files inside the review checkout confirmed that `grep`, `rg`, and `diff` read the supplied
file and `git diff --summary` reaches its comparison path. No outside file was read.

The initial four-adapter fixture did not create its simulated workspace directory, so
workspace detection fell back to the surrounding checkout and allowed direct-path controls
on the base. Those results were discarded. The committed runner creates a real temporary
workspace inside the checkout and cleans it up; the base's zero failures validate that seam.

The supplied 1,073-row battery and earlier runners do not establish this new option-arity
invariant. The counterexamples above are sufficient to **HOLD this digest**. Re-run them
against the revised proposal before clearing it.

Review artifacts only: no governance surface changed, no deployment authorized.
