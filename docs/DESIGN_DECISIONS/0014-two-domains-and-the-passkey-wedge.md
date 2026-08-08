# 0014 — Two domains, the app as human harness, and the passkey wedge

**Status:** draft for review (dp, 2026-08-08). Review order: GPT → kimi → fleet forum. **Not ratified.**
**Builds on:** decision 0013 (an appeal binds to the act), the signature premise, `PRD_APP.md` (#296).
**Supersedes in `PRD_APP.md`:** §2 assumed the app sits on a daemon. It does not, and should not.

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
- **The app is separate from the daemon and does not bundle it.** Measured: `src-tauri` does not
  depend on `hestia` core, `daemon.rs` is 112 lines of `reqwest`, and `lib.rs:39` hardcodes
  `http://127.0.0.1:7711`. It is already a client; it should become a *member* rather than a viewer.
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

**Measured state of signing, unchanged as of `4d4cad6`:** `sign_act` / `verify_witness` have **zero
callers** outside `witness_act.rs`, and `chain.rs` contains **zero occurrences of "signature"** —
there is no column to hold one. The primitive is correct (N marks verify against one digest with
`witnesses` cleared) and entirely unwired.

> **The app should be the first signer.** It is a new surface with no legacy, its acts are
> consequential (they fill the sovereign role), and it already depends on `ed25519-dalek`. Making the
> app's acts signed from its first release produces the reference implementation the harness gates
> get retrofitted against — rather than retrofitting five gates first and hoping the app matches.

---

## 7. First cut: move the operator key out of a plaintext file

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
- makes the app's **first governance act** *"I hold the sovereign's key and I sign as them"*, which
  is §2's human-harness relationship exercised end to end;
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
2. The app is a member with an LCT that fills roles; it does not bundle the daemon.
3. Sovereignty is a profile (device / node / mirror), not a boolean.
4. The adoption wedge is WebAuthn, with m-of-n as hestia-side policy above it.
5. The chain is archived and re-created signed, rather than migrated.
6. First increment is the operator key into the identity vault.

**Open, and genuinely undecided:**
- **Where the m-of-n threshold is authored.** Per-relying-party? Per-act-class? Owner-set globally?
  This is policy authorship and the answer determines whether it is a setting or a law.
- **What happens when m cannot be reached** — travelling with one device, others at home. The
  availability-not-blocker principle says degrade rather than lock out, but the degraded path for
  *authentication* is exactly where an attacker aims.
- **Whether the identity vault syncs across the constellation, and how.** It must survive device
  loss, which implies replication; replication implies a sync protocol nobody has specified.
- **Whether a hub can be an identity witness** for recovery — dp raised witnessing across hubs as a
  resilience source, and it is the natural answer to the previous question.
- **Platform key custody** — Secure Enclave / StrongBox / TPM are named in the spec and unimplemented.
  This is where "seamless installation" gets hard.
