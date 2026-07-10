# Device & Vault Lifecycle — spec draft

**Status:** DRAFT (v0.1, 2026-07-10) · **Lane:** HUB · **Thread:** `hestia-device-vault-model`
**Answers:** `shared-context/hestia/open-questions-vault-constellation-device-mgmt-2026-07-10.md`
**Positions ratified in:** `shared-context/hestia/plan-device-vault-lifecycle-spec-2026-07-10.md`

The principle throughout is the one already applied to orchestrator scope and the egress boundary:
**trust and authority are specific and witnessed, not global and assumed.** This spec applies it one
layer down — to devices, their vaults, and the keys that sign external acts.

Two open decisions are marked `[DECISION: dp]` and block finalization; everything else is ready to
implement.

---

## 1. Assurance model

### 1.1 The tier ladder

`AssuranceLevel` (constellation.rs) gains a bottom tier and becomes the single scale every signing
path maps onto:

| Tier | Meaning | Today's paths that land here |
|---|---|---|
| `Operational` | A raw operational key signed; **no vault was opened, no live presence shown** | `MemberKeySource::ChannelKeyFile` (mesh watchers) |
| `SingleDevice` | One device's vault identity signed; vault was open (incl. auto-unlock) | `MemberKeySource::VaultIdentity`, single-member constellation |
| `MultiDevice` | 2+ constellation devices co-signed a challenge at act time | verified `ConstellationAttestation` with 2+ device sigs |
| `HardwareBacked` | A `DeviceType::Hardware` member co-signed (TPM / Hardbound tier) | verified attestation incl. a hardware device |

Rules:
- The verifier **derives** the tier from verified signatures, never from a claim (already the
  invariant in `ConstellationAttestation::verify`; it now covers `Operational` too).
- An auto-unlocked vault (passphrase file, §2.1) caps at `SingleDevice`. Convenience unlock is a
  legitimate consumer tier, but it can never masquerade as multi-device presence.
- `Operational` is **explicit, never inferred as a default**. `hestia hub set-member-key
  --channel-key` remains the only way to enter it, and status/CLI output must label the connection's
  tier wherever the key source is shown.

### 1.2 Migration note (enum ordering & rollout order)

`AssuranceLevel` derives `Ord` and callers compare tiers. `Operational` must be inserted as the
**first** variant so the ordering stays semantic (`Operational < SingleDevice < MultiDevice <
HardwareBacked`). Serialized snake_case names are unaffected; any stored proofs/attestations
deserialize unchanged.

The enum lives in **two crates**: hestia `core/src/constellation.rs` and its mirror
`web4/hub/hub-lib/src/constellation.rs:39` (also derived `Ord`, also snake_case on the wire).
Insert the variant first in **both**, or every existing `<`/`>=` tier comparison silently inverts
for it on the side that lags.

**Rollout order: hubs before signers.** "Deserialize unchanged" holds for data at rest, not for
the wire: an old hub-lib receiving `operational` in a live envelope fails deserialization of the
whole envelope. Ship the enum to hub-lib/hub-daemon first; only after hubs are updated may hestia
emit the new tier. (Per CBP's sanity check on the thread, 2026-07-10.)

---

## 2. Vault lifecycle (per device)

### 2.1 Posture: one vault, one passphrase, per device

Each device keeps its own `~/.hestia/` vault and passphrase. **Key material is never shared or
derived across devices** — a compromised device exposes only its own vault, and revocation (§3.2)
is meaningful because the revoked key was never anyone else's key. Devices relate through
constellation cross-attestation (§3), not shared secrets. The vault key is not a constellation
factor; the vault is where a device's identity keys and constellation store live at rest
(`ConstellationStore::load/save` already vault-encrypts `constellation.json`).

The passphrase-file auto-unlock (`HESTIA_PASSPHRASE` from mode-600 `~/.hestia/.passphrase` in the
systemd unit) is retained as the **consumer tier**, with its cost now priced into the assurance
model: everything a daemon-auto-unlocked vault signs is at most `SingleDevice` (§1.1).

### 2.2 Rotation — `hestia vault rotate`

New CLI verb. Requirements:
- Prompts for (or reads) the current passphrase, takes the new one interactively or via
  `HESTIA_PASSPHRASE_NEW`.
- Re-keys **without downtime**: items are re-encrypted under the new Argon2id-derived key
  item-by-item; the daemon holds both keys in memory during the pass and swaps atomically at the
  end (per-item independent locking makes this incremental; no big-bang re-encrypt of a monolith).
- Rewrites `~/.hestia/.passphrase` (mode 600) last, after the vault is fully re-keyed, so a crash
  mid-rotation leaves a vault openable by the *old* file.
- Emits a witnessed act (`witness_act`) recording that a rotation happened (not the material).

### 2.3 Recovery

Today, losing the passphrase (+ file) is a hard loss. The spec adds two opt-in paths:
- **Recovery code at init:** `hestia init` offers to print a one-time recovery code (a second
  Argon2id-wrapped copy of the vault key). Declining is a first-class choice and recorded in the
  device's unlock policy (§2.5).
- **Constellation-quorum recovery** (requires §3.3): a `MultiDevice`+ constellation can re-mint a
  device's vault access by quorum co-sign of remaining devices.

`[DECISION: dp]` — is the recovery code acceptable for the consumer tier, or is hard-loss the
intended posture (recovery *only* via constellation quorum)?

### 2.4 Per-item second factor

The vault's per-item independent locking already gives the grain; this adds policy on top: an item
class may be marked `co_sign_required`, meaning reads of it **fail even on an unlocked daemon**
unless accompanied by a live owner co-sign (interactive prompt or a challenge co-signed by another
constellation device). This closes the "vault open = service running" standing-egress surface for
the items that matter, without breaking the consumer tier for everything else.

### 2.5 Per-device unlock policy

Each device carries a small policy document (vault-stored, like the constellation store) — the
device analogue of the per-orchestrator scope policy:

```json
{
  "device_lct": "<uuid>",
  "unlock_mode": "auto_file | interactive | tpm",
  "max_assurance": "single_device",
  "auto_unlock_classes": ["presence", "config"],
  "co_sign_required_classes": ["identity_secrets", "hub_admin"],
  "recovery": "code | quorum | none"
}
```

The daemon enforces it at unlock and at item access. Scope comes from the device's own identity,
not a global preset — the same principle as per-orchestrator policy, one layer down.

---

## 3. Constellation lifecycle ceremonies

The primitives exist (`ConstellationStore`, `ConstellationAttestation`, `witness_act`); this
section specifies the ceremonies that make add/remove **witnessed acts** instead of local mutations.

### 3.1 Enrollment

1. **New device** runs `hestia init` → mints its keypair + LCT locally (keys never leave it).
2. It presents a **pairing offer**: `{lct_id, pubkey_hex, device_type, nonce}` as QR / short code.
3. **Owner device** runs `hestia constellation add <offer>`. This now:
   - constructs an enrollment `Act` (offer digest + roster-after),
   - owner signs it (`sign_act`),
   - challenges the new device to co-sign the same payload (proves key possession, binds the nonce),
   - stores both signatures with the `ConstellationMember` record.
4. Trust in the new LCT derives from the **witnessed add**, not from the add call itself. An add
   without a verifiable co-sign is rejected, not stored-unproven.

### 3.2 Revocation

`hestia constellation remove` becomes a witnessed **revocation record** (owner-signed act naming
the revoked LCT + reason + roster-after), and:
- is **pushed to every `HubConnection`** the constellation is known at; hubs pin the revocation and
  refuse subsequent acts signed by the revoked key,
- propagates to other constellation devices on next liveness contact (they mark the member revoked,
  not merely absent),
- local delete alone is explicitly insufficient for the lost/compromised case.

### 3.3 Recovery (lost owner device)

- `MultiDevice`+: a **quorum of remaining devices** (≥2 co-signs, or the hardware member) signs an
  owner-rotation act; hubs that verify it re-pin the new owner key. The old owner key is
  simultaneously revoked (§3.2).
- Single-device constellations fall back to the §2.3 recovery code, or hard loss if declined.

### 3.4 No retroactivity

Attestations are challenge-bound and timestamped. Add/remove/revoke changes the derivable tier
**only for acts going forward**; an act witnessed at `MultiDevice` keeps that tier even if the
constellation later shrinks. (Verifiers evaluating *old* acts evaluate them against the roster
records in force at act time.)

---

## 4. External acts — the signing-authority table

A constellation presents externally as **one identity (the owner LCT)**. The per-act attestation
names the signing device and carries the derived tier (`DeviceSignature` already supports this).
Key selection (`MemberKeySource`) and delegation reconcile into one table — two axes, one spectrum:

| Signer | Key | Delegation depth | Tier (derived) |
|---|---|---|---|
| Constellation via device vault identity | sealed vault key | 0 (self) | per attestation: `SingleDevice`…`HardwareBacked` |
| Headless watcher via channel key | raw Ed25519 file | 0 (self, operational) | `Operational` (capped) |
| Foreign member (keyless AGY) | none — delegator signs | ≥1 | `min(delegator's tier, Operational)`¹ |

¹ Default cap; a delegation record may carry a higher cap only if the delegation act itself was
witnessed at that tier.

Hubs gate act classes on tier (chapter law): e.g. high-consequence outward acts require
`MultiDevice`+; routine mesh coordination (`referenced_act` notices) remains fine at `Operational`.

`[DECISION: dp]` — which existing act classes (if any) immediately require `MultiDevice`? i.e. is
the CBP mesh watcher's channel-key path grandfathered at `Operational` for everything it does
today, or capped out of some current act?

**CBP's input (sanity check, 2026-07-10):** the watcher's only write is `referenced_act`
coordination notices, all carrying the default `ConsequenceClass::Reversible`
(`web4-core/src/act.rs:125`) — nothing it does today exceeds `Reversible`, so no grandfathering
carve-out is needed. CBP proposes keying the tier floor off the consequence axis that already
exists, rather than per-act-class lists, making the decision structural:

| `ConsequenceClass` | tier floor |
|---|---|
| `Reversible` | `Operational` |
| `Costly` | `SingleDevice` |
| `Irreversible` | `MultiDevice` + council (existing gate, `hub-lib/src/events.rs`) |

The raw channel key is thereby **retired as an unstated workaround** and retained as an explicit,
tier-capped exception — which is all a headless watcher needs.

---

## 5. Implementation order

1. `AssuranceLevel::Operational` in **`web4/hub/hub-lib/src/constellation.rs` first** (hub-track
   counterpart PR; hubs must deserialize the tier before any signer emits it — §1.2), then the
   hestia enum + tier labeling in `hub status` / connection views (small, unblocks 4).
2. Witnessed enrollment + revocation ceremonies (§3.1–3.2) — `constellation.rs` + CLI.
3. Revocation push to `HubConnection`s + hub-side pin (needs a hub-track counterpart PR).
4. Per-device unlock policy doc + enforcement (§2.5), then per-item co-sign classes (§2.4).
5. `vault rotate` (§2.2).
6. Recovery paths (§2.3, §3.3) — **after** the two `[DECISION: dp]` items resolve.
