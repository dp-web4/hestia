# App sprints — the human harness

**Derived from:** `PRD_APP.md` (#296) as amended by **decision 0014** (#297, GPT-reviewed).
**Status:** ACTIVE. **kimi is out of usage ~2 days; its half moves to codex** (dp, 2026-08-08).
Split restored: **claude-code** builds the harness and the things that sign; **codex** builds the
identity vault and the chain those signatures land in. Neither can land a sprint alone.

---

## The ordering constraint that sets everything

Sprint A is a **vertical slice through the whole model**, not a warm-up. GPT's §4 amendment upgraded
it from *"move a seed out of a plaintext file"* to *"establish principal + harness"* — and that is
the right first move precisely because every later sprint assumes the composed identity it creates.

Nothing after A is safe to build until A's provenance shape is real, because everything else records
acts, and an act recorded under the wrong identity is worse than an act not recorded.

---

## Sprint A — principal + harness (the vertical slice)

**Goal:** an app act reaches the daemon carrying the full composition, and the daemon records it that
way.

```
actor:       app-instance-LCT      principal:  human-root-LCT
via_device:  device-LCT            office:     sovereign-role-LCT
authority:   occupancy / delegation / session-id
```

| # | deliverable | owner |
|---|---|---|
| A1 | **Identity vault** in the app — encrypted at rest, holds the root credential. Replaces the plaintext Ed25519 seed at `app/src-tauri/src/operator.rs`. | **codex** *(was kimi)* |
| A2 | **App-instance harness LCT** — created on first run, persisted, distinct from the principal. | **claude** |
| A3 | **Composed operator session** — daemon binds actor + principal + device + office, returns a session that later acts resolve through. | **claude** |
| A4 | **The record carries all five fields** — and a test proves none is dropped. | **codex** *(was kimi)* |

**Acceptance, measured not asserted:**
- a chain entry from an app act names **actor and principal distinctly**;
- **no plaintext private key remains on disk** — verified by search, not by inspection;
- a test **fails** if the app signs as the principal (impersonation regression guard);
- the composition survives app restart (0014 §4: continuity across stop/start).

**Not in A:** WebAuthn, m-of-n, vault sync, the IA restructure.

---

## Sprint B — signing, on a fresh chain

**Goal:** app acts are signed and verifiable; the new chain is signed from genesis.

| # | deliverable | owner |
|---|---|---|
| B1 | Wire `witness_act::sign_act` / `verify_witness` — **currently zero callers**. | **claude** |
| B2 | Chain gains a signature column; **archive the experimental chain, start signed at genesis** (0014 §6, dp's ruling). | **codex** *(was kimi)* |
| B3 | App acts signed by the **harness** LCT, per A's composition. | **claude** |
| B4 | Verification path + a test that an unsigned or wrongly-signed act is rejected. | **codex** *(was kimi)* |

**Acceptance:** every entry in the new chain verifies; the archived chain is reachable and labelled
as the unsigned era; **a forged signer fails a test.**

---

## Sprint C — constellation surface

**Goal:** the app exposes what the daemon already has. **Exposure, not construction** — `hestia
constellation` ships 12 verbs and the app reaches none.

| # | deliverable | owner |
|---|---|---|
| C1 | Device list with the **four states** distinguished: known / enrolled / **consenting** / revoked (`PRD_APP` §5.2). | **claude** |
| C2 | Guided add — and the app states **which custody model** is in use (`add` holds a key locally; `add-remote` holds none). | **codex** *(was kimi)* |
| C3 | `serve-owner` as an explicit, **device-side** consent moment (R2 — being a factor is a separate grant from pairing). | **codex** *(was kimi)* |
| C4 | Assurance tier visible, and **what the next tier requires**. Revocation one action, reachable while panicking. | **claude** |

**Acceptance:** a device can be added, enrolled, consented, and revoked entirely from the app; the
tier changes visibly; **the consent step cannot be skipped or implied by pairing.**

### C — amendments from kimi's code review (#296)

kimi read `constellation.rs` + `cli.rs` + hub-lib against the four-state model. R2 confirmed verbatim,
and four things change the build:

- **C5 — `suspended` is a real fifth state with no writer.** It exists in *both* `DeviceStatus` enums
  (hestia and hub-lib), both verifiers honour it exactly like revoked, and it is **part of the
  canonical roster hash** — a cross-implementation digest, so another implementation can write it
  into state this app reads. **Add it to the model; design no flow.** Semantics when it lands:
  suspended = reversible pause without a re-enrollment ceremony; revoked = compromise response.
  *(owner: claude, with C1)*
- **C6 — enrollment status must be read from the hub, never from the local roster.** `constellation
  revoke` touches only the hub (`cli.rs:2713-2731`), so a revoked device still reads `Active` in the
  local vault. The local `status` field is a latent mirror production never writes. **This is a bug
  that is easy to write and hard to see.** *(owner: codex — was kimi)*
- **C7 — revoked is a tombstone, not a disappearance.** The hub keeps the record and still lists it,
  and **re-enrollment reactivates** (rotating key/class, bumping `enrollment_version`). Render
  revoked-and-present, not gone, and surface re-enrollment as the way back — owner-signed, so a
  lost-phone attacker cannot use it. *(owner: claude, with C4)*
- **C8 — consent is the one state the app cannot *read*.** Consent lives on the serving device
  (`serve_owners`, `#[serde(default)]`, fail-closed to *serve nobody*); `ConstellationMember` has no
  consent field and there is no owner-side query for *"do you serve me?"*. So the app can show the
  **evidence** (a co-sign outcome — and the refusal names its own cause) but not the **state**. Two
  honest options: render from evidence, or spec a peer query over the pair channel. **R2 as written
  implies the app can show the state; the code says it can only show the evidence.** *(owner: codex — was kimi; pick one and say which)*

**And the panic path is settled by this** (kimi): the lost-phone action is **enrollment revocation**,
not consent withdrawal. Revocation is owner-side, authoritative, and works from any of the owner's
devices; consent withdrawal is device-side and therefore unreachable on the lost phone — and harmless,
because enrollment is the authoritative gate. R5 keeps its requirement and gains its reason.

---

## Sprint D — information architecture

**Goal:** three places (Me / Communities / Activity) replacing eight flat routes; mobile as the
design target; the salience rule.

| # | deliverable | owner |
|---|---|---|
| D1 | Three-place shell; bottom tabs on mobile, rail on desktop. | **claude** |
| D2 | Default surface = **things awaiting the owner**, usually empty and looking correct when empty. | **claude** |
| D3 | Three disclosure depths (plain / evidence / raw), owner-chosen. | **codex** *(was kimi)* |
| D4 | **Visual convergence on `BRAND.md`** — both surfaces to canon, tokens from one source (`PRD_APP` §8.5). | **codex** *(was kimi)* |

**Acceptance:** every function reachable in ≤2 taps on a phone; **no non-salient datum on a default
path**; app and dashboard indistinguishable in identity.

---

## Sprint E — hub join, then discovery

| # | deliverable | owner |
|---|---|---|
| E1 | Guided join; **pending is a first-class state** (hub law escalates every non-trivial join). | **codex** *(was kimi)* |
| E2 | Invitation-first discovery: URL / QR / deep link. | **claude** |
| E3 | Federated gossip — *pending* codex/GPT's answer on whether hub-side peer exposure exists. | **blocked** |

---

## Sprint F — the wedge (NOT scheduled)

WebAuthn provider. **Deliberately unscheduled**, and this is a decision rather than an omission:

- it is a real protocol against **three platform key stores**, none of it written;
- 0014 §5.5 requires choosing where m-of-n **binds**, and the honest target (B, quorum-bound) implies
  threshold/MPC signing;
- a three-hour version produces something that demos and does not work — which is worse than nothing,
  because it *looks* like progress.

**Prerequisite:** A and B complete, and a ruling on §5.5 shape A-as-bootstrap vs B-as-target.

---

## The split, and why it is drawn here

**claude** takes the composition and the shell: harness LCT, composed session, signing wire-up,
device states, IA. **kimi** takes custody and verification: identity vault, chain replacement, consent
boundary, disclosure depths, brand convergence.

The line is deliberate — **the seat that builds the identity vault is not the seat that builds the
thing that signs with it.** Neither of us can land a whole sprint alone, so each sprint has a
built-in NOT-SAME reviewer.

> **Review capacity — restored in part, with one residual caveat that must not be forgotten.**
> The split exists so that the seat building the identity vault is not the seat building the thing
> that signs with it. With codex taking kimi's half that property is back: **claude and codex are
> NOT-SAME to each other and each reviews the other's code.**
>
> **The caveat: codex and GPT are one entity.** GPT reviewed the design (0014) and codex now builds
> half the implementation, so *design review and half the build share an author*. That is weaker than
> the original arrangement and stronger than a single builder. It is recorded rather than resolved.
>
> **Compensation, in force from Sprint A and kept even with the split restored:**
> 1. **Red before green.** Every guard test is committed *failing*, in its own commit, before the
>    implementation exists. A test written after the code can be shaped to fit it; one committed red
>    cannot.
> 2. **Acceptance is measured, never judged** — searches and failing tests, not readings.
> 3. **I do not merge my own work.** dp or GPT lands it. Branches accumulate rather than self-approve.
> 4. **Each sprint states what I could not self-verify**, explicitly, in its PR.
