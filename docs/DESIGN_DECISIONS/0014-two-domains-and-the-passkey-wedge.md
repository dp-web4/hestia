# 0014 — Two domains, the app as human harness, and the passkey wedge

**Status:** draft for review (dp, 2026-08-08). Review order: GPT → kimi → fleet forum. **Not ratified.**
GPT review incorporated 2026-08-08; kimi second review incorporated 2026-08-11 (two divergences
corrected, two additions adopted — marked **(kimi)** below).
**Builds on:** decision 0013 (an appeal binds to the act), the signature premise, `PRD_APP.md` (#296).
**Supersedes in `PRD_APP.md`:** §2 assumed the app sits *on* a daemon architecturally. It does not:
the separation of authority and identity is logical and is ruled here. How the two are *packaged and
installed* is not ruled here — see §8, open list.

---

## 1. The split: governance and identity are two domains

dp: *"what is emerging, to me is two domains: governance (daemon/gate hooks/witness chain) and
identity (constellation, device binding, encrypting credentials at rest). so governance vault may
(should?) be separate from identity vault."*

**Adopted, and the separation is forced rather than preferred.** They differ on every axis that
matters to a vault:

| | governance | identity |
|---|---|---|
| scope | **per machine** | **per person** |
| lifetime | dies with the machine | must survive every machine |
| contents | law, policy, gate state, witness chain | device keys, constellation, credentials at rest |
| a phone and a workstation | share **nothing** | share the **replicated stratum**; never the device keys (§1.1) |
| loss event | reinstall | **identity crisis** |

One store makes "I reformatted my laptop" and "I lost my identity" the same event. They are not the
same event, and a design that cannot distinguish them will handle both badly.

**Consequence:** the app carries an **identity vault**. The daemon keeps the **governance vault**.
Neither is a subset of the other.


### 1.1 Two domains, each with local and shareable strata (GPT §3)

The first draft said identity is "shared everything". **That is wrong, and wrong in the direction
that would destroy the thesis.** Web4's multi-device binding model is explicit: the Root LCT is
common identity, each Device LCT binds to a *distinct hardware anchor*, and the device private key
is valuable **precisely because it is independent**. Copying it everywhere would remove the
independence that makes more devices stronger — it would make an n-device constellation exactly as
compromisable as its weakest device.

So the correct statement is not "two flat stores":

> **Governance and identity are two domains, each with a local and a shareable stratum.**

| domain | replicated / shareable | strictly local |
|---|---|---|
| **governance** | signed society law, canonical roles, authority + delegation projections, common policy artifacts where the MRH permits | witness chain, plane-E telemetry, gate/runtime state, machine secrets, installed-artifact state, policy-generation cache |
| **identity** | Root LCT + constellation membership, **public** Device LCT records, enrollment/revocation history, recovery policy, encrypted credentials whose policy permits replication, continuity metadata | Secure Enclave / StrongBox / TPM anchor keys, local passkey private material, device unlock material, attestation keys |

**This must land before "identity vault sync" hardens into an implementation assumption.** The
identity vault is a *logical domain* — replicated identity state plus device-local custody — not one
blob that syncs wholesale.

---

## 2. The app is a human harness

dp: *"hestia app becomes a 'human harness' in a way, and plugs into governance just like agents do.
app acts are signed by its lct, whether local or remote, and will typically be filling a role
(usually that of sovereign but not always)."*

This is the cleanest framing anyone has put on the app, and it resolves questions `PRD_APP.md` left open:

- The app is **not** a second dashboard. It is a **member**, in the same sense claude-code and kimi
  are members: it has an LCT, it fills a role, its acts are governed and recorded.
- The role is **usually sovereign, not definitionally so.** An app on a family member's phone might
  hold a lesser role on the same daemon. The app is not "the operator's window"; it is "a member
  that often occupies the operator's office."
- **The app is logically separate from the daemon.** Measured: `src-tauri` does not depend on
  `hestia` core, `daemon.rs` is 112 lines of `reqwest`, and `lib.rs:39` hardcodes
  `http://127.0.0.1:7711`. It is already a client; it should become a *member* rather than a viewer.
  **(kimi, restoring GPT cond. 8)** That measurement proves *logical* separation — distinct code,
  distinct authority, the app never inside the daemon's trust boundary. It does **not** rule
  packaging: an installer that ships and manages the daemon alongside the app may be the right
  first-run answer for a nontechnical user, and an identity decision should not constrain
  onboarding. An earlier revision said "does not bundle it," which read as a distribution ruling
  this document never argued for; packaging is returned to the open list (§8).
- **Sovereign-capable, per dp** — the app must be able to be a full node where that makes sense, not
  only a thin client. But sovereignty is **not one profile**: see §4.


### 2.1 The app must not impersonate its principal (GPT §4)

The first draft asserted two things that **cannot both be the provenance model**: that the app is a
member with its own LCT, and that its first act is *"I hold the sovereign's key and sign as them."*

If the app signs consequential acts with the human's private key, **the harness actor disappears from
the record** — at exactly the point where the deputy/instruction-provenance model this fleet just
adopted says the actor must remain visible. It is the deputy problem, reintroduced by the surface
built to make humans legible.

The composition already falls out of decision 0013:

```
human / root LCT   — principal, identity, beneficiary
  device LCT         — the hardware anchor the person is present through
    app-instance LCT   — the harness/actor sending the governed request
      role occupancy     — the office being exercised (often Sovereign)
        delegation/session — why this harness may act for this principal, in this office, now
```

A consequential record then says all of it, and **no identity disappears**:

```
actor:       app-instance-LCT
principal:   human-root-LCT
via_device:  device-LCT
office:      sovereign-role-LCT
authority:   occupancy / delegation / session-id
```

---

## 3. Identity is the constellation, and fragility is the growth curve

dp: *"identity is the constellation — a device could be lost, damaged, or compromised. if
constellation is only that device (initially likely) then that's an inherent vulnerability. the more
devices the more resilient... initially fragile by reality and grows more robust with adoption/use."*

**This is canon, not a new position.** `web4-standard/core-spec/multi-device-lct-binding.md`:

> *"Web4 treats multi-device presence as a **strength** — identity becomes more robust as it is
> witnessed across more independent anchors."*

The spec's anchor taxonomy already names **Secure Enclave / StrongBox, FIDO2 keys, TPM, and
software-only fallback**, with `"anchor_type": "fido2"` a defined value.

**The bootstrap problem, stated honestly:** a one-device constellation is a single point of failure,
and every user starts there. Any design that treats the one-device case as degraded will lose the
user before they reach the two-device case. §5 is how that inverts.

---

## 4. Presence profiles — and why they are NOT "sovereignty profiles"

Falls out of dp's observation that mobile has no harnesses to govern. **Measured: there are none —**
all eleven plugin directories (`claude-code`, `codex`, `cursor`, `gemini`, `kimi`, `openclaw`,
`reviewer`, plus infrastructure) are desktop. None declares android or ios.

So **presence** decomposes along the §1 split. The earlier draft called these "sovereignty profiles", which reintroduced the capacity-vs-office category error this fleet just spent days separating (GPT §5). `Sovereign` is an **office**, established through occupancy and authority — not a deployment shape:

> **Any profile may be Sovereign-capable; Sovereign itself remains an office.**

| profile | identity half | governance half | typical host |
|---|---|---|---|
| **device** | full — holds a key, co-signs, is an anchor | none | phone today |
| **node** | full | full — daemon, gate hooks, chain | laptop / workstation |
| **mirror** | full | none locally; observes a remote node | tablet, second laptop |

A phone is **a full identity anchor with no governance half**, and that is not a lesser product — it
is the correct shape. On-device models later add a governance half to the same device without
changing its identity half.

> **The app must have continuity across stop/start** (dp). It cannot assume it is running. Identity
> state is durable and reconstructible from the identity vault; anything that only exists while the
> app is open is a bug, not a session.

---

## 5. The wedge: replace the six-digit code with m-of-n single clicks

dp: *"instead of the current mfa/authenticator app dance of typing in codes, replace it with
single-click hestia approval on each device, and authentication becomes m-of-n single clicks. i'd
use it in an instant because the six-digit codes are a pain."*

**This is the adoption thesis, and it should drive the roadmap.** Everyone with a TOTP app hates it;
the constellation is already a better answer to the same problem.

### 5.1 What exists, measured

- **Per-act co-signing exists.** `present` co-signs a verifier-supplied nonce; `cosign-serve` drains
  co-sign requests on a device and signs them; `serve-owner` is the device-side consent to act as a
  factor at all.
- **m-of-n does not exist.** No `threshold`, `quorum`, or `min_devices` anywhere in
  `constellation.rs`. What exists is *tier derivation* — enrolled devices raise a standing assurance
  **level**. "This act needed 2 of your 3 devices" is a different thing and is not implemented.
- **The legacy bridge is not where it needs to be.** The only legacy standard in `core/src` is
  **OID4VCI** (12 references) — verifiable-credential issuance. **WebAuthn/FIDO2 appears in the
  spec, in `docs/ARCHITECTURE.md`, and in zero lines of code.**

### 5.2 The move: present as a passkey

**Hestia does not need the world to adopt Web4 in order to replace an authenticator app. It needs to
speak WebAuthn.**

GitHub, Google, and banks accept a passkey today. None accepts a Web4 verifiable credential. So:

- a hestia device registers as a **WebAuthn authenticator**;
- the relying party sees **one ordinary passkey** and is satisfied;
- **behind it, hestia decides how many devices had to click.** m-of-n becomes *hestia-side policy
  over a credential the world already takes.*

This is `PRD.md` §4.2 (*invisible security*) at product scale: adoption comes from being a better
authenticator, and Web4 arrives underneath without the user ever meeting the word.

### 5.3 Why it also solves the bootstrap fragility

A one-device constellation **can match** ordinary passkey assurance — *conditionally*, and the
condition is falsifiable (GPT §7): **when its key custody, RP binding, user verification and
anti-export properties meet the platform's credential-protection bar.** A software-encrypted key
in an application vault is **not** automatically equivalent to Secure Enclave, StrongBox, TPM or
Windows Hello. The earlier draft claimed automatic parity; that silently overrode Web4's own
software-anchor ceiling for product convenience. Every device added makes it **better than what
anyone else has**. Fragility stops being an objection and becomes the reason to keep going, which is
dp's *"grows more robust with adoption/use"* made into a product loop rather than a hope.

### 5.4 The honest cost

**WebAuthn is a real protocol implementation**, platform-specific across Secure Enclave, StrongBox,
and TPM, and **none of it exists today**. It is the largest single piece of new work this document
implies, and it should not be estimated casually. Legacy credentials are the *transitional* anchor
dp names — they reduce fragility while the constellation is small — but the transitional anchor and
the wedge are the same protocol, which is convenient rather than accidental.


### 5.5 Where m-of-n binds — the load-bearing decision (GPT §6)

*"The relying party sees one passkey; hestia decides how many devices clicked"* is plausible at the
WebAuthn interface and **is not yet a security architecture.** Three materially different systems
hide inside that sentence:

| | shape | what it delivers |
|---|---|---|
| **A** | one device owns the credential key; peers merely **approve** its use | the UX and a valid WebAuthn response — but the quorum is **policy around a single cryptographic point of control**. Compromise that device strongly enough to use its key outside hestia's policy path and the quorum evaporates. |
| **B** | the credential itself is **threshold-controlled**; no single device can produce the assertion | the actual thesis: *more independent anchors ⇒ one compromise is insufficient*. Implies threshold/MPC signing compatible with WebAuthn algorithms and provider APIs. **Substantially harder.** |
| **C** | each device holds its **own** ordinary credential | straightforward platform WebAuthn — but the RP sees several credentials and cannot be given m-of-n unless it participates. **Breaks the universal wedge.** |

**Ruling adopted (GPT's recommendation):**

> **The product wedge is WebAuthn provider compatibility. The target security model is a
> quorum-bound credential operation, such that possession or control of any single device anchor is
> insufficient once policy requires m > 1. A single-key policy wrapper (A) is permitted only as an
> explicitly lower-assurance bootstrap, and must never be described as cryptographic m-of-n.**

This keeps the wedge available now without pretending the hard cryptography already exists — and it
makes the difference between A and B a *stated assurance claim* rather than an implementation detail
nobody wrote down.

**(kimi)** GPT's closing rule belongs in the text, not the review thread: *a declaration that
several devices approved is not stronger identity.* It is the identity-domain twin of the
governance layer's own hard-won law — declared is not alive, attested is not witnessed. Same rule,
two domains; shape A is a declaration, shape B is a witness.

### 5.6 Availability may degrade service; it may not silently degrade assurance (GPT §8)

The fleet's standing principle — *unavailability degrades, it does not block* — **cannot be copied
into authentication unqualified.**

For governance, a degraded act can be witnessed and carry debt. For authentication, silently turning
2-of-3 into 1-of-3 **under the same credential** is the attacker's preferred path: make the other
devices unreachable, then trigger the weaker rule. The relying party still sees the same credential
and cannot know hestia lowered its own bar.

> **Constitutional line: availability may degrade service; it may not silently degrade identity
> assurance.**

When `m` cannot be reached, the permitted responses are: refuse this credential use; enter a separate
recovery ceremony; use a **separately defined** lower-assurance credential whose downgrade is explicit
and witnessed; or invoke a pre-authorised emergency policy with a **distinct** assurance result.
Invisible threshold relaxation on the same high-assurance claim is not among them.

---

## 6. Signing: the chain is disposable, so sign from genesis

dp: *"the current chain is experimental, it can be retired (archived) and replaced at any time.
don't let it be a legacy anchor that stops necessary progress."*

**Taken, and it changes the plan.** Prior analysis treated ~111 000 unsigned entries as a migration
constraint and proposed a `signed_from_position` boundary. That is no longer required:

- **archive the current chain**, replace it, and **sign from entry zero**;
- no era where signed and unsigned coexist and a reader must know which;
- no boundary marker to explain, mis-read, or forget.

**Measured state of *chain* signing, as of `4d4cad6`:** `sign_act` / `verify_witness` have **zero
callers** outside `witness_act.rs`, and `chain.rs` contains **zero occurrences of "signature"** —
there is no column to hold one. The primitive is correct (N marks verify against one digest with
`witnesses` cleared) and entirely unwired.

> **Freshness, `#298` (Sprint A, merged 2026-08-08).** That measurement is about the **witness
> chain**, and it still holds there. It is no longer true of the app: `#298` shipped encrypted
> custody (Argon2id + ChaCha20-Poly1305) and a **triply signed five-field session transcript** —
> principal, harness and device each signing the same domain-separated bytes — with the wire format
> since consolidated into the `hestia-wire` crate (`#300`). So the *reference implementation this
> section calls for exists*; what remains unwired is the chain column that would carry a signature
> onto a witnessed entry. This document stays architectural: read the sections below as the design
> the implementation now instantiates, not as a claim that nothing is built.

> **The app should be the first signer.** It is a new surface with no legacy, its acts are
> consequential (they fill the sovereign role), and it already depends on `ed25519-dalek`. Making the
> app's acts signed from its first release produces the reference implementation the harness gates
> get retrofitted against — rather than retrofitting five gates first and hoping the app matches.

### 6.1 Two signature roles, both named before entry zero **(kimi, restoring GPT cond. 10)**

"The app should be the first signer" names the **actor** signature — who performed the act. GPT's
condition 10 asks for a second, distinct role: the **witness/chain** signature — who attests the
entry's *ordering and inclusion*, and under which policy generation. One signature carrying both
meanings is exactly the ambiguity the fresh chain exists to avoid, and it is expensive to recover
once entries accumulate.

> **Ruling: the new chain's entry format carries both roles from genesis — an actor signature over
> the act, and a witness signature over (position, act digest, policy generation). The witness side
> may begin as a single-daemon signer; what may not happen is a genesis whose format has no place
> for it.**

`witness_act.rs` already holds the correct primitive with zero callers; this is a *format* decision,
and the chain rewrite is the one moment when adding it is free.

### 6.2 Archive means readable by the instruments **(kimi + claude S6 amendment)**

Three days of this fleet's accountability work — the refusal censuses, the stranding audits, the
escalation-drain numbers — key on the current chain via `chain_walk`, and decision 0013 binds
appeals to acts by `deny_hash`. If "archive" means *retained but not queryable*, every pre-archive
`deny_hash` binding dangles and that history gets re-litigated from memory.

> **Ruling: the archived chain must remain queryable by the existing instruments (`chain_walk` and
> the audit tooling) at stable addresses. Archive is a change of writability, not of legibility:
> the old chain stops growing; it does not stop answering.**

---

## 7. First cut: move the operator key out of a plaintext file — **built in `#298`**

> **Status, recorded so this section is not read as pending work.** The increment argued for below
> landed in `#298` on 2026-08-08: the plaintext seed is gone, replaced by an Argon2id-derived,
> ChaCha20-Poly1305 vault with a `LegacyOperatorKey` migration for existing installs. The reasoning
> is kept in full because it is *why* the shape is what it is — and because the measured "before"
> is what makes the change legible to a reader who arrives after it.

dp: *"initially, just providing the sign-in key for the dashboard which would be easier and would
move the key from plaintext file into the identity vault."*

**This is the right first increment, and it is not a stopgap.**

Measured: `operator_auth.rs` is already challenge/response — the operator signs a 32-byte nonce with
their LCT key, which is sound. But `app/src-tauri/src/operator.rs` reads **a plaintext 32-byte
Ed25519 seed from a key file**, the same file the dashboard's one-click login reads. Its own
docstring is careful that the UI *"can never read the key"* — the app is already the better
custodian, and it is still custodying plaintext on disk.

Moving that seed into the identity vault:

- **removes a plaintext private key from disk** — a real security improvement independent of
  everything else in this document;
- makes the app's **first governance act** *"I prove custody of the principal's key, and I sign the
  composed transcript as a distinct actor"* — the app remains the **harness**, never the principal
  (§2.1, §7.1). Custody is not impersonation: the app holds the key and signs *alongside* it as
  itself, so the record names principal, harness and device separately. This is §2's human-harness
  relationship exercised end to end;
- proves app → daemon role occupancy with **one credential and no new protocol**, before the
  dashboard-rendering question is settled at all.

The heavier option — the app embedding a browser to render the daemon-served dashboard — is then
judged on its merits later, rather than being load-bearing now.


### 7.1 The first cut establishes principal + harness, not impersonation (GPT §4)

GPT's amendment makes this increment substantially more valuable than "change where one seed loads
from". The slice should be:

1. the app instance **has or creates its own harness LCT**;
2. the identity vault **proves the human/root LCT** through the protected credential;
3. the daemon **creates an operator session binding both identities**, plus the device anchor and the
   office;
4. subsequent app acts **resolve through that composed session**.

That single vertical slice exercises the identity/governance boundary, signed identity, app-as-harness,
canonical role occupancy, actor/principal provenance, **and** the deputy closure — at once, and it is
still bounded.

---

## 8. What this decides, and what it leaves open

**Decided:**
1. Governance vault and identity vault are separate stores with different scopes and lifetimes.
2. The app is a member with an LCT that fills roles; it is logically separate from the daemon.
   (Packaging/distribution is **not** decided here — open list.)
3. **Sovereign is an office**, occupied and revocable — not a property of a machine. *Presence*
   is the profile (device / node / mirror): what a participant can host, which is a separate axis
   from what authority it holds. §4. (This item previously read *"Sovereignty is a profile"*,
   which reintroduced the exact category error §4 removes; corrected before ratification.)
4. The adoption wedge is WebAuthn, with m-of-n as hestia-side policy above it.
5. The chain is archived and re-created signed, rather than migrated. The new format names **both**
   signature roles from genesis (§6.1), and the archive stays queryable by the existing
   instruments at stable addresses (§6.2).
6. First increment is the operator key into the identity vault — **done, `#298`** (encrypted
   custody + triply signed five-field session; wire format consolidated in `#300`). §7.
7. **(kimi)** Where m-of-n thresholds are authored is a law-vs-setting question, and the fleet's
   own machinery supplies the answer: **assurance *floors* are law** — vault-authored,
   society-visible, appealable — and per-relying-party tuning is policy *within* those floors.
   A threshold that a setting can push below the floor is a day-one implementation hole in §5.6's
   constitutional line; the floor must live where settings cannot reach it.

**Open, and genuinely undecided:**
- **Packaging and distribution** (returned to open by kimi's review, per GPT cond. 8): whether a
  first-run installer ships and manages the daemon alongside the app. §2 rules the *logical*
  separation only; the onboarding trade-off — a nontechnical user's first five minutes versus a
  clean separation story — is a product ruling nobody has made yet.
- **The granularity of m-of-n tuning within the law-authored floors** (per-relying-party,
  per-act-class, or both) — the law/setting boundary itself is decided (item 7); the policy
  surface inside it is not.
- **What happens when m cannot be reached** — travelling with one device, others at home. §5.6 is
  the constraint: service may degrade, **identity assurance may not silently degrade**, so "relax
  the threshold because the user is stuck" is *not* on the menu. The genuinely open question is
  which of the remaining exits to build: **refuse** the act and say so; a **separate recovery
  path** with its own (higher, slower) evidence bar; or a **separately declared lower-assurance
  credential** whose reduced assurance is visible to the relying party at use time. The degraded
  path for *authentication* is exactly where an attacker aims, which is why the choice is
  enumerated rather than left to whatever the implementation does under pressure.
- **Whether the identity vault syncs across the constellation, and how.** It must survive device
  loss, which implies replication; replication implies a sync protocol nobody has specified.
- **Whether a hub can be an identity witness** for recovery — dp raised witnessing across hubs as a
  resilience source, and it is the natural answer to the previous question.
- **Platform key custody** — Secure Enclave / StrongBox / TPM are named in the spec and unimplemented.
  This is where "seamless installation" gets hard.
