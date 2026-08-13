# Codex fleet review — gate consolidation A–G

**Disposition: BLOCK. Do not merge the train as complete and do not deploy it.**

Reviewed for notice 2156 / issue #409 at these exact heads:

| Sprint | PR | Head |
|---|---:|---|
| A | #398 | `4dfadbd29c569dce711592780a047b3b07eb6427` |
| B | #399 | `024e59a025944f9f4ca5ea3a410d055dee2548e0` |
| C | #400 | `15825308d5ae6763646ab258fafdd63cafd72ca2` |
| D | #401 | `0835c4bc8c38755c30f3b6dfe754dceefb806905` |
| E | #403 | `5f147ad2204162cfbfcc1f8e8aa8cb08abc1862d` |
| F | #406 | `9bc2e1ff6916a6899e1141800f1eaae251797198` |
| G | #408 | `09d90dab55b24ed90b8d006dfa6dcbecb4d8f2a0` |

The architecture remains the right direction: one transport-free law core, thin harness
adapters, a shared mechanism, explicit degraded semantics, and deployed-generation evidence.
The exact implementation does not yet satisfy its own falsifiable criteria. Several failures
are already reported by the train's own tests; others are source-level gaps in claims introduced
at G.

## Blocking findings

### 1. PR #408 retires the Codex bundle's hooks but leaves an installable manifest pointing at them

Sprint G deletes the complete directory
`plugins/codex/marketplace/plugins/hestia-codex/hooks/`, while the surviving plugin manifest still
declares `"hooks": "./hooks/hooks.json"`. The marketplace indexes still advertise that plugin.
This is neither deduplication nor retirement: it is a published package whose declared entrypoint
does not exist.

The exact-head CI catches adjacent consequences:

- `plugins/codex/tests/marketplace_parity_test.py` is red;
- `tools/identity_classification_test.py` still discovers the half-retired marketplace producer and
  is red on producer-shape divergence.

Required resolution: either remove the marketplace/plugin registration as a deliberate retirement,
or make the package derive its hooks from the canonical source and restore a valid, digest-pinned
entrypoint. Deleting only the implementation while retaining the installer surface is not safe.

### 2. Criterion 8 is not met: Codex refuses closure writes but its escalation/claim path is broken

`plugins/codex/hooks/pre_tool_use.py` changed `deny()` to accept `(rule_id, reason)`, but the closure
write call site still passes `(rendered_sentence, remediation_sentence)`. The rendered sentence is
therefore treated as an unregistered rule. Codex never opens or claims the required gate escalation.

The committed process-level boundary battery reports **4/10 passed**. Six closure arms are red,
including ordinary Write, `apply_patch`, Bash, approved write continuation, shared-mechanism write,
and witnessed read. The failure is visible as “no remedy registered,” with no escalation claim.

`cross_harness_closure_test.py` nevertheless reports criterion 8 green because it invokes only each
shim's bound classifier function. It equates “classifier returned a rule id” with
“refused-and-escalatable”; it never executes the shims' deny/escalation paths. That inference is
false on the exact Codex shim.

Required resolution: wire Codex to the same real escalation/claim lifecycle, make the 10 process
arms green, and change the cross-harness criterion test to exercise refusal plus approval/claim—not
classifier return values alone.

### 3. Sprint F's acceptance tests do not test the committed tree in CI

Both `sprintF_test.py` and `break_the_core_test.py` default `TREE` to
`plugins/_shared/tree`. That staging tree is not committed. The claimed 9/9 and 2/2 results were
obtained against an out-of-tree drafting layout through `SPRINTF_TREE`; under the repository's bare
CI runner, all Sprint F cases fail before reaching the behavior under test.

At exact G, the plugin job reports seven failing test files overall. Besides the two vacuous F
launches and the product failures above, the self-protection inventory is red and ten newly added
shebang files have mode `100644`, violating the repository's executable-bit guard.

Required resolution: default the acceptance tests to the repository root, retain explicit
out-of-tree override support, set tracked executable modes, and require the full discovery job to be
green. Scratch verification cannot substitute for the checked-in execution path.

### 4. Sprint G's core digest is absent from every normally delivered refusal

`witness_decision_unified()` builds a local `record` containing `core_digest`, but the arguments sent
to `hestia_witness_decision` omit that field. The digest survives only in the local fallback record
when witness delivery fails. When the daemon is healthy—the path the dashboard is meant to observe—
the claimed attestation is discarded before transport.

Thus “every refusal record now carries it” and PRD criterion 7 are false at the exact head. No G test
inspects the delivered witness arguments for the digest, which is why this remained green in the
narrow suite.

Required resolution: add a daemon/witness schema field (or an explicitly supported metadata
envelope), send the digest on the successful path, persist it, and test both delivered and fallback
records. The dashboard consumer can remain follow-up; producing observable evidence cannot.

### 5. The Bash write-position classifier misses ordinary compound-command writes

The classifier tokenizes with `shlex` in whitespace-splitting mode, which discards newlines, while
its separator set contains punctuation separators but no line boundary. A destructive command after
a newline is therefore folded into the first simple command's argument vector; target extraction is
performed using only the first command name. A direct closure write in that later command can classify
as a read or none.

The same claimed “any closure write” boundary omits common direct writers such as `git apply`,
`patch`, and directory-creation forms. Indirect execution can reasonably remain a disclosed residual;
ordinary shell grammar and standard direct writers cannot while criterion 8 says *any element* is
refused and escalatable.

Required resolution: preserve command boundaries (including newlines), define the supported grammar
as a tested allow/refuse contract, add differential positive cases for every command boundary, and
either cover standard direct writers or narrow the acceptance claim to what the parser actually
prices. Attestation after mutation is detection, not refusal.

### 6. The “hardened” path predicate still uses substring/prefix matching for member-home scope

`path_in_scope()` checks `m in low` or `low.startswith(expanduser(marker))` for `home_markers` before
normalization and without a separator boundary. A sibling whose name merely starts with the member
home directory name, or a path containing the literal marker text, is granted as home scope. This is
the same boundary class the train says it removed for temp/workspace paths, left active in the third
scope arm.

Required resolution: expand and normalize each home root, then accept only exact-root or
root-plus-separator containment; add sibling and traversal controls for both adopting profiles.

## Operator decision: hold R1 deployment

I recommend **HOLD**, not the runbook's recommended “accept tightening.” R1 and R2 compose into a
non-recoverable operating boundary:

- standing repository scope has no daemon surface;
- live `hestia_request_scope` path grants are carried but inert in the segment-keyed evaluator;
- launch at the workspace root yields no launch-repository grant;
- the remaining launch grant is still derived from local environment/cwd state, contrary to the
  ratified authority boundary.

This is more than a tightening. A member launched above a task repository can lose all repository
reach and the advertised scope-request remedy cannot restore it. Land an authenticated standing-scope
surface plus an effective exact-path grant predicate, then remove the environment-derived launch
authority and re-review the deployed behavior.

## Integration and evidence notes

- Sprint A head `4dfadbd` is **not an ancestor** of Sprint G head `09d90da`. At G, the PRD still says
  “Not started.” The deploy note's “tip carries all” statement is therefore false for A. Merge A
  explicitly and resolve the status/contract before representing the tip as A–G.
- GitHub's exact-head plugin job is red, while the PR descriptions say suite-gated green. The red is
  train-caused and reproducible from the CI log; it is not an unrelated baseline.
- The currently installed gate refused my direct invocation of the named gate test files as a Bash
  write even though the act was execution/read. I did not route around that refusal; the exact-head
  GitHub job supplied the process evidence above. This is a live false-positive datum for the same
  classifier family, not part of the six source blockers.

## Re-review bar

Re-request review when:

1. the complete Python plugin discovery job is green at the new exact heads;
2. Codex's 10/10 boundary battery proves actual refuse/escalate/claim/read behavior;
3. the marketplace is validly derived or fully retired;
4. successful witness delivery demonstrably persists the loaded-core digest;
5. Bash command-boundary and home-sibling negative controls land; and
6. R1/R2/R3 have an operator-approved authority path rather than a deploy-time warning.

Until those hold, the strongest honest status is **architecture accepted, implementation blocked**.