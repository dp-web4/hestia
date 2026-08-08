# GPT review — decision 0014 and the current Hestia juncture

**Date:** 2026-08-08  
**Reviewer:** GPT  
**Hestia `main` baseline:** `4d4cad647f8d1cd2c50ab820f9a838c7f75b09a3`  
**Primary review target:** PR #297 / `da728f78158971bcbafe4a33c0beea00872f08b8`  
**Companion:** PR #296 / `157ebb12a6acc604f22c139e16d76e86101afbda`  
**Disposition:** **CHANGES REQUESTED — direction strongly endorsed; several identity/authority boundaries must be made explicit before ratification.**

---

## 1. The juncture

The center of gravity has moved again.

Two days ago the dominant question was whether Hestia had a coherent governance destination. It now largely does. Since my previous re-audit:

- the generic all-member installer landed (#272), and registration-derived targets were folded into it (#285), resolving the installer-fork concern in the right direction;
- decision 0013 landed (#283): appeal becomes a transition on one recorded act rather than a portable capability;
- the governance PRD was refreshed (#284) with act binding, deployment-state distinctions, actor/instructor/beneficiary provenance, and the deputy boundary;
- asker mismatch is now witnessed on both doors (#288);
- deployment and ancestry probes landed (#289);
- the newline hole is preserved as opposite-sign evidence rather than silently papered over (#292);
- the full product/governance/release status was reconciled on current source (#293).

The current reference daemon is substantially more current than it was, but deployment is still a distinct state: #295 reports the daemon rebuilt at current source while three of four member gates remained on the previous day's copies. That is not a contradiction in the new model; it is exactly the distinction the model now knows how to state.

The important new turn is **human identity**.

PR #296 correctly notices that the owner is no longer an abstract persona. The last several days produced direct evidence of the human failure mode Hestia predicted: the operator became the resolver pool, was flooded with badly contextualized decisions, and began rubber-stamping. The app therefore stops being a weaker dashboard and becomes part of the governance architecture.

PR #297 then makes the deeper move: the app is a human harness, identity is a constellation, governance and identity are distinct domains, and ordinary WebAuthn/passkeys become the compatibility wedge into the existing world.

I think that move is correct.

I do **not** think the draft is ready to become a decision of record unchanged.

---

## 2. What I endorse without qualification

### 2.1 Governance and identity are different domains

Yes.

Machine governance state and human identity have different lifetimes, failure semantics, replication needs, and authority boundaries. Reinstalling a workstation must not be equivalent to destroying a person's identity.

The split should survive review.

### 2.2 The app is a human harness, not another dashboard

Yes.

The app should be a first-class participant in the same identity/role/provenance grammar as every other actor. Its value is not that it renders more Hestia state; it is that it allows a human to participate in governance with attributable, signed acts through an interface that makes good decisions cheap.

That is the right product and architecture framing.

### 2.3 Constellation management belongs at the center of the app

Yes.

The existing CLI already contains meaningful distinctions the app does not expose. In particular, pairing and consenting to serve as another entity's factor are not the same act. The app should make that separation obvious rather than bury it in a protocol.

### 2.4 WebAuthn is the right compatibility wedge

Yes, with the cryptographic qualification in §6.

This is not merely aspirational. Current platform APIs make a third-party passkey provider a real implementation target:

- Android Credential Manager supports third-party credential providers for passkeys;
- Apple AuthenticationServices exposes passkey-capable Credential Provider Extensions;
- current Windows 11 exposes WebAuthn plugin authenticator/passkey-manager APIs.

WebAuthn itself permits authenticators to be roaming hardware, platform hardware, software components, or implementations whose credential storage/signing is not confined to local client hardware.

So the proposition *"the outside world sees an ordinary WebAuthn credential while Hestia supplies the internal identity policy"* is architecturally valid.

It is a very strong wedge.

### 2.5 Archive the experimental chain and start the real signed chain cleanly

Yes.

If the present chain is explicitly experimental and has no external reliance that makes its continuity load-bearing, carrying an unsigned era into the durable format buys complexity without buying trust.

Archive it. Preserve it as evidence. Start the new format at genesis.

### 2.6 Move the operator secret out of plaintext immediately

Yes.

This is an independently valuable security improvement and a good first vertical slice. The current app reads the operator's Ed25519 seed from a plaintext JSON file. Moving that credential into protected identity storage is worth doing even if every larger decision in 0014 changes later.

But the identity it signs as needs one correction first (§4).

---

## 3. Required amendment: two domains does not mean two flat stores

The conceptual split is right. This table is not:

```text
phone vs workstation:
  governance — share nothing
  identity   — share everything
```

**Identity cannot share everything.** Web4's own multi-device binding model says why.

The Root LCT is common identity. Each Device LCT binds to a distinct hardware anchor. The device private key is specifically valuable because it is independent and, where possible, hardware-bound. Copying that private key to every device would destroy the independence that makes the constellation stronger.

Likewise, governance nodes may share signed law, role definitions, society projections, or policy generations even though their local gate state, chain, telemetry, and machine secrets remain local.

The better statement is:

> **Governance and identity are two domains, each with local and shareable strata.**

### Governance domain

**Machine-local:**

- local witness chain;
- Plane-E telemetry;
- gate/runtime state;
- machine secrets;
- installed artifact state;
- local policy-generation cache.

**Shareable/projected:**

- signed society law;
- canonical roles;
- authority/delegation projections;
- common policy artifacts where the MRH permits.

### Identity domain

**Person-wide / replicated:**

- Root LCT and constellation membership;
- public Device LCT records;
- enrollment/revocation history;
- recovery policy;
- selected encrypted credentials whose policy permits replication;
- account metadata required for continuity.

**Device-local / non-exportable where possible:**

- Secure Enclave / StrongBox / TPM private anchor keys;
- local passkey private material when the chosen provider model binds it locally;
- device unlock material;
- attestation keys and other hardware-root secrets.

So the decision remains **two domains**, not three. But the identity vault is not one blob that syncs wholesale. It is a logical domain containing **replicated identity state plus device-local custody**.

This amendment should be made before the phrase *identity vault sync* hardens into an implementation assumption.

---

## 4. Required amendment: the app currently has two incompatible identities

0014 says both:

1. the app is a member with **its own LCT**, filling a role; and
2. the app's first governance act is effectively **"I hold the sovereign's key and sign as them."**

Those cannot both be the provenance model.

If the app has its own LCT but signs consequential acts with the human/Sovereign private key, the record loses the harness actor precisely where the newly-adopted deputy/instruction-provenance model says the actor must remain visible.

If it signs only with its own LCT, it needs an explicit basis for exercising the human's authority.

The correct composition already falls out of decision 0013 and the refreshed governance PRD:

```text
human/root LCT      — principal / identity / beneficiary
        |
device LCT          — hardware anchor through which the person is present
        |
app-instance LCT    — harness/actor that sends the governed request
        |
role occupancy      — office being exercised (often Sovereign)
        |
delegation/session  — why this harness may act for this principal in this office now
```

A consequential record can then honestly say:

```text
actor:       app-instance-LCT
principal:   human-root-LCT
via_device:  device-LCT
office:      sovereign-role-LCT
authority:   occupancy/delegation/session-id
```

No identity disappears.

### Consequence for the first cut

Do move the operator credential into the identity vault.

But use that vertical slice to establish **principal + harness**, not to teach the app to impersonate its principal:

1. app instance has/creates its own harness LCT;
2. identity vault proves the human/root LCT through the protected credential;
3. daemon creates an operator session binding both identities plus the device anchor and office;
4. subsequent app acts resolve through that composed session.

That first increment would simultaneously exercise:

- the identity/governance domain boundary;
- signed identity;
- app-as-harness;
- canonical role occupancy;
- actor/principal provenance;
- the deputy closure.

That is a much stronger first cut than simply replacing the path from which one Ed25519 seed is loaded.

---

## 5. Required amendment: `device / node / mirror` are not sovereignty profiles

The decomposition is useful. The name is dangerous.

Hestia and Web4 have just spent significant effort separating **capacity** from **office**. `Sovereign` is an authority-bearing office. Calling `device`, `node`, and `mirror` *sovereignty profiles* reintroduces the same category error under a new vocabulary.

A phone can be an identity anchor without occupying the Sovereign office. A workstation node can run governance while its app occupies some other office. A mirror can belong to the Sovereign's constellation without itself having Sovereign authority.

Rename the concept to something like:

- **deployment profile**;
- **participation profile**; or
- **presence profile**.

Then retain the clean sentence:

> Any profile may be Sovereign-capable; Sovereign itself remains an office established through occupancy and authority.

This is not cosmetic. It keeps the role ontology clean exactly when the human side enters it.

---

## 6. Required amendment: define where m-of-n actually binds the passkey

This is the load-bearing technical issue in 0014.

The sentence

> *the relying party sees one ordinary passkey; behind it, Hestia decides how many devices had to click*

is plausible at the WebAuthn interface.

It is **not yet a security architecture**.

There are three materially different implementations hiding inside it.

### A. One device owns the WebAuthn credential private key; peers merely approve its use

Flow:

```text
RP challenge → credential-holding Hestia device
             → ask m-of-n peers
             → local device signs with ordinary private key
```

This produces the desired UX and WebAuthn response.

But if the credential-holding device is compromised strongly enough to use its private key outside Hestia's policy path, the quorum disappears. The m-of-n rule is policy around a **single cryptographic point of control**.

That may be acceptable under an A1/cooperative threat model. It does **not** satisfy the identity thesis that compromising one device should cease to be sufficient as the constellation grows.

### B. The WebAuthn credential itself is threshold-controlled

One RP credential/public key exists, but no one device can produce its assertion signature. A quorum participates in the signing operation or in an equivalent cryptographically-enforced key-use ceremony.

That is the shape that actually delivers:

> more independent devices ⇒ compromise of one is insufficient.

It is also substantially harder. It implies threshold/MPC signing or another hardware-enforced mechanism compatible with WebAuthn credential algorithms and platform provider APIs.

### C. Each device owns a different ordinary WebAuthn credential

This is straightforward platform WebAuthn, but the RP sees multiple credentials. Hestia cannot impose m-of-n transparently unless the relying party participates in the threshold policy.

That breaks the universal compatibility wedge.

### Decision required

0014 should explicitly say which assurance it means.

My recommendation:

> **The product wedge is WebAuthn provider compatibility. The target security model is a quorum-bound credential operation such that possession/control of any single device anchor is insufficient once policy requires m>1. A single-key policy wrapper is permitted only as an explicitly lower-assurance bootstrap implementation and must not be described as cryptographic m-of-n.**

That keeps the wedge now without pretending the hard crypto already exists.

---

## 7. Required amendment: one-device parity is conditional, not automatic

The draft says a one-device Hestia constellation presented as a passkey is **exactly as good as the passkey the user already has**.

That is only true if the Hestia provider protects and exercises the credential at least as well as the passkey implementation it is replacing.

A software-encrypted key in an application vault is not automatically equivalent to a Secure Enclave-, StrongBox-, TPM-, Windows Hello-, or platform-provider-backed credential.

The accurate claim is stronger because it is falsifiable:

> **A one-device Hestia credential can match ordinary passkey assurance when its key custody, RP binding, user verification, and anti-export properties meet the platform's credential-protection bar. From that baseline, additional independent anchors can add Hestia assurance.**

This also aligns with Web4's existing software-anchor ceiling instead of silently overriding it for product convenience.

---

## 8. Required amendment: authentication availability may not silently lower assurance

0014 correctly leaves open what happens when policy says 2-of-3 and only one device is reachable.

The existing Hestia principle *availability should not become a blocker* cannot be copied into identity authentication without a qualifier.

For governance, a degraded mode can sometimes be witnessed and carry debt.

For authentication, silently changing 2-of-3 to 1-of-3 **under the same credential** creates the attacker's favorite path: make the other devices unavailable, then trigger the weaker rule. The external RP still sees the same credential and cannot know Hestia reduced its internal bar.

The constitutional line should be:

> **Availability may degrade service; it may not silently degrade identity assurance.**

When `m` cannot be reached, choices include:

- refuse this high-assurance credential use;
- enter a separate recovery ceremony;
- use a separately-defined lower-assurance credential/path whose downgrade is explicit and witnessed;
- invoke a pre-authorized emergency policy with a distinct trust/assurance result.

What must not happen is invisible threshold relaxation on the same high-assurance identity claim.

This decision belongs in 0014 because it determines the credential architecture, not merely later UI.

---

## 9. Required amendment: logical separation does not decide packaging

I agree with:

> **the app is not the daemon.**

I do not think 0014 has established:

> **the app does not bundle the daemon.**

Those are different decisions.

A desktop installer can ship/manage a daemon sidecar while preserving:

- separate processes;
- separate LCTs;
- separate vaults;
- separate authority;
- a real transport boundary.

For a nontechnical first-run path, bundling may be the best product answer. On a `device` profile it would install no daemon; on a `node` profile it might.

Ratify **logical and authority separation**. Leave **distribution/packaging** to the app/release design.

Otherwise an architectural identity decision unnecessarily constrains onboarding.

---

## 10. Required amendment: signed chain needs two different signatures

Starting a new signed chain at genesis is right.

But *"the app should be the first signer"* risks conflating two signatures that answer different questions:

### Actor signature

> Who authored/authorized the governed act?

Signed over the canonical `ActEnvelope` / act digest by the actor or authority composition defined for that act.

### Witness/chain signature

> Who witnessed the act, decision, ordering, and chain inclusion?

Signed over the chain entry / witness envelope by Hestia's witness authority, binding at least:

- canonical act digest;
- resolved actor/principal/office provenance;
- policy generation and decision;
- prior chain reference;
- timestamp/sequence;
- evidence/transition type.

The app can absolutely be the **first actor producing signed acts**.

The durable chain format should nevertheless define both signature roles before entry zero. Otherwise the first implementation will make one signature carry two meanings and the distinction will be expensive to recover later.

---

## 11. Recovery and identity-vault replication

The draft correctly leaves sync and hub witnessing open. One negative requirement should already be decided:

> **Never synchronize the identity vault as an opaque whole.**

Replication must be per record/class with explicit custody semantics.

Examples:

- Root LCT/public constellation state — replicated;
- device public keys and attestations — replicated;
- device private anchor keys — never exported;
- RP credentials — replicated, threshold-shared, or local according to their credential policy;
- recovery material — quorum-controlled and separately governed;
- human profile metadata — MRH-scoped;
- revocation state — aggressively replicated.

A Hub may become a valuable **witness** for recovery without becoming an identity owner. It can attest to historical constellation state, revocations, membership, or prior proofs. That is different from possessing enough secret material to recreate the identity by itself.

Preserve that distinction when the recovery design starts.

---

## 12. PR #296 — app PRD disposition

The app PRD is directionally strong and should remain the companion document, with 0014 overriding the parts it explicitly changes.

The strongest requirements in #296 should survive:

- **R0:** judge the app by decisions the owner can make well, not information displayed;
- the `Me / Communities / Activity` information architecture;
- salience-first default surface;
- owner-controlled progressive disclosure;
- explicit device-side factor consent;
- invitation-first / trust-riding discovery rather than prematurely introducing a central registry;
- pending membership/join as a first-class state;
- visual design converging on canon instead of propagating dashboard drift.

One consequence of this review: the `Me` area is not merely *identity*. It should eventually expose the distinction among **human identity, devices, harness/app instances, and roles**, while keeping that ontology out of the default surface unless needed.

The internals can be exact without forcing the owner to think in ontology terms.

---

## 13. Revised first vertical slice

I recommend a slightly richer first cut than 0014 currently names, still small enough to execute before WebAuthn.

### Identity-vault operator login v0

1. Create/open a local identity vault in the Tauri shell.
2. Import the existing operator/root credential from `operator.key` once, then securely erase/retire the plaintext source through an explicit migration ceremony.
3. Give this app installation an **app/harness LCT**.
4. Bind or resolve the current **device LCT**.
5. Authenticate the human/root LCT with the protected identity credential.
6. Request an operator session from the daemon carrying/proving:
   - human principal LCT;
   - app/harness LCT;
   - device LCT;
   - requested office/role;
   - occupancy/delegation basis.
7. Daemon returns a session whose provenance contains all four rather than flattening them into `operator`.
8. Perform one consequential operator act from the app and verify its witness record preserves that composition.

No WebAuthn required yet.

This slice gives immediate value, removes plaintext custody, and proves the exact identity grammar that the later passkey provider will need.

Then WebAuthn becomes another transport/authenticator front end to a model that already works rather than the place the model is invented.

---

## 14. Sequencing at the juncture

The identity/app track should begin **in parallel**, not replace the governance migration.

### Governance track remains critical

- installed harness parity;
- Plane-E live proof;
- one executing shared gate;
- key-bound actor identity;
- act-bound appeal implementation;
- NOT-BENEFICIARY;
- third-verdict driver only after those boundaries hold.

### Human identity track can safely start with

- app-as-harness identity grammar;
- protected identity vault;
- plaintext operator-key migration;
- signed app act envelope;
- device-LCT association;
- app UX/IA from #296;
- platform passkey-provider spike(s), explicitly not yet claiming threshold assurance.

### Do not make public-release readiness depend on full m-of-n WebAuthn

That is a new, substantial product/security track. It should not become a hidden prerequisite for closing the existing Hestia governance release.

The first public Hestia can use ordinary operator authentication while the passkey provider matures, provided the release says exactly what exists.

---

## 15. Ratification conditions for 0014

I would change my disposition to **RATIFY** when the decision incorporates these boundaries:

1. Two domains retained, but identity state explicitly decomposed into replicated state and device-local non-exportable custody.
2. Human/root LCT, Device LCT, app/harness LCT, and role occupancy are distinct in the provenance model.
3. The app does not "sign as" the human merely because it holds access to a human credential.
4. `device / node / mirror` renamed to deployment/presence/participation profiles; Sovereign remains an office.
5. The WebAuthn wedge states the m-of-n enforcement locus and distinguishes policy quorum from cryptographic quorum.
6. One-device passkey-equivalence claim is conditioned on equivalent key custody/user verification.
7. Unavailable quorum cannot silently lower assurance on the same credential.
8. Logical app/daemon separation is ratified without prematurely forbidding bundled installation.
9. Actor signatures and witness/chain signatures are distinguished before the new chain's genesis.
10. Identity-vault replication explicitly excludes wholesale replication of hardware-bound device secrets.

None of these rejects the direction.

They make the direction composable with the governance and identity principles Hestia has just spent several days discovering the hard way.

---

## 16. Final assessment

Claude's latest decision is important because it finds the missing bridge between Web4's identity model and something a normal person might choose **before** they care what Web4 is.

That is rare and worth protecting.

The key is not to let the elegance of *"one passkey outside, a constellation inside"* flatten the very distinctions Web4 exists to preserve.

The durable version is:

> **One familiar credential surface outside. Explicit principal, device, harness, role, and quorum provenance inside.**

And the deeper identity rule is the mirror of the governance rule Hestia has already learned:

> **A declaration that several devices approved is not stronger identity. The cryptographic operation must make one device insufficient when the policy says one device is insufficient.**

With those changes, I think 0014 is not just compatible with the current architecture. It is a natural next layer of it.
