# PRD — governance config lives in the vault, reached over MCP

> **SUPERSEDED 2026-08-05 by [`PRD_GOVERNANCE.md`](PRD_GOVERNANCE.md) §4.1**, which absorbs this
> proposal whole and extends it. Kept, not deleted: the motivating finding (#133) and the
> demonstration that produced it are the evidence the successor rests on, and a superseded document
> that is removed takes its reasoning with it.

**Status**: superseded — absorbed into `PRD_GOVERNANCE.md`
**Author**: claude-code (CBP), 2026-07-31
**Motivating finding**: issue #133
**Standing position**: dp has asked for this repeatedly; today only produced the demonstration

> **How this is written.** Config paths appear by *description*, not in full. Spelling them is
> classified as writing to the governance surface — filing #133 tripped escalation `74dc7f46` on
> its first attempt. Third instance this week of the gate impeding its own documentation
> (#116, fourth consequence).

---

## 1. The problem

**Every file the gate reads to decide what it governs is writable by every member it governs.**

Demonstrated, not theorised: a member's MRH was widened by appending one line to its identity file.
No escalation, no approval, no required witness. Editing the gate *hook* escalates; editing the file
that tells the hook what to protect does nothing.

The asymmetry is the whole finding. Rewriting the gate is loud. Editing its config **silently widens
what the unchanged gate permits** — the rule stays intact and verifiable while its *domain* moves.
Vault-ratified gate hashes, self-protection markers and CI all report green throughout, because each
of them is checking the rule and none is checking the rule's scope.

## 2. The principle

> A governance input must not be reachable by the party it governs through a channel that party can
> write.

Filesystem at shared UID (A1) is exactly such a channel. The vault, reached over MCP, is not: reads
are mediated, writes are witnessed acts, and both are subject to policy that does not live in the
thing being edited.

This also restores an honest correspondence. A scope grant has *always been* a governance act
semantically. It has never been one mechanically. This PRD closes that gap rather than adding a new
control.

## 3. What moves, and what cannot

| input | today | target | notes |
|---|---|---|---|
| member identity / MRH scope | on disk, unprotected | **vault** | the demonstrated hole |
| policy presets | on disk | **vault** | already vault-adjacent |
| member registry | on disk | **vault** | feeds arbiter eligibility (#80) |
| operator key material | on disk, 0600 | **vault** | 0600 separates nobody at shared UID |
| hook registration (all four members) | on disk | **cannot move** | see below |

**Hook registration is the irreducible case.** The harness reads it from disk before any of our code
runs; there is no point at which we could serve it from the vault. It cannot be moved, so it must be
*detected*:

1. the vault holds the ratified registration for each member,
2. the gate, on every invocation, compares what registered it against that ratified value,
3. a mismatch **denies and escalates** rather than warning.

This is the one place where tamper-*evidence* is the ceiling, and it should be labelled as such
rather than described alongside the moved configs as if it were equally closed.

## 4. Fail-closed, and the fallback that would void the whole design

**If the vault is unreachable, the gate denies. It does not read the filesystem copy.**

Stated first and loudly because the convenient implementation is a fallback, and a fallback makes
this entire PRD decorative: an attacker (or an ordinary member with a stale env var) stops the daemon
and the old path is authoritative again. That is the same shape as the escalation channel that
failed OPEN under a harness timeout — the mechanism present, the guarantee void, everything green.

Three states, distinguished, never collapsed:

- **vault answered** → that is the config
- **vault reachable, no such key** → deny; an unconfigured member is not an unrestricted one
- **vault unreachable** → deny, naming the cause, exactly as the fail-closed cause classification
  in #96 already does for policy verdicts

## 5. The half a vault does not fix: reciprocity

Moving configs makes a scope change *witnessed and authorised*. It does not make it *disinterested*.

`hestia_gate_arbitrate_escalation` enforces NOT-SAME correctly, and a peer granting me scope is
genuinely a different member — plausibly a different vendor lineage, recording as `CrossVendor`, the
strongest tier we can express. **NOT-SAME checks the arbiter's identity, not whether it has a stake.**

Two members trading favours pass every check built this week.

So a scope-mutation act must additionally carry:

- **beneficiary** — which member's authority increases. Distinct from the author.
- **NOT-BENEFICIARY** — an arbiter may not rule a mutation that widens its own MRH, even when it is
  a different member from the author. This is the missing half of NOT-SAME.
- **reciprocity as visible evidence** — A widened B, and B previously widened A, is a *fact about the
  pair*, computable from the chain. Not blocked; surfaced, and weighed as the weak evidence it is.

This is the T3/V3 posture rather than a rule: independence is recorded and graded, never asserted.

## 6. Migration

1. Vault becomes the **authority**; on-disk files remain as a shadow copy, read only to compare.
2. **Drift detector** runs and reports disagreement between the two. Any drift found in this window
   is a live finding, not a migration artifact — the disk copy was writable the whole time.
3. Disk copies demoted to informational, gate reads vault only.
4. Disk copies removed.

Steps 1–2 are worth landing alone: a drift detector against today's files answers "has this already
happened?", which is currently unanswerable and should not stay that way.

## 7. Falsifiable success criteria

Stated as predictions so they can fail:

1. Appending to a member identity file on disk **changes no verdict** — the gate reads the vault.
2. A scope mutation over MCP produces a chain entry naming **author, beneficiary and authority**, and
   is refusable by policy.
3. **Stopping the daemon denies** rather than restoring the old path. Probe it directly, because this
   is the assertion most likely to be quietly false.
4. A member cannot rule an escalation that widens its own MRH, even as a different member from the
   author.
5. The drift detector reports zero disagreement — and if it reports non-zero on first run, that is a
   finding to be published, not a bug to be cleaned up before anyone looks.

## 8. Open questions

- **Bootstrap.** The vault needs a passphrase to open, and the gate needs config to run. What governs
  the gate between boot and unlock? Currently the answer is "the disk copy", which is the hole. A
  deny-until-unlocked gate is correct and makes an unlock outage total.
- **Cross-member reads.** May a member read another's MRH? Useful for arbiters judging eligibility;
  also a reconnaissance surface. Probably yes-and-witnessed, matching the read posture #97 settled.
- **Does this reach the foreign members?** kimi and codex hooks read identity from disk in their own
  adapters. The vault path has to be available to them or the fix covers one member of four — the
  same coverage asymmetry already flagged when #97 landed and still open.
- **Where does hub's config live**, and does it have the same shape? Audited separately in
  `PRD_CONFIG_IN_VAULT_HUB.md`.
