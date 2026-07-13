# Claude Context for hestia

hestia is the local-first Web4 trust layer for AI agents: credential vault, MCP server,
society state, and witness chain. AGPL-3.0-or-later. See README.md and CONTRIBUTING.md.

## Accountability self-audit (run before shipping a surface)

Web4's ratified accountability norm (RWOA + S + V). Before proposing a diff that creates or changes a
**surface** - any path a caller can drive that can cause a **consequential act** (sign, admit/join,
assign role, amend law/policy, read or release a secret, spend/transfer, mutate governed state, or emit
an outward message on behalf of an identity) - run this self-audit and carry its block in the PR
description or commit message. When unsure whether an act is consequential, treat it as consequential.

Trust is a contextual preponderance of evidence scaled to stakes, not a boolean: low-stakes reversible
acts may pass on weak evidence (recorded); the required strength of evidence rises with consequence and
irreversibility.

**Gate question:** *Can this path cause a consequential act while, for that act's stakes, R / W / S / O /
A / V is not satisfied?* If yes for any clause at the act's stakes, the surface FAILS: fix before
shipping, or escalate with the recorded FAIL (writing the block after the fact to match what was built
is itself an A violation).

- **S - stakes + reversibility.** Classify the act (consequence low/med/high, reversible/irreversible).
  This sets the required strength of evidence and whether V applies. An unclassified surface defaults to
  high-consequence.
- **R - reachability is weak evidence, not authority.** A who-can-reach-it check (loopback, bind
  address, same-host, allowlisted origin, filesystem presence) as the *sole* basis for a high-stakes or
  irreversible act fails R. Reachability is admissible as part of the evidence, or alone only for
  low-stakes reversible acts. (Loopback launders through a same-host reverse proxy.)
- **W - witnessed identity + authority.** High-stakes acts need a witnessed, key-bound identity AND the
  authority for *this* act; absence of evidence sufficient for the stakes denies or escalates. No-law
  denies for acts whose stakes demand law.
- **O - order (preflight).** The R+W decision must dominate every side effect (store write, send, sign).
  A gate that runs after a mutation fails O; a denied act must leave state bit-identical.
- **A - atomic, self-witnessing record.** The act, its stakes assessment, and the evidence relied upon
  commit together in the signed hash-chained record; a record that omits its evidence-basis fails A even
  if a record exists.
- **V - catastrophic-risk veto.** Irreversible/high-consequence acts need an explicit veto/escalate path
  that can fire even when the evidence would otherwise proceed. (Reversible = risk-managed on
  preponderance; irreversible = conservative veto.)

Genesis acts run in a bounded, self-witnessing bootstrap window that cannot be re-entered once witnessed
authority exists.

Review-gate block (carry in the PR/commit; a construct-pointer per line, grep-able name not a drifting
line number):
```
surface: <name>   act: <consequential act>
S: <low|med|high>/<reversible|irreversible> [construct: ...]
R: <pass|fail|n/a> [construct: <auth site>]   W: <pass|fail|escalate> [construct: <identity+authority site>]
O: <pass|fail> [construct: <preflight> before <first side-effect>]   A: <pass|fail> [construct: <atomic commit>]
V: <present|absent|n/a> [construct: <veto/escalate path>]
verdict: <PASS | FAIL(block) | ESCALATE(human gate)>
```
