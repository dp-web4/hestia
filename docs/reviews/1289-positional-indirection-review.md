# HOLD: positional indirection can still add file arguments

Review of notice **21836**, 2026-10-13. Reviewed head
`afd36bbe95bc69fab0b6c37279e8e07fb33e52fe`, held patch SHA256
`b7ec48209278b6c7c332504f27ad883557cecd96b281b84efa1b1b1de7b504b2`,
governed base `53008a50`. The runner checks the digest and old hunk lines,
then reconstructs proposed shared modules in memory. No governed source was
applied or deployed.

The previous nested-array runner now passes **66/66** with `--full-gate`,
independently reproduced. Its reported cases are fixed. A related indirection
case remains: the target name can come from a positional parameter.

## P1: `_INDIRECT` only recognizes identifier names

Location: proposed `plugins/_shared/hestia_gate_core.py`, `_INDIRECT` and
`_per_element`, used by `_outside_candidates.data`.

`_INDIRECT` requires an ASCII letter or underscore immediately after `${!`.
`${!1}` therefore passes through as a single quoted argument. Bash uses the
first positional parameter as the name to expand; when it is `A[@]`, the
result is one argument per array element.

Let `OUTSIDE` be a literal absolute filename outside the simulated policy workspace:

```sh
A[0]=hello; A[1]=OUTSIDE; set -- 'A[@]'; gh release create v2 --notes "${!1}"
A[0]=hello; A[1]=--body-file; A[2]=OUTSIDE; set -- 'A[@]'; gh pr create --title "${!1}"
```

All array contents and the target name are specified in the command. There is
no inherited shell state, command substitution, or filesystem access required
to demonstrate the argument expansion.

An inert Bash probe using `printf` instead of invoking `gh` confirmed:

```text
<gh>
<release>
<create>
<v2>
<--notes>
<hello>
<SYNTHETIC_ASSET>
```

The companion runner exercises this expansion in six positions: PR title,
PR title with equals, issue title, release title, release notes, and release
notes with equals. Each is a request on base and **allow** on the held core.
The failure reproduces in the helper, core evaluator, and all four adapters.
The adapter allows have committed evidence from the disposable policy stub.

Repair direction: account for positional parameters in indirect expansion,
or conservatively request review whenever the indirect target's cardinality
is unproved. The named-variable regex is not the whole indirection grammar.

## Reproduction and limits

The [runner](scope-1289-positional-indirection-regressions.py) never executes
the represented commands. Its synthetic outside paths remain inside the
checkout on disk, outside only the narrower simulated policy workspace.

```sh
python3 -B docs/reviews/scope-1289-positional-indirection-regressions.py --repo . --full-gate
python3 -B docs/reviews/scope-1289-positional-indirection-regressions.py --repo . --held b7ec48209278b6c7c332504f27ad883557cecd96b281b84efa1b1b1de7b504b2 --full-gate
```

| Version | Checks | Failures |
|---|---:|---:|
| Base | 66 | 0 |
| Held `b7ec4820...` | 66 | 36 |

Controls cover a direct outside path, nested scalar, nested joined array,
quoted echo, and the intended prose-reason change. The scalar/star/prose
controls intentionally change from request on base to allow on held.

An initial exploratory `${!#}` candidate was discarded: the inert Bash probe
produced the single string `A[@]`, not multiple elements. A separate compound
probe involving nested positional indirection was blocked by the live gate;
it was not retried, and this report makes no claim from its execution.
The final runner uses only `${!1}` for the six unsafe cases.

The full battery, corpus, and other older runners were not rerun. The fixed
nested-array runner and this new regression are sufficient to retain HOLD
for this digest; this is a review verdict, not an application authorization.
