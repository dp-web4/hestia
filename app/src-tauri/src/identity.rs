//! App-side construction of a composed operator session.
//!
//! The principal, app harness, and device anchor are distinct keys held by the
//! encrypted [`IdentityVault`](crate::identity_vault::IdentityVault). They sign
//! one canonical transcript, so no identity or authority field can be changed
//! after either side has expressed consent.

use crate::identity_vault::IdentityVault;

pub const SESSION_TRANSCRIPT_DOMAIN: &str = "hestia:operator-session:v1";
pub const SOVEREIGN_OFFICE: &str = "role:constellation:sovereign";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionComposition {
    pub actor: String,
    pub actor_public_key: String,
    pub principal: String,
    pub via_device: String,
    pub device_public_key: String,
    pub office: String,
    pub authority: String,
}

impl SessionComposition {
    pub fn from_vault(vault: &IdentityVault, challenge: &str) -> Self {
        Self {
            actor: vault.harness_lct().to_string(),
            actor_public_key: vault.harness_public_key_hex(),
            principal: vault.principal_lct().to_string(),
            via_device: vault.device_lct().to_string(),
            device_public_key: vault.device_public_key_hex(),
            office: SOVEREIGN_OFFICE.to_string(),
            // The principal's signature over this value is the bounded delegation:
            // it authorizes this composition for this one daemon-issued challenge.
            authority: format!("operator-session:{challenge}"),
        }
    }
}

/// Length-delimited, domain-separated bytes shared with the daemon verifier.
/// Field order and spelling are the wire contract; changing either requires v2.
pub fn canonical_session_transcript(challenge: &str, composition: &SessionComposition) -> Vec<u8> {
    let fields = [
        ("challenge", challenge),
        ("actor", composition.actor.as_str()),
        ("actor_public_key", composition.actor_public_key.as_str()),
        ("principal", composition.principal.as_str()),
        ("via_device", composition.via_device.as_str()),
        ("device_public_key", composition.device_public_key.as_str()),
        ("office", composition.office.as_str()),
        ("authority", composition.authority.as_str()),
    ];
    let mut out = format!("{SESSION_TRANSCRIPT_DOMAIN}\n").into_bytes();
    for (name, value) in fields {
        out.extend_from_slice(format!("{name}:{}\n", value.len()).as_bytes());
        out.extend_from_slice(value.as_bytes());
        out.push(b'\n');
    }
    out
}

/// Produce the complete, jointly signed request body. The legacy `lct_id`
/// remains as an equality check only; the daemon refuses disagreement.
pub fn session_request_body(
    vault: &IdentityVault,
    challenge: &str,
) -> Result<serde_json::Value, String> {
    let composition = SessionComposition::from_vault(vault, challenge);
    let transcript = canonical_session_transcript(challenge, &composition);
    Ok(serde_json::json!({
        "lct_id": composition.principal,
        "challenge": challenge,
        "actor": composition.actor,
        "actor_public_key": composition.actor_public_key,
        "principal": composition.principal,
        "via_device": composition.via_device,
        "device_public_key": composition.device_public_key,
        "office": composition.office,
        "authority": composition.authority,
        "signature": vault.sign_hex(&transcript)?,
        "actor_signature": vault.sign_harness_hex(&transcript),
        "device_signature": vault.sign_device_hex(&transcript),
        "transcript": SESSION_TRANSCRIPT_DOMAIN,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn transcript_is_unambiguous_and_domain_separated() {
        let c = SessionComposition {
            actor: "lct:web4:mb32:bactor".into(),
            actor_public_key: "11".repeat(32),
            principal: "lct:web4:mb32:bprincipal".into(),
            via_device: "lct:web4:mb32:bdevice".into(),
            device_public_key: "22".repeat(32),
            office: SOVEREIGN_OFFICE.into(),
            authority: "operator-session:abc".into(),
        };
        let bytes = canonical_session_transcript("abc", &c);
        assert_eq!(
            web4_core::crypto::sha256_hex(&bytes),
            "0524720396a6a9be07c5fa62e9e736e1d1302d59e37d7daf3609d8f87bd492a1",
            "cross-crate transcript vector changed; bump the domain version"
        );
        let text = String::from_utf8(bytes).unwrap();
        assert!(text.starts_with("hestia:operator-session:v1\nchallenge:3\nabc\n"));
        for field in ["actor", "principal", "via_device", "office", "authority"] {
            assert!(text.contains(&format!("{field}:")), "missing {field}");
        }
    }
}
