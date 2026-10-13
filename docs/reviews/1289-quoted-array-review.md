# HOLD: PR #1289 quoted arrays still add file arguments

Review of notice **21708**, 2026-10-13. Reviewed head `74aff7cf1045b3cc771187b2cb8e44e9978a7d0d`;
held patch SHA256 `743dad83d6ab4e6844c2f3ec0a2bc0eb6fb8a8a657ea2133c4c58a2a15cdeb65`;
governed base `53008a50`. The runner verified the patch digest and every old core
hunk line, then reconstructed the proposed core in memory. No governed source
was applied or deployed.

The prior word-splitting runner now passes **66/66** with `--full-gate`, independently
reproduced. That finding is fixed. The remaining blocker is the assumption that every
double-quoted expansion contributes one argument.

## P1: Quoted array expansion is exempted before its argument count is checked

Location: proposed `plugins/_shared/hestia_gate_core.py`, `_outside_candidates.data`,
the unconditional `continue` when an expansion is preceded by `_DQ_REF`.

Bash expands `"${A[@]}"` to one argument per array element, even inside double
quotes. The same holds for an array slice such as `"${A[@]:1}"`. These references
carry `_DQ_REF`, so `data()` skips them without checking their cardinality or
examining the arguments they contribute.

Let `OUTSIDE` stand for a literal absolute filename outside the simulated policy's
workspace:

```sh
A[0]=hello; A[1]=--body-file; A[2]=OUTSIDE; gh pr create --title "${A[@]}"
A[0]=hello; A[1]=--body-file; A[2]=OUTSIDE; gh pr create --title="${A[@]}"
A[0]=hello; A[1]=--body-file; A[2]=OUTSIDE; gh issue create --title "${A[@]}"
A[0]=hello; A[1]=OUTSIDE; gh release create v2 --title "${A[@]}"
A[0]=hello; A[1]=OUTSIDE; gh release create v2 --notes "${A[@]}"
A[0]=unused; A[1]=hello; A[2]=OUTSIDE; gh release create v2 --notes="${A[@]:1}"
```

All six are unenumerated requests on the base and **allow** on the held core.
The element assignments are data assignments, not file reads; all array contents
are specified in the same command. No inherited state, glob, or command substitution
is needed.

Inert Bash probes replacing the invocation with `set --` and `printf` confirmed:

```text
gh pr create --title hello --body-file SYNTHETIC_BODY
gh release create v2 --notes hello SYNTHETIC_ASSET
gh release create v2 --notes=hello SYNTHETIC_ASSET
```

Installed `gh pr create --help` identifies `--body-file` as a file read, and
`gh release create --help` identifies trailing filenames as release assets to
upload. No represented `gh` invocation, file read, or upload was executed.

**Repair direction:** require evidence of one argument before exempting a quoted
expansion in an argument-sensitive data position. Treat array-all, array-slice,
array-key, and positional-all expansions conservatively unless their resulting
arguments are enumerated and classified. The quote marker alone is insufficient.
The helper also allows `"${@:1}"` and `"${!A[@]}"` in the new prose positions;
those supplementary probes are not included in the counts below.

## Reproduction and limits

The companion [runner](scope-1289-quoted-array-regressions.py), derived from the
previous word-splitting runner, never executes the represented shell commands.
Synthetic outside paths are inside the checkout on disk but outside the narrower
simulated policy workspace. It uses a disposable policy stub, not a live daemon.

```sh
python3 -B docs/reviews/scope-1289-quoted-array-regressions.py --repo . --full-gate
python3 -B docs/reviews/scope-1289-quoted-array-regressions.py --repo . --held 743dad83d6ab4e6844c2f3ec0a2bc0eb6fb8a8a657ea2133c4c58a2a15cdeb65 --full-gate
```

| Version | Checks | Failures |
|---|---:|---:|
| Base | 66 | 0 |
| Held `743dad83…` | 66 | 36 |

The six unsafe cases fail in the helper, core evaluator, and each of the
claude-code, codex, kimi, and gemini adapters. All four adapters report
`gate.allow` with committed stub evidence for each unsafe case. Direct-path,
quoted-scalar, and intended quoted-reason controls behave as expected.

The battery, generic-option runner, and older #1232 runners were not rerun in this
review: this independently reproduced regression is sufficient to retain HOLD.
The earlier unquoted-splitting blocker is resolved; quoted argument multiplicity
is the remaining finding for this digest.
