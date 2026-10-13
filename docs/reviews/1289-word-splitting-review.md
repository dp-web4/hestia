# HOLD: PR #1289 unquoted prose expands into file arguments

Review of notice **21669**, 2026-10-13. Reviewed head `03b26c38`;
held patch SHA256 `e2705d13e51f58595268361276ae1644efae1eb5b448365b690df62d7762111b`;
governed base `53008a50`. The digest and old hunk context were verified while
reconstructing the proposed core in memory. No governed source was applied or deployed.

The command-specific option table fixes the previous HOLD's flag-arity examples:
the original prose runner now passes **66/66**, independently reproduced. The new
counterexamples below still block this digest.

## P1: A shell word in a prose position can produce additional file arguments

Location: proposed `plugins/_shared/hestia_gate_core.py`, `_outside_candidates.data`
and its pending-option / `--option=value` callers (held patch's core hunk beginning
at old line 1885).

`data(word)` exempts an expansion unless its name appears in `globby` and the use is
unquoted. But pathname expansion is only one way an unquoted expansion changes argv.
Ordinary whitespace causes field splitting, so a value containing no glob can insert
another option or a positional filename. The prose exemption skips all those fields.

Let `OUTSIDE` represent a literal absolute filename outside the test policy's workspace:

```sh
R="hello --body-file OUTSIDE"; gh pr create --title $R
R="hello --body-file OUTSIDE"; gh pr create --title=$R
R="hello --body-file OUTSIDE"; gh issue create --title $R
R="hello OUTSIDE"; gh release create v2 --title $R
R="hello OUTSIDE"; gh release create v2 --notes $R
R="hello OUTSIDE"; gh release create v2 --notes=$R
```

Every row is an unenumerated once-only request on the base and **allow** on the held
core. This uses a value assigned in the same command, ordinary default field splitting,
and no glob, inherited variable, substitution, or private file.

An inert Bash `set --` / `printf` probe confirmed these argument vectors without
invoking `gh`:

```text
gh pr create --title hello --body-file SYNTHETIC_BODY
gh release create v2 --notes=hello SYNTHETIC_ASSET
```

The extra arguments have file semantics: `gh pr create` reads its body from
`--body-file`; `gh release create` takes trailing filenames as assets to upload.
Verified against installed CLI help and the official
[PR create](https://cli.github.com/manual/gh_pr_create) and
[release create](https://cli.github.com/manual/gh_release_create) manuals.
The release examples need no injected flag at all. Actual file reads or uploads
were not executed; the measured regression is the scope gate allowing these commands.

The quoted forms preserve one data argument and pass on both versions. The intended
quoted, glob-bearing `hestia --reason "$R"` case also passes on the proposal.

**Repair direction:** establish that an expansion contributes exactly one argument
before exempting it as prose. Preserve quoted prose, and either enumerate and reclassify
fields from an unquoted expansion or keep it an unenumerated request when single-argument
behavior cannot be established. Checking only for glob-bearing assigned values is
insufficient. This is separate from the acknowledged inherited-variable glob residual.

## Reproduction and limits

The companion [runner](scope-1289-word-splitting-regressions.py) is derived from the
earlier prose runner. It reconstructs the held core in memory, checks its digest and
each old hunk line, and never executes the represented commands. Its synthetic outside
paths are inside the checkout on disk but outside the narrower simulated workspace.

```sh
python3 -B docs/reviews/scope-1289-word-splitting-regressions.py --repo . --full-gate
python3 -B docs/reviews/scope-1289-word-splitting-regressions.py --repo . --held e2705d13e51f58595268361276ae1644efae1eb5b448365b690df62d7762111b --full-gate
```

| Version | Checks | Failures |
|---|---:|---:|
| Base | 66 | 0 |
| Held `e2705d13…` | 66 | 36 |

Six unsafe cases fail in the helper, core evaluator, and each of the claude-code,
codex, kimi, and gemini adapters. All four adapters return `gate.allow` with committed
stub evidence for those six cases. Direct-path and quoted-data controls behave as
expected. These are disposable policy-stub results, not a live-daemon acceptance run.

The supplied battery and earlier #1232 runners were not rerun: the reproduced
regression is sufficient to retain HOLD. The previous generic-option finding is
resolved; this document supplies the distinct remaining blocker.
