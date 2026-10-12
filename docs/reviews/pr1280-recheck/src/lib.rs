// Compile production state, transport, handshake and authentication; only vault/signing
// are synthetic. This verifies routing/session transitions, not cryptography or Tauri.
#![allow(dead_code, unused_imports)]
#[path = "../../../../app/src-tauri/src/daemon.rs"]
mod daemon;
#[path = "../../../../app/src-tauri/src/handshake.rs"]
mod handshake;
#[path = "../../../../app/src-tauri/src/operator.rs"]
mod operator;
include!(concat!(env!("OUT_DIR"), "/state.rs"));

mod identity_vault {
    pub struct IdentityVault(std::path::PathBuf);
    impl IdentityVault {
        pub fn path(&self) -> &std::path::Path { &self.0 }
        pub fn principal_lct(&self) -> &str { "lct:web4:human:test-principal" }
    }
    pub fn migrate_plaintext_operator_key(
        _: &std::path::Path, destination: std::path::PathBuf, _: &str,
    ) -> Result<IdentityVault, String> {
        Ok(IdentityVault(destination))
    }
}

mod identity {
    pub fn session_request_body(
        _: &crate::identity_vault::IdentityVault, challenge: &str,
    ) -> Result<serde_json::Value, String> {
        Ok(serde_json::json!({"challenge": challenge, "synthetic_review_credential": true}))
    }
}
