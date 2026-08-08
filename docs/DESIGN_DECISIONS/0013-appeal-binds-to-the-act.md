# 0013 — An appeal binds to the act, not to a marker

**Status:** decided (dp, 2026-08-07). Supersedes the claim-token model.
**Supersedes in flight:** #244 fix (2) as proposed in-thread; #281's visibility approach (which
remains useful as an interim, but is not the repair).
**Composes with:** the signature premise (dp, same session) — orthogonal, both required.

---

## The defect this replaces

`claim()` joins on `(plugin_id, marker)` and nothing else. No tool, no target, no arguments, no
act identity.

A grant is therefore addressed to *"whoever calls themselves X, doing anything whose marker
resolves to Y."* Two consequences, both measured on 2026-08-07, both live:

**A grant is claimable outside its scope.** The operator approved a `Write` of a markdown file
under `/tmp`; its marker was a governance filename, and the real target appeared only in the `why`
prose that `claim()` never reads. **The same grant would have been satisfied by an edit to the
gate itself.** At claim time the two acts are indistinguishable.

**A grant is claimable by another agent.** `proven_asker` derives from a *`session_id` argument*;
omit it and the mismatch check is skipped, `asker_is_proven` is computed but never gates the
claim, and the call returns `claimed: true, permits_write: true`. Independently, `tool_connect`
takes `plugin_id` as a caller-supplied string — the handler's own comment says *"any local client
could then connect claiming `plugin_id = …`"* — so even the proven path proves only that the
caller repeated its own assertion.

The root shape: **a grant today is a token that authorises a future act.** Tokens travel.

---

## The model

### 1. Auditable provenance for every act, with composable fractal role and agent

Every act carries the composed identity that produced it — agent, role, instance, session — and
that composition is the provenance, not a single flat id. Sub-identities compose upward; the audit
trail is the composition.

### 2. The denied act is recorded, and the escalation references it

A denial is not an event that happened to a string. It is a **recorded act with an identity**, and
an escalation carries that identity. The act's status becomes **`appealed`** and stays there until
resolved.

### 3. A grant or denial resolves exactly one recorded act

Any grant or denial traces to the referenced, recorded act **alone**, and transitions *that act's*
state from `appealed` to `granted-on-appeal` or `denied-on-appeal`.

**A grant is not a capability. It is a verdict on a past act.** What it authorises is
**re-evaluation of the original recorded act, verbatim, from the chain**, and only for the
**originating role/agent chain**.

Nothing is minted, so nothing can be spent elsewhere.

### 4. Unattributed acts are not appealable

Not as sanction — as structure. **There is no agent to hand the result to.** A grant on an
unattributed act has no recipient; re-evaluation has nobody to re-evaluate *for*.

So an act with no attributable agent must be **refused at escalation-open time**, with that stated
as the reason. It must not open an escalation that later fails at claim.

> This is already observable, backwards. On 2026-08-07 approvals granted to escalations filed under
> the literal `unattributed` proved **unclaimable** — the system refused to deliver a grant to a
> non-entity, correctly, by accident, at the wrong moment and with a misleading error. The
> principle was already latent in the mechanism; it was simply not stated, so it read as a bug.

### 5. Timeout is a verdict, not an absence

An escalation that expires is recorded as **`denied on appeal — reason: timeout`**.

The state machine is therefore **total**: no act is stranded in `appealed`. This closes the
PRD §8.2 symptom *"escalations expire unruled overnight"* — not by preventing expiry, but by making
expiry a decision with a reason. An unlooked-at appeal and a refused one stop being
indistinguishable.

---

## Resolutions of the three implementation tensions

**Denials that cannot be recorded → the fallback, same availability-not-blocker principle** (dp).
A fail-closed denial caused by an unreachable daemon cannot write to the chain: recording requires
the path that just failed. That class does not become unappealable — it takes the fallback record
(plane E), and appeals reference it. Unavailability degrades the evidence; it does not remove the
right to appeal.

**Verbatim re-evaluation → resolve via hash of the original** (dp). The chain need not hold the
act's bytes — the plugin deliberately never sends full tool arguments to the daemon. It holds the
**digest**. At retry the member re-presents the verbatim act, the daemon re-evaluates it and
verifies the digest matches. A different act yields a different digest and is refused. Privacy
preserved, verbatim enforced — and the digest is the natural object to sign.

**State transition on an append-only chain → this is solved, do not reinvent it** (dp:
*"blockchains do this all the time, previous state is mutated constantly"*). Transitions are
appended and current state is a fold. The projection machinery already exists (#198).

---

## How this composes with signatures

Orthogonal, and both required:

- **This decision closes the SCOPE hole** — a grant cannot travel to a different act.
- **Signatures close the IDENTITY hole** — a grant cannot be presented by a different member.

Neither substitutes for the other. Both are independently valuable: act-binding holds under
declared identity, and signing holds under today's join key. They can proceed in parallel.

---

## What we already have

Measured on 2026-08-07 against `origin/main`, this is mostly a **wiring gap, not a build**:

| piece | state |
|---|---|
| denied act recorded with an identity | **exists** — `policy_decision` carries `action_id` |
| composed identity on that record | **exists** — `plugin_id`, `role_lct`, `instance_lct`, `session_id` |
| escalation → deny reference field | **exists** — `gate_escalation_opened.answers_deny` |
| that field ever populated | **never — 0 of 314** |
| act state machine + fold | projection machinery exists (#198) |
| signing primitive for the digest | **exists, zero callers** (`witness_act.rs`) |

The link from an escalation to the act it appeals has had a slot since it was designed, and has
never carried a value.

---

## Consequences to accept deliberately

- **Claim tokens disappear.** There is nothing to claim, so the marker/tool/target join class
  ceases to exist rather than being made stricter.
- **Some acts become unappealable** — the unattributed ones — and that must be *said* at open time,
  not discovered at claim time.
- **Re-evaluation can still deny.** A grant authorises re-evaluation, not an outcome. If law
  changed in between, the verbatim act may be refused again, and that is correct.
- **The originating role/agent chain is part of the binding.** The same agent acting in a different
  role is not the same appellant.
