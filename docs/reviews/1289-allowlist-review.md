# PASS: the expansion allowlist resolves the reported #1289 regressions

Review of notice **21911**, 2026-10-13. Reviewed head
`86925bb90f210473c76c87294952e1423b2653e1`, held patch SHA256
`c78ba6517d8f5be0db4774d78bba1fd16c0585b4fb493cba6464881b08596813`,
governed base `53008a50`.

**Release my HOLD 21861 for this exact digest.** No blocking finding remains
from this review. This is a code-review verdict; application and deployment
still use their applicable governance process. No governed source was applied.

The earlier implementation recognized particular splitting shapes and missed
positional indirection. `_per_element` now requires a head accepted by
`_ONE_WORD_HEAD` before treating a quoted braced expansion as one argument.
Unproved indirect forms, including `${!1}`, are judged. Nested operator words
are still checked recursively. This addresses the structural cause of the
last finding rather than adding only positional digits to `_INDIRECT`.

## Independent validation

Each runner verified the held patch digest and old hunk lines, reconstructed
the proposed shared modules in memory, and ran with `--full-gate` against
the disposable policy stub. Represented shell commands were not executed.

| Runner | Checks | Failures | Runner source commit |
|---|---:|---:|---|
| Prose option arity | 66 | 0 | `a5fa9d26` |
| Unquoted field splitting | 66 | 0 | `cbd024f4` |
| Quoted arrays | 66 | 0 | `c2a93488` |
| Nested arrays | 66 | 0 | `1b02b7fd` |
| Positional indirection | 66 | 0 | `e2cdf944` |
| **Total** | **330** | **0** | |

Each suite checks the reach helper, core evaluator, and all four adapters;
the adapter assertions also require committed evidence from the stub.
Controls include direct outside paths and intended prose/scalar behavior.

Invocation for each runner:

```text
python3 -B <runner> --repo <review-checkout> --held c78ba6517d8f5be0db4774d78bba1fd16c0585b4fb493cba6464881b08596813 --full-gate
```

Additional inert Bash probes used only array/parameter setup and `printf`.
Joined-array transformations `@A`, `@K`, `@k`, and `@Q`, and the analogous
joined positional forms, each produced one argument in those probes. These
are spot checks, not an exhaustive proof of Bash expansion cardinality.

## Limits

The optional battery invocation was blocked before execution: its proposed
in-memory fixture relocation contained the battery's original cache-path
literal, which the live gate judged out of scope. It was not retried. No
battery result is claimed here. The requester's 1293-check battery, corpus
replay, older #1232 runners, and broader contract suite were not independently
rerun in this review. The five completed regression suites establish the
reported fixes within their tested cases, not universal shell containment.

The six stray scope petitions named in notice 21911 were separately refused
at the requester's direction, with verified replies to their original notices.
