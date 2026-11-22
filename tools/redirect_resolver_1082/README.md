# Withdrawn redirect-resolver evidence (#1082)

Source: `55fdbc1cc695b949ef8bb99104e3c5774949ca5d`, branch
`cbp/redirect-target-resolvable`.

**Nothing in this directory is a production dependency or an approved gate candidate.**
The author withdrew the resolver series after command-identity and rebinding
counterexamples. v5 and v6 are included because their failures are reproducible evidence;
v7 is included only as the next historical control. A green battery is not certification,
and none of these files may be imported by the runtime gate.

## Generated evidence

From the repository root:

```sh
python3 tools/redirect_resolver_1082/redirect_resolver_battery.py \
  --file tools/redirect_resolver_1082/redirect_target_resolver_v6.py \
  --json /tmp/k1173-v6.json
python3 tools/redirect_resolver_1082/redirect_resolver_battery.py \
  --file tools/redirect_resolver_1082/redirect_target_resolver_v7.py \
  --json /tmp/k1173-v7.json
```

The battery loads the historical closure and resolver from git objects, generates shell
commands, and asks Bash to adjudicate destinations without performing the generated write.
Its counts are **generated-case results**, not observed fleet friction. In particular, the
ORDER dimension refutes v6; v7's zero on that same generated space does not make the
withdrawn candidate safe to install.

`redirect_target_resolver.py` is the historical v5 candidate. `redirect_v6_refusal_reasons.py`
attributes refusals in a supplied demand JSON; its intermediate safety claim was superseded
by the ORDER finding.

## Observed-corpus evidence

`redirect_corpus_demand.py`, `redirect_resolver_wild_census.py`, and
`out_of_grammar_exposure_census.py` are evidence probes, not scheduled jobs. They require
explicit `HESTIA_TRANSCRIPT_ROOTS`; the exposure census also requires an explicit
`HESTIA_CLOSURE_PATH`. They do not infer a corpus or classifier from the machine on which
they run. Output paths are controlled by the `HESTIA_*_OUT` variables documented in each
script.

Numbers in the harvested findings describe the authors' historical corpora. They are not
measurements of current traffic and must not be repeated as current counts without rerunning
against an explicitly supplied corpus.

## Retired source tooling

- `gate_self_access_refusal_census.py`: retired; its hardcoded corpus, checkout, and
  `resolver` import are superseded by the explicit-input corpus probes retained here.
- `redirect_target_resolver_suites.py`: retired; the source itself records that its suite run
  did not happen, and its hardcoded checkout no longer exists.
- `redirect_target_resolver_table.py`: retired as a runnable tool; its hardcoded checkout and
  machine paths are not portable. The generated battery covers the adversarial dimensions,
  and the harvested findings preserve the table and its subsequent refutations.

The separate here-string defect is **#1089**, fixed independently by `2a96c4f4`. Resolver
withdrawal neither dismisses nor reimplements that fix.
