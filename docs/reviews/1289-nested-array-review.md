# HOLD: nested parameter expansions still add file arguments

Review of notice **21755**, 2026-10-13. Reviewed head
`292348bfb24eced506af7c7e94ec98e347a07b91`, held patch SHA256
`3174573d0d4adc7e87eff07f5c851e1c35b83b5a314637ae286d3adf68353fd9`,
governed base `53008a50`. The runner checks the patch digest and old hunk lines,
then reconstructs the proposed shared modules in memory. No governed source was
applied or deployed.

The previous quoted-array runner now passes **66/66** with `--full-gate`,
independently reproduced. Direct array expansions are fixed. Nesting the same
expansion inside a parameter default or alternate value bypasses the new check.

## P1: `_PER_ELEMENT` checks only the outer parameter's prefix

Location: proposed `plugins/_shared/hestia_gate_core.py`, `_PER_ELEMENT` and
`_outside_candidates.data`, in the `_DQ_REF` branch.

`data()` exempts a quoted expansion unless `_PER_ELEMENT.match(ref)` identifies
an array or positional expansion at its beginning. `_expansion_spans()` ends a
`${...}` span at the first closing brace rather than traversing nested parameters.
For `${R:-${A[@]}}`, the span begins with `${R:`, so the per-element check misses
the array inside the default value and the unconditional `continue` exempts it.
Bash still produces one argument per array element when that branch is selected.

Let `OUTSIDE` be a literal absolute filename outside the simulated policy workspace:

```sh
A[0]=hello; A[1]=--body-file; A[2]=OUTSIDE; R=; gh pr create --title "${R:-${A[@]}}"
A[0]=hello; A[1]=--body-file; A[2]=OUTSIDE; R=; gh pr create --title="${R:-${A[@]}}"
A[0]=hello; A[1]=--body-file; A[2]=OUTSIDE; R=yes; gh issue create --title "${R:+${A[@]}}"
A[0]=hello; A[1]=OUTSIDE; R=; gh release create v2 --title "${R:-${A[@]}}"
A[0]=hello; A[1]=OUTSIDE; R=yes; gh release create v2 --notes "${R+${A[@]}}"
A[0]=hello; A[1]=OUTSIDE; R=; gh release create v2 --notes="${R:-${A[@]}}"
```

All six are unenumerated requests on the base and **allow** on the held core.
All values and branch choices are specified in the command itself. No inherited
state, command substitution, glob, or file access is necessary to demonstrate it.

Inert Bash probes using `set --` and `printf` instead of invoking `gh` confirmed
that each tested default/alternate array form produces:

```text
<gh>
<release>
<create>
<v2>
<--notes=hello>
<SYNTHETIC_ASSET>
```

The nested `${A[*]}` control produces one `--notes=hello SYNTHETIC_ASSET`
argument. No represented file read or upload was executed.

**Repair direction:** establish single-argument cardinality recursively for
parameter operator words, or conservatively request review for nested expansions
whose cardinality is unproved. Matching only the outer expansion's prefix is not
enough. Nested scalar and joined-array controls should remain single arguments.

## Reproduction and limits

The companion [runner](scope-1289-nested-array-regressions.py) never executes the
represented shell commands. Synthetic paths are within the checkout on disk but
outside the narrower simulated policy workspace. The four-adapter arm uses a
disposable policy stub, not a live daemon.

```sh
python3 -B docs/reviews/scope-1289-nested-array-regressions.py --repo . --full-gate
python3 -B docs/reviews/scope-1289-nested-array-regressions.py --repo . --held 3174573d0d4adc7e87eff07f5c851e1c35b83b5a314637ae286d3adf68353fd9 --full-gate
```

| Version | Checks | Failures |
|---|---:|---:|
| Base | 66 | 0 |
| Held `3174573d...` | 66 | 36 |

Each unsafe case fails in the helper, core evaluator, and claude-code, codex, kimi,
and gemini adapters. All four adapters allow with committed stub evidence.
The direct-path, nested-scalar, nested-star, quoted-echo, and intended-reason
controls behave as expected. Nested scalar/star controls intentionally change
from request on base to allow on held.

The full battery, corpus, and older runners were not rerun in this review. The
previous quoted-array runner passes; this independently reproduced regression
is sufficient to retain HOLD for this digest.
