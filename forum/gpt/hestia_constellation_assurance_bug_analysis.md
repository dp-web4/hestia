# Hestia Security Bug Analysis and Fix Recommendation

**Title:** Constellation attestations are self-authenticating, allowing forged multi-device and hardware-backed assurance  
**Repositories reviewed:** `dp-web4/hestia`, with relying-party comparison against `dp-web4/web4`  
**Hestia commit reviewed:** `1d9d2db3ce2d1db31a96d77065e58e90e63565a2`  
**Web4 commit reviewed:** `bc289fb65102af1628528f5db8c9414a75dd6e6f`  
**Primary Hestia file:** `core/src/constellation.rs`  
**Primary Web4 file:** `hub/hub-lib/src/constellation.rs`  
**Severity:** High as a latent security defect; Critical once an assurance tier authorizes higher-impact actions or data access  
**Recommended disposition:** Block use of `MultiDevice` and `HardwareBacked` as authorization evidence until the protocol is corrected

---

## Executive summary

The constellation-attestation design intends to prove that a person controls multiple previously associated devices, and optionally that at least one participating device is hardware-backed.

The current wire object does not prove that.

A `ConstellationAttestation` carries:

- the claimed owner LCT;
- the claimed owner public key;
- the claimed device roster;
- each device's claimed public key;
- each device's claimed device type, including `Hardware`;
- signatures made by those supplied keys.

Hestia's local verifier validates the signatures against the keys carried in the same untrusted object. It does not resolve the owner key, device key, enrollment status, or device type from independently trusted state. It also counts duplicate signature entries as distinct devices.

The Web4 hub verifier improves two parts of this:

- it requires the owner key to equal the member key already pinned by the hub;
- it deduplicates device signatures by `lct_id`.

However, it still verifies device signatures against public keys supplied in the attestation and derives `HardwareBacked` from a `device_type: Hardware` value supplied in the same attestation. An actor who controls the legitimate owner key can generate arbitrary new keypairs, assign them arbitrary device IDs and types, sign the challenge, and obtain an inflated assurance tier without controlling any previously enrolled second device or any hardware-backed key.

This is not a cryptographic primitive failure. The signatures work. The defect is a trust-origin error: untrusted claims are being treated as authoritative enrollment facts.

The secure invariant must be:

> An attestation proves current possession of keys whose association, status, type, and hardware properties were established before the challenge and are resolved from authoritative state independent of the presented attestation.

A Hestia-only patch can prevent unsafe local verification and produce a safer wire form, but the network property also requires the Web4 hub verifier to resolve device facts from an authoritative constellation registry or signed enrollment records. The presenter cannot be the sole source of both the claim and the evidence used to validate that claim.

---

## Affected code

### Hestia producer and local verifier

`core/src/constellation.rs`

Relevant regions at the reviewed commit:

- `ConstellationAttestation` wire shape: approximately lines 64-99
- signing payload: approximately lines 101-120
- attestation creation: approximately lines 122-169
- attestation verification: approximately lines 171-226
- tests: approximately lines 374-518

The unsafe verification pattern is effectively:

```rust
for ds in &self.device_signatures {
    if !self.member_lcts.contains(&ds.lct_id) {
        continue;
    }

    let pk = pubkey_from_hex(&ds.pubkey_hex)?;
    let sig = sig_from_hex(&ds.signature)?;

    if pk.verify(&payload, &sig).is_ok() {
        verified.push(ds);
    }
}
```

The verifier accepts the key and device classification from `ds`, the untrusted evidence object it is evaluating.

### Web4 relying-party verifier

`hub/hub-lib/src/constellation.rs`

The hub correctly checks the presented owner key against the member's pinned key and deduplicates device IDs. It still performs the device verification against `ds.pubkey_hex` and derives hardware assurance from `ds.device_type`.

That means the hub authenticates the owner, but it does not authenticate the constellation.

---

## Security properties the implementation claims to provide

The module documentation describes the mechanism as challenge-response MFA:

- the owner signs the roster and challenge;
- reachable devices co-sign the same payload;
- two or more device signatures produce `MultiDevice`;
- a hardware device signature produces `HardwareBacked`;
- the relying party derives the tier rather than trusting `claimed_assurance`.

Recomputing the tier is necessary, but insufficient. The inputs used to recompute it must themselves be trusted.

The present code proves only:

1. the presenter knows the private key corresponding to the presented owner public key;
2. the presenter knows private keys corresponding to the presented device public keys;
3. those keys signed a payload containing the presented owner ID, roster, nonce, and timestamp.

It does **not** prove:

1. that the owner public key belongs to the claimed owner, in Hestia's standalone verifier;
2. that a device key was enrolled before the challenge;
3. that a device belongs to the owner;
4. that two signatures came from two distinct, independently enrolled devices;
5. that a device classified as `Hardware` has any hardware-bound key;
6. that the roster is the relying party's authoritative or previously committed roster.

---

## Exploit scenarios

## 1. Forged hardware-backed assurance

### Preconditions

The attacker controls the legitimate owner/member signing key, or is the legitimate owner attempting to inflate assurance.

No hardware device is required.

### Steps

1. Receive a fresh hub challenge.
2. Generate a normal software Ed25519 keypair.
3. Invent a device UUID.
4. Add that UUID to `member_lcts`.
5. Construct a `DeviceSignature` containing:
   - the invented UUID;
   - `device_type: Hardware`;
   - the generated software public key;
   - a valid signature from the software private key.
6. Sign the full payload with the legitimate owner key.
7. Present the attestation.

### Current result

- Hestia local verification accepts the device signature against the supplied software public key.
- Web4 hub verification also accepts the device signature against the supplied software public key.
- Both derive `HardwareBacked` from the supplied enum value.

### Security impact

Any policy that treats `HardwareBacked` as stronger evidence can be bypassed with a software-generated key and a string label.

This is especially important for patent and product claims. The implementation currently demonstrates a **claimed hardware classification**, not verified hardware-bound possession.

---

## 2. Forged multi-device assurance with newly generated keys

### Preconditions

The attacker controls the legitimate owner/member signing key.

Only one actual device is required.

### Steps

1. Receive a fresh challenge.
2. Generate two software keypairs on the same machine.
3. Invent two device UUIDs.
4. Put both UUIDs in the roster.
5. Add two signatures made by the two generated keys.
6. Sign the roster with the owner key.
7. Present the attestation.

### Current result

The hub sees two distinct `lct_id` values with valid signatures and derives `MultiDevice`.

### Security impact

The result proves control of two keys generated during the challenge, not control of two previously enrolled devices or factors.

If `MultiDevice` is intended as recovery protection, high-risk approval, anti-account-takeover evidence, or trust elevation, the assurance is illusory.

---

## 3. Duplicate-signature inflation in Hestia's local verifier

### Preconditions

The presenter has one device key.

### Steps

1. Create one valid `DeviceSignature`.
2. Duplicate the same structure in `device_signatures`.
3. Present the attestation to Hestia's local `verify()` method.

### Current result

Hestia pushes both entries into a `Vec` and checks `verified.len() >= 2`, yielding `MultiDevice`.

The Web4 hub verifier has already corrected this particular defect with a map keyed by device LCT, but Hestia's local verifier remains vulnerable.

### Security impact

Any future Hestia code path that relies on the local verifier can obtain multi-device assurance from one signature repeated twice.

---

## 4. Foreign-owner self-authentication in Hestia's local verifier

### Preconditions

None beyond ability to generate a keypair.

### Steps

1. Invent an `owner_lct_id`.
2. Generate an owner keypair.
3. place its public key in `owner_pubkey_hex`;
4. sign the payload with that key.
5. call `verify()` with the expected nonce.

### Current result

Hestia verifies the signature against the public key supplied in the same object. The method accepts it without receiving an expected owner LCT or trusted owner key.

### Security impact

The method proves internal self-consistency, not identity. It is unsafe as a general authentication API.

The current Web4 hub path avoids this specific failure by comparing the owner key to the member key already pinned by the hub. Hestia should nevertheless remove or rename the unsafe API so it cannot later be used as an authentication verifier.

---

## 5. Future-dated attestations are accepted

Both implementations reject an attestation only when:

```rust
now - issued_at > max_age
```

An `issued_at` timestamp significantly in the future produces a negative duration and passes the test.

The fresh nonce limits straightforward replay in the hub flow, so this is not the primary vulnerability. It is still a correctness defect and can become security-relevant in alternate transports, cached attestations, or future refactoring.

The verifier should enforce both:

```text
issued_at >= now - max_age
issued_at <= now + allowed_clock_skew
```

---

## Root cause

The protocol conflates three different statements:

1. **Current possession:** a key signed this fresh challenge.
2. **Enrollment:** the key was previously accepted as belonging to this constellation.
3. **Assurance classification:** the key is a separate device, and possibly hardware-backed.

A challenge signature can prove statement 1.

It cannot prove statements 2 or 3 when the public key, device identity, device class, and roster all come from the claimant in the same message.

Owner-signing the roster does not solve the problem if the assurance is intended to protect against owner-key compromise. An attacker with the owner key can sign a newly fabricated roster. It also does not establish hardware properties.

The protocol needs an independently committed enrollment layer.

---

## Severity and current exposure

### Severity

**High**, becoming **Critical** when either tier controls consequential authorization.

Examples that would make the defect Critical:

- exposing more sensitive vault data to a `MultiDevice` session;
- permitting irreversible actions only at `MultiDevice`;
- allowing account or identity recovery at `MultiDevice`;
- treating `HardwareBacked` as equivalent to TPM, Secure Enclave, FIDO2, or other non-exportable-key evidence;
- raising trust ceilings or bypassing operator review based on the tier.

### Current exposure

At the reviewed commits:

- Hestia's standalone verifier appears to be used only in its module tests.
- The Web4 hub contains the relying-party gate and tier-binding implementation.
- Indexed search did not reveal broad downstream authorization consumption of the tier.

This makes the defect primarily latent today, which is the best time to change the wire contract. It should be fixed before other code begins depending on the current v1 semantics.

---

# Recommended fix

## Security invariant

A relying party must calculate assurance exclusively from:

- an authenticated owner identity already associated with the transport or session;
- a roster committed before the challenge;
- one unique signature per active enrolled device;
- a device public key resolved from authoritative state, not from the attestation;
- a device class resolved from authoritative state, not from the attestation;
- verified hardware evidence when granting a hardware tier.

The presented attestation may identify a device and provide a challenge signature. It must not be authoritative for that device's key or classification.

---

## Recommended protocol v2

### Wire shape

Remove `pubkey_hex` and `device_type` from each device signature:

```rust
pub struct DeviceSignatureV2 {
    pub lct_id: Uuid,
    pub signature: String,
}
```

Add a roster commitment:

```rust
pub struct ConstellationAttestationV2 {
    pub version: u16,                 // 2
    pub owner_lct_id: Uuid,
    pub roster_version: u64,
    pub roster_hash: String,
    pub challenge_nonce: String,
    pub issued_at: DateTime<Utc>,
    pub owner_signature: String,
    pub device_signatures: Vec<DeviceSignatureV2>,
}
```

The signing payload should bind:

```text
protocol version
owner LCT
relying-party or hub LCT
pair/session ID
challenge nonce
issued_at
roster version
roster hash
ordered list of signing device IDs
purpose / requested assurance context
```

Binding the relying party, pair ID, and purpose prevents a valid response for one hub or action context from being transplanted into another.

### Authoritative device record

Each enrolled device should have an authoritative record such as:

```rust
pub struct EnrolledDevice {
    pub owner_lct_id: Uuid,
    pub device_lct_id: Uuid,
    pub public_key: PublicKey,
    pub status: DeviceStatus,
    pub device_class: DeviceClass,
    pub enrolled_at: DateTime<Utc>,
    pub enrollment_version: u64,
    pub hardware_evidence: Option<VerifiedHardwareEvidence>,
}
```

The record must be:

- stored in the Hestia vault as the local source;
- published or committed in a form the hub can independently resolve;
- signed by the owner or enrollment authority;
- versioned and revocable;
- established before the attestation challenge.

A content hash of the canonical roster should be stable and cross-implementation-testable.

### Hardware-backed classification

`DeviceType::Hardware` must not itself grant hardware assurance.

`HardwareBacked` should require a verified record containing evidence such as:

- TPM EK/AK trust-chain validation plus proof of possession;
- Secure Enclave or platform-attestation evidence;
- FIDO2 authenticator attestation with an accepted trust policy;
- another explicitly supported hardware root.

The hardware evidence should bind the challenge-signing key or certify a key that signs the challenge. Merely recording that a device is named "YubiKey" or typed `Hardware` is insufficient.

---

## Hestia implementation changes

## 1. Deprecate the current authentication-looking verifier

The existing method:

```rust
pub fn verify(
    &self,
    expected_nonce: &str,
    max_age: chrono::Duration,
) -> anyhow::Result<AssuranceLevel>
```

should not remain a public authentication API.

Preferred options:

- remove it;
- make it test-only;
- rename it to `verify_internal_consistency()` and clearly document that it establishes no identity or assurance;
- replace it with a verifier that accepts trusted external state.

A safe local signature could be:

```rust
pub fn verify_against_store(
    &self,
    expected_owner_lct: Uuid,
    expected_owner_pubkey: &PublicKey,
    expected_nonce: &str,
    expected_relying_party: Uuid,
    expected_pair_id: Uuid,
    store: &ConstellationStore,
    max_age: chrono::Duration,
    allowed_future_skew: chrono::Duration,
    now: DateTime<Utc>,
) -> anyhow::Result<AssuranceLevel>
```

For network verification, use a resolver abstraction rather than passing Hestia's private store directly.

## 2. Resolve device facts from the store

For each presented device ID:

1. reject duplicate roster IDs;
2. reject duplicate signature IDs or deduplicate and reject conflicting duplicates;
3. find the device in `ConstellationStore`;
4. require active/enrolled status;
5. parse the public key from the stored member record;
6. verify the signature against that stored key;
7. derive device class from the stored record;
8. derive hardware status only from validated hardware evidence.

Do not read `pubkey_hex` or `device_type` from the presented attestation for authorization.

## 3. Canonicalize the roster

`ConstellationStore::add_device()` currently generates IDs and pushes records into a vector. Before computing a roster hash:

- require unique device LCT IDs;
- require unique active public keys unless intentional shared-key behavior is explicitly supported;
- sort by canonical device LCT bytes;
- serialize with a pinned canonical encoding;
- include status and enrollment version;
- exclude mutable presentation fields such as `last_seen` and `reachable`.

## 4. Add explicit device status

The current member shape has `reachable` but no enrollment/revocation status. Reachability is transient and should not determine whether a key remains authorized.

Add something like:

```rust
pub enum DeviceStatus {
    Active,
    Suspended,
    Revoked,
}
```

A revoked device must never contribute assurance even if it can still sign.

## 5. Tighten assurance semantics

The current `SingleDevice` result also covers zero verified device signatures.

That is misleading. Consider:

```rust
pub enum AssuranceLevel {
    OwnerOnly,
    SingleDevice,
    MultiDevice,
    HardwareBacked,
}
```

Suggested definitions:

- `OwnerOnly`: owner signature valid, zero enrolled device co-signatures;
- `SingleDevice`: one distinct active enrolled device co-signed;
- `MultiDevice`: at least two distinct active enrolled devices co-signed;
- `HardwareBacked`: at least one verified signer is backed by accepted hardware evidence; optionally combine with device count as orthogonal fields rather than a single ordered enum.

A better long-term result is a structured assurance object:

```rust
pub struct Assurance {
    pub owner_authenticated: bool,
    pub distinct_devices: usize,
    pub hardware_bound_devices: usize,
    pub roster_version: u64,
}
```

Policy can then require `distinct_devices >= 2` and `hardware_bound_devices >= 1` independently. A single enum collapses two different axes.

## 6. Reject future timestamps

Add an explicit future-skew check:

```rust
let age = now.signed_duration_since(self.issued_at);

if age > max_age {
    anyhow::bail!("attestation expired");
}

if age < -allowed_future_skew {
    anyhow::bail!("attestation issued too far in the future");
}
```

## 7. Bind the context more fully

The current payload binds owner, nonce, timestamp, and roster IDs. Add:

- protocol version;
- hub/relying-party LCT;
- pair ID or session ID;
- requested action or assurance purpose;
- roster version/hash.

This makes the proof specific to the verifier and context in which it is used.

---

## Web4 hub changes required for the complete fix

A Hestia patch alone can stop Hestia from producing obviously malformed attestations, but it cannot make a relying party secure. A malicious or modified Hestia client can always send arbitrary JSON.

The hub verifier must therefore change too.

Recommended hub API:

```rust
pub trait ConstellationResolver {
    fn owner_key(&self, owner_lct: Uuid) -> Option<PublicKey>;

    fn active_device(
        &self,
        owner_lct: Uuid,
        device_lct: Uuid,
        roster_version: u64,
    ) -> Option<ResolvedDevice>;

    fn roster_hash(
        &self,
        owner_lct: Uuid,
        roster_version: u64,
    ) -> Option<[u8; 32]>;
}
```

Verification should:

1. require `att.owner_lct_id` to equal the authenticated pair participant;
2. resolve the owner key from the member registry;
3. require the referenced roster version and hash to match committed state;
4. reject duplicate roster IDs;
5. deduplicate signature IDs and reject conflicting duplicates;
6. resolve each device's key and class;
7. verify the signature against the resolved key;
8. count only distinct active devices;
9. grant hardware assurance only from resolved, validated hardware evidence;
10. burn the nonce on every presentation attempt, as the hub already does;
11. bind the result to the pair with a short validity window, as the hub already does.

---

## Safe compatibility strategy

The v1 format is already present in both repositories. A fail-safe migration is preferable to silently changing its meaning.

Recommended behavior:

### v1 attestations

- continue parsing for compatibility;
- verify the owner as currently done;
- treat all device public keys and types as self-asserted;
- cap the result at `OwnerOnly` or, at most, a low-confidence `SingleDeviceSelfAsserted`;
- never produce `MultiDevice` or `HardwareBacked`;
- include a machine-readable reason such as `legacy_self_asserted_roster`.

### v2 attestations

- require a committed roster;
- resolve device facts independently;
- permit higher tiers only after all checks pass.

Do not infer v2 security from the mere presence of a new field. Include an explicit version and reject unknown versions fail-closed.

---

# Minimal emergency patch

If the full registry protocol cannot be implemented immediately, apply these changes now:

1. Change Hestia's local `verified` collection from `Vec` to `HashMap<Uuid, ...>`.
2. Reject conflicting duplicate entries.
3. Require expected owner LCT and expected owner public key as verifier arguments.
4. Reject future-dated attestations.
5. Rename current higher tiers to indicate self-assertion, or cap the result at the lowest tier.
6. Refuse to return `HardwareBacked` based only on `DeviceType::Hardware`.
7. Add a warning in both repositories that v1 proves key possession only, not prior enrollment or hardware binding.

This does not establish real multi-device assurance, but it prevents the current API from overstating what was proven.

---

# Suggested patch shape

The following is intentionally architectural rather than a drop-in diff.

```rust
#[derive(Clone, Debug)]
pub struct TrustedDevice {
    pub lct_id: Uuid,
    pub public_key: PublicKey,
    pub active: bool,
    pub hardware_verified: bool,
}

pub trait TrustedConstellation {
    fn expected_owner_key(&self, owner_lct: Uuid) -> Option<PublicKey>;
    fn roster_hash(&self, owner_lct: Uuid, version: u64) -> Option<[u8; 32]>;
    fn device(
        &self,
        owner_lct: Uuid,
        version: u64,
        device_lct: Uuid,
    ) -> Option<TrustedDevice>;
}

pub fn verify_v2<R: TrustedConstellation>(
    &self,
    expected_owner_lct: Uuid,
    expected_nonce: &str,
    expected_pair_id: Uuid,
    expected_relying_party: Uuid,
    resolver: &R,
    max_age: chrono::Duration,
    future_skew: chrono::Duration,
    now: DateTime<Utc>,
) -> anyhow::Result<Assurance> {
    if self.owner_lct_id != expected_owner_lct {
        anyhow::bail!("owner does not match authenticated participant");
    }

    if self.challenge_nonce != expected_nonce {
        anyhow::bail!("nonce mismatch");
    }

    let age = now.signed_duration_since(self.issued_at);
    if age > max_age {
        anyhow::bail!("attestation expired");
    }
    if age < -future_skew {
        anyhow::bail!("attestation issued in the future");
    }

    let owner_key = resolver
        .expected_owner_key(self.owner_lct_id)
        .ok_or_else(|| anyhow::anyhow!("owner key unresolved"))?;

    let expected_roster_hash = resolver
        .roster_hash(self.owner_lct_id, self.roster_version)
        .ok_or_else(|| anyhow::anyhow!("roster unresolved"))?;

    if expected_roster_hash != self.roster_hash {
        anyhow::bail!("roster commitment mismatch");
    }

    let payload = self.signing_payload_v2(
        expected_pair_id,
        expected_relying_party,
    );

    owner_key.verify(&payload, &self.owner_signature)?;

    let mut seen = std::collections::HashSet::new();
    let mut distinct_devices = 0usize;
    let mut hardware_devices = 0usize;

    for presented in &self.device_signatures {
        if !seen.insert(presented.lct_id) {
            anyhow::bail!("duplicate device signature");
        }

        let trusted = resolver
            .device(
                self.owner_lct_id,
                self.roster_version,
                presented.lct_id,
            )
            .ok_or_else(|| anyhow::anyhow!("device not enrolled"))?;

        if !trusted.active {
            anyhow::bail!("device not active");
        }

        trusted.public_key.verify(&payload, &presented.signature)?;
        distinct_devices += 1;

        if trusted.hardware_verified {
            hardware_devices += 1;
        }
    }

    Ok(Assurance {
        owner_authenticated: true,
        distinct_devices,
        hardware_bound_devices: hardware_devices,
        roster_version: self.roster_version,
    })
}
```

---

# Required regression tests

## Tests that must fail on current code and pass after the fix

### Hestia

1. **Duplicate device entry does not create multi-device assurance**
   - include the same `lct_id` and signature twice;
   - expected: reject or count once.

2. **Self-supplied foreign owner key is rejected**
   - expected owner LCT/key are trusted inputs;
   - attestation contains another key;
   - expected: reject.

3. **Invented device ID is rejected**
   - owner signs a roster containing an unenrolled device;
   - expected: reject.

4. **Wrong key for enrolled device is rejected**
   - device ID exists but signature verifies only under a supplied attacker key;
   - expected: reject against stored key.

5. **Claimed hardware label without hardware evidence is rejected**
   - ordinary software key is presented as hardware;
   - expected: no hardware assurance.

6. **Revoked device does not count**
   - valid signature from a revoked device;
   - expected: reject or ignore, never count.

7. **Future timestamp is rejected**
   - `issued_at` exceeds allowed skew;
   - expected: reject.

8. **Roster ordering is canonical**
   - same roster in different vector order;
   - expected: same canonical roster hash, or noncanonical input rejected.

9. **Roster version mismatch is rejected**
   - signature binds old or fabricated roster version;
   - expected: reject.

10. **Zero device signatures are not called single-device MFA**
    - expected: `OwnerOnly` or equivalent.

### Cross-repository vectors

11. **Hestia and Web4 produce identical v2 signing payload bytes**
12. **Hestia and Web4 produce identical canonical roster hashes**
13. **Unknown protocol versions fail closed**
14. **Device-signature duplicates produce identical failure behavior**
15. **Hardware evidence maps to assurance identically**

---

# Proof-of-concept tests for the existing vulnerability

These tests are useful to add first so the team can see the failure before replacing the behavior.

## Forged hardware label

```rust
#[test]
fn current_verifier_accepts_software_key_labeled_hardware() {
    let owner = KeyPair::generate();
    let fake_device = KeyPair::generate();
    let owner_lct = Uuid::new_v4();
    let fake_device_lct = Uuid::new_v4();
    let issued_at = Utc::now();
    let nonce = "fresh-hub-challenge";

    let roster = vec![fake_device_lct];
    let payload = ConstellationAttestation::signing_payload(
        owner_lct,
        &roster,
        nonce,
        &issued_at,
    );

    let att = ConstellationAttestation {
        owner_lct_id: owner_lct,
        owner_pubkey_hex: owner.verifying_key().to_hex(),
        member_lcts: roster,
        challenge_nonce: nonce.to_string(),
        issued_at,
        claimed_assurance: AssuranceLevel::SingleDevice,
        owner_signature: owner.sign(&payload).to_hex(),
        device_signatures: vec![DeviceSignature {
            lct_id: fake_device_lct,
            device_type: DeviceType::Hardware,
            pubkey_hex: fake_device.verifying_key().to_hex(),
            signature: fake_device.sign(&payload).to_hex(),
        }],
    };

    // This currently succeeds and returns HardwareBacked.
    assert_eq!(
        att.verify(nonce, chrono::Duration::minutes(5)).unwrap(),
        AssuranceLevel::HardwareBacked,
    );
}
```

## Duplicate signature inflation

```rust
#[test]
fn current_hestia_verifier_counts_one_device_twice() {
    let owner = KeyPair::generate();
    let device = KeyPair::generate();
    let owner_lct = Uuid::new_v4();
    let device_lct = Uuid::new_v4();
    let issued_at = Utc::now();
    let nonce = "fresh-hub-challenge";
    let roster = vec![device_lct];

    let payload = ConstellationAttestation::signing_payload(
        owner_lct,
        &roster,
        nonce,
        &issued_at,
    );

    let ds = DeviceSignature {
        lct_id: device_lct,
        device_type: DeviceType::Desktop,
        pubkey_hex: device.verifying_key().to_hex(),
        signature: device.sign(&payload).to_hex(),
    };

    let att = ConstellationAttestation {
        owner_lct_id: owner_lct,
        owner_pubkey_hex: owner.verifying_key().to_hex(),
        member_lcts: roster,
        challenge_nonce: nonce.to_string(),
        issued_at,
        claimed_assurance: AssuranceLevel::SingleDevice,
        owner_signature: owner.sign(&payload).to_hex(),
        device_signatures: vec![ds.clone(), ds],
    };

    // This currently succeeds and returns MultiDevice in Hestia.
    assert_eq!(
        att.verify(nonce, chrono::Duration::minutes(5)).unwrap(),
        AssuranceLevel::MultiDevice,
    );
}
```

The first test identifies the protocol defect. The second identifies the additional Hestia implementation defect.

---

# Acceptance criteria

The fix is complete only when all of the following are true:

- [ ] The verifier receives or resolves an expected owner identity independently of the attestation.
- [ ] `owner_lct_id` is bound to the authenticated channel participant.
- [ ] The device roster was committed before the challenge.
- [ ] The attestation binds a roster version and content hash.
- [ ] Device public keys are resolved from authoritative state.
- [ ] Device enrollment status is resolved from authoritative state.
- [ ] Device class is resolved from authoritative state.
- [ ] Hardware assurance requires validated hardware evidence bound to the signing key.
- [ ] Duplicate device IDs cannot increase assurance.
- [ ] Conflicting duplicate entries fail closed.
- [ ] Revoked or suspended devices cannot contribute.
- [ ] Future-dated attestations beyond permitted clock skew fail.
- [ ] Zero device signatures are not represented as device MFA.
- [ ] Hestia and Web4 share cross-language/cross-repository test vectors.
- [ ] Legacy v1 attestations cannot produce a high assurance tier.
- [ ] No authorization policy consumes `MultiDevice` or `HardwareBacked` before these criteria are met.

---

# Suggested GitHub issue text

## Title

**Security: constellation attestation trusts claimant-supplied device keys/types, allowing MFA and hardware-tier inflation**

## Body

`ConstellationAttestation` currently carries the owner key, device roster, device public keys, and device types inside the object being verified. Hestia verifies signatures against those supplied keys and counts duplicate entries; the Web4 hub pins the owner key and deduplicates IDs, but still trusts supplied device keys and `device_type`.

A holder of the owner key can therefore generate arbitrary software keys during a challenge, label one `Hardware`, and obtain `HardwareBacked`, or present two generated keys and obtain `MultiDevice`, without controlling previously enrolled independent devices.

This is a trust-origin defect, not a signature defect. The relying party must resolve device key, active enrollment, device class, and hardware evidence from state committed before the challenge.

Immediate action:

1. prevent v1 from producing `MultiDevice` or `HardwareBacked`;
2. deduplicate/reject duplicate device IDs in Hestia;
3. require trusted owner identity in the local verifier;
4. reject future timestamps;
5. design v2 with roster version/hash and resolver-backed device verification;
6. remove device public key and type from the authoritative wire evidence;
7. require verified hardware binding for hardware assurance.

See attached analysis for exploit examples, protocol v2 recommendation, regression tests, and acceptance criteria.

---

## Bottom line

The current mechanism is a valid fresh multi-key signature bundle. It is not yet a valid multi-device or hardware-backed identity proof.

The distinction is fixable, and the architecture already has the right conceptual pieces: LCT identities, pinned keys, signed records, registries, challenge nonces, and fail-closed verification. The missing element is temporal and authoritative separation between:

- device enrollment facts established before the challenge; and
- fresh possession signatures supplied in response to the challenge.

Once that separation is enforced, the constellation mechanism becomes a strong and defensible assurance primitive.
