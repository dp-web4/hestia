//! Synthetic-only regression for the delegation snapshot's operator-key cache.

#[test]
fn equal_size_and_mtime_key_replacement_must_refresh_the_verifier() {
    use hestia::member_registry::MemberRegistry;
    use hestia::delegation::{agent_key_for_lct, DelegationStore};
    use hestia::server::delegation_gate::{assess, Act, DelegationGate, GateMode, Snapshot, Status};
    use hestia::vault::Vault;
    use web4_core::crypto::KeyPair;
    use web4_core::RoleRegistry;

    let dir = tempfile::tempdir().unwrap();
    let vault = Vault::init(dir.path().join("synthetic-vault"), "test-passphrase".into()).unwrap();
    let key_path = dir.path().join("operator.key");
    let write_key = |bytes: [u8; 32]| {
        std::fs::write(&key_path, serde_json::json!({"secret_key_hex":hex::encode(bytes)}).to_string()).unwrap();
    };
    write_key([1; 32]);
    let old_metadata = std::fs::metadata(&key_path).unwrap();
    let old_mtime = old_metadata.modified().unwrap();
    let gate = DelegationGate::new(dir.path().to_path_buf());
    let members = MemberRegistry::default();
    let roles = RoleRegistry::new();
    gate.refresh(&vault, &members, &roles);
    let old = gate.snapshot().operator_key.clone().unwrap();
    assert_eq!(old, KeyPair::from_secret_bytes(&[1; 32]).verifying_key());

    write_key([2; 32]);
    std::fs::OpenOptions::new().write(true).open(&key_path).unwrap()
        .set_times(std::fs::FileTimes::new().set_modified(old_mtime)).unwrap();
    let new_metadata = std::fs::metadata(&key_path).unwrap();
    assert_eq!(new_metadata.len(), old_metadata.len());
    assert_eq!(new_metadata.modified().unwrap(), old_mtime);
    gate.refresh(&vault, &members, &roles);
    let current = gate.snapshot().operator_key.clone().unwrap();
    let old_signer = KeyPair::from_secret_bytes(&[1; 32]);
    let member_lct = "lct:web4:synthetic-member";
    let mut store = DelegationStore::default();
    store.create_delegation(uuid::Uuid::new_v4(), agent_key_for_lct(member_lct), vec![],
                            vec!["act:command".into()], Some(1), &old_signer);
    let mut evidence = Snapshot::default();
    evidence.mode = Some(GateMode::Enforce);
    evidence.operator_key = Some(KeyPair::from_secret_bytes(&[2; 32]).verifying_key());
    evidence.store = Some(store);
    evidence.member_lcts.insert("synthetic".into(), member_lct.into());
    let action = Act { plugin_id: "synthetic", role: "role:test", tool_name: "Bash",
                       category: "command", target: Some("synthetic") };
    assert_eq!(assess(&evidence, &action, chrono::Utc::now()).status, Status::InvalidSignature,
               "control: the replacement verifier rejects the old signature");
    evidence.operator_key = Some(current.clone());
    let finding = assess(&evidence, &action, chrono::Utc::now());
    assert_eq!(finding.status, Status::InvalidSignature,
               "a delegation signed by the replaced key must not still match");
    assert_eq!(current, KeyPair::from_secret_bytes(&[2; 32]).verifying_key(),
               "a changed key must not remain trusted merely because file metadata collides");
}
