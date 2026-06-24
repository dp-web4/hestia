// Copyright (c) 2026 MetaLINXX Inc.
// SPDX-License-Identifier: AGPL-3.0-or-later

//! Mint and witness the fleet's **first real web4 Act** — Phase-1 dogfooding.
//!
//! Builds a session-handoff [`Act`] (this session's arc → its future self,
//! temporal-MRH continuity) over real substance, witnesses it with hestia's
//! flat witness primitive, verifies the mark, and prints the Act JSON to stdout
//! (provenance to stderr). The actor is a freshly-minted arc LCT — Phase-1's
//! "an LCT per arc". The witness mark is the arc's own authorship signature;
//! independent fleet/hestia co-witnessing follows once the live ledger path is
//! up. The Act binds to a `content_hash` of the substance so it can't drift.
//!
//! Run: `cargo run --example first_act -- <substance_path>`

use std::io::Read;

use chrono::Utc;
use sha2::{Digest, Sha256};
use uuid::Uuid;
use web4_core::act::{Act, ConsequenceClass, SubstanceMedium, SubstanceRef};
use web4_core::crypto::KeyPair;

use hestia::witness_act::{act_digest, sign_act, verify_witness};

fn main() {
    let substance_path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "(no substance path given)".into());

    // Real content hash of the substance file — binds the thin Act to this
    // exact version of the fat thing it attests.
    let mut content = Vec::new();
    if let Ok(mut f) = std::fs::File::open(&substance_path) {
        let _ = f.read_to_end(&mut content);
    }
    let content_hash = {
        let mut h = Sha256::new();
        h.update(&content);
        hex::encode(h.finalize())
    };

    // Phase-1: mint an arc LCT for this session (the actor / from).
    let arc = KeyPair::generate();
    let arc_lct = Uuid::new_v4();

    // A handoff to future-self (temporal MRH). `memory` addresses FutureSelf;
    // relabel the kind "handoff"; a session handoff is reversible.
    let substance = SubstanceRef::new(&substance_path, content_hash, SubstanceMedium::Doc);
    let mut act = Act::memory(arc_lct, substance, Utc::now())
        .with_kind("handoff")
        .with_consequence(ConsequenceClass::Reversible);

    // Witness it (the arc's authorship signature — verifiable by any recipient).
    let mark = sign_act(&act, &arc, arc_lct, "authored").expect("sign");
    act.witnesses.push(mark.clone());

    let verified = verify_witness(&act, &mark, &arc.verifying_key()).expect("verify");

    eprintln!("# first real web4 Act");
    eprintln!("arc_lct (actor): {arc_lct}");
    eprintln!("arc_pubkey:      {}", arc.verifying_key().to_hex());
    eprintln!("act_digest:      {}", act_digest(&act).expect("digest"));
    eprintln!("witness verifies: {verified}");
    assert!(verified, "the witness mark must verify");

    println!("{}", serde_json::to_string_pretty(&act).expect("serialize"));
}
