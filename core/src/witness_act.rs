// Copyright (c) 2026 MetaLINXX Inc.
// SPDX-License-Identifier: AGPL-3.0-or-later

//! # Witnessing web4 acts (the hestia leg of fleet-as-a-society)
//!
//! Hestia already witnesses tool acts into its hash-linked chain. This lets it
//! witness a web4-core [`Act`](web4_core::act::Act) — a handoff, sweep, forum
//! post, or memory write — producing the flat
//! [`WitnessAttestation`](web4_core::r6::WitnessAttestation) that attaches to
//! the act. That turns a handoff from *trusted-on-faith* into
//! *recipient-verifiable* (CBP's "Fleet as a Web4 society", and the hub's
//! `ReferencedAct` witness leg), and records the witnessing in hestia's own
//! auditable chain so the act-attestation and the local audit trail agree.
//!
//! The attestation signs a **digest of the act with its `witnesses` field
//! cleared**, so every witness signs the same bytes regardless of marks already
//! attached — N independent marks on one act all verify against one digest.

use anyhow::{Context, Result};
use chrono::Utc;
use sha2::{Digest, Sha256};
use uuid::Uuid;
use web4_core::act::Act;
use web4_core::crypto::{KeyPair, PublicKey, SignatureBytes};
use web4_core::r6::WitnessAttestation;

use crate::storage::chain::SqliteChainStore;

/// The canonical hash a witness signs: sha256 of the act's canonical JSON with
/// the `witnesses` field cleared (so attaching a mark doesn't invalidate the
/// marks already there).
pub fn act_digest(act: &Act) -> Result<String> {
    let mut bare = act.clone();
    bare.witnesses.clear();
    let json = serde_json::to_vec(&bare).context("serializing act for digest")?;
    let mut h = Sha256::new();
    h.update(&json);
    Ok(hex::encode(h.finalize()))
}

/// Sign an act as a witness — the pure crypto half (no chain side effect).
/// `verdict` is the witness's judgment: `"verified"` or `"disputed"`.
pub fn sign_act(
    act: &Act,
    my: &KeyPair,
    my_lct: Uuid,
    verdict: &str,
) -> Result<WitnessAttestation> {
    let digest = act_digest(act)?;
    Ok(WitnessAttestation {
        lct: my_lct.to_string(),
        attestation: verdict.to_string(),
        signature: my.sign(digest.as_bytes()).to_hex(),
        timestamp: Utc::now(),
    })
}

/// Witness an act: record the witnessing in hestia's chain **and** return the
/// attestation to attach to the act. The chain entry makes hestia's act of
/// witnessing itself auditable (and tamper-evident via the hash link).
pub fn witness_act(
    chain: &SqliteChainStore,
    act: &Act,
    my: &KeyPair,
    my_lct: Uuid,
    verdict: &str,
) -> Result<WitnessAttestation> {
    let mark = sign_act(act, my, my_lct, verdict)?;
    chain
        .append(
            "witness.act",
            serde_json::json!({
                "act_id": act.act_id,
                "act_digest": act_digest(act)?,
                "actor_lct": act.actor_lct,
                "verdict": verdict,
            }),
            &my_lct.to_string(),
        )
        .context("recording act witnessing in chain")?;
    Ok(mark)
}

/// Verify a witness mark on an act: recompute the digest and check the mark's
/// signature against the witness's public key. This is the verification the
/// *recipient* of a handoff runs — the thing that replaces trust-on-faith.
pub fn verify_witness(
    act: &Act,
    mark: &WitnessAttestation,
    witness_pubkey: &PublicKey,
) -> Result<bool> {
    let digest = act_digest(act)?;
    let sig_bytes = hex::decode(&mark.signature).context("decoding witness signature hex")?;
    let arr: [u8; 64] = sig_bytes.as_slice().try_into().map_err(|_| {
        anyhow::anyhow!(
            "witness signature must be 64 bytes, got {}",
            sig_bytes.len()
        )
    })?;
    let sig = SignatureBytes::from_bytes(arr);
    Ok(witness_pubkey.verify(digest.as_bytes(), &sig).is_ok())
}

#[cfg(test)]
mod tests {
    use super::*;
    use web4_core::act::{SubstanceMedium, SubstanceRef};

    fn an_act() -> Act {
        let actor = Uuid::new_v4();
        let peer = Uuid::new_v4();
        Act::handoff(
            actor,
            peer,
            SubstanceRef::new("forum/handoff-2026-06-20", "abc123", SubstanceMedium::Forum),
            Utc::now(),
        )
    }

    #[test]
    fn witness_mark_verifies_against_the_signer() {
        let kp = KeyPair::generate();
        let my_lct = Uuid::new_v4();
        let act = an_act();
        let mark = sign_act(&act, &kp, my_lct, "verified").unwrap();
        assert!(verify_witness(&act, &mark, &kp.verifying_key()).unwrap());
    }

    #[test]
    fn a_different_key_does_not_verify() {
        let kp = KeyPair::generate();
        let other = KeyPair::generate();
        let act = an_act();
        let mark = sign_act(&act, &kp, Uuid::new_v4(), "verified").unwrap();
        // The recipient checks against the wrong pubkey → rejects.
        assert!(!verify_witness(&act, &mark, &other.verifying_key()).unwrap());
    }

    #[test]
    fn tampering_with_the_act_breaks_the_mark() {
        let kp = KeyPair::generate();
        let act = an_act();
        let mark = sign_act(&act, &kp, Uuid::new_v4(), "verified").unwrap();
        // Repoint the substance after witnessing → digest changes → mark fails.
        let mut tampered = act.clone();
        tampered.substance =
            SubstanceRef::new("forum/something-else", "deadbeef", SubstanceMedium::Forum);
        assert!(!verify_witness(&tampered, &mark, &kp.verifying_key()).unwrap());
    }

    #[test]
    fn digest_excludes_existing_marks_so_n_witnesses_agree() {
        let a = KeyPair::generate();
        let b = KeyPair::generate();
        let mut act = an_act();
        let mark_a = sign_act(&act, &a, Uuid::new_v4(), "verified").unwrap();
        // Attach A's mark, then B witnesses the now-marked act.
        act.witnesses.push(mark_a.clone());
        let mark_b = sign_act(&act, &b, Uuid::new_v4(), "verified").unwrap();
        act.witnesses.push(mark_b.clone());
        // Both marks verify against the fully-marked act — the digest ignored
        // the witnesses field, so A's mark survived B's attachment.
        assert!(verify_witness(&act, &mark_a, &a.verifying_key()).unwrap());
        assert!(verify_witness(&act, &mark_b, &b.verifying_key()).unwrap());
    }
}
