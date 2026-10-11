//! D3 router-interface certificates.
//!
//! A router neighbor must not be created from three unrelated operator claims
//! ("router LCT", "Hub member UUID", "key"). This certificate binds them in
//! one immutable payload and proves possession of BOTH identities:
//!
//! 1. the canonical router/Society binding key; and
//! 2. the dedicated Hub membership key.
//!
//! Live Hub pin and receipt-mode checks remain I/O concerns for the CLI/cutover
//! preflight. This module owns the portable cryptographic artifact.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use uuid::Uuid;
use web4_core::crypto::{KeyPair, PublicKey, SignatureBytes};
use web4_core::derive_lct_id;

pub const ROUTER_CERT_PROTOCOL: &str = "hestia-router-interface-cert-v1";
pub const RECEIPT_PROTOCOL: &str = "hub-mailbox-receive-v1";

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct RouterInterfaceCertificatePayload {
    pub protocol: String,
    /// Canonical key-derived router/Society identity.
    pub router_lct: String,
    /// Public half of the key from which router_lct derives.
    pub router_pubkey_hex: String,
    /// Society/Hub where the dedicated transport membership lives.
    pub hub_lct_id: Uuid,
    /// Dedicated receipt-mode Hub member, never a legacy seat mailbox.
    pub hub_member_lct: Uuid,
    /// Live Hub-pinned public key observed at issuance.
    pub hub_member_pubkey_hex: String,
    /// Hestia router interface whose credential handle uses hub_member_lct.
    pub interface_binding_id: Uuid,
    /// Capability proved by a successful non-destructive fetch.
    pub receipt_protocol: String,
    /// UTC Unix seconds at issuance/probe time.
    pub issued_at: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct RouterInterfaceCertificate {
    pub payload: RouterInterfaceCertificatePayload,
    /// Ed25519 signature by the router/Society binding key.
    pub router_signature_hex: String,
    /// Ed25519 signature by the dedicated Hub membership key.
    pub hub_member_signature_hex: String,
}

impl RouterInterfaceCertificatePayload {
    pub fn validate_shape(&self) -> Result<()> {
        anyhow::ensure!(
            self.protocol == ROUTER_CERT_PROTOCOL,
            "router certificate protocol must be {ROUTER_CERT_PROTOCOL}"
        );
        anyhow::ensure!(
            self.receipt_protocol == RECEIPT_PROTOCOL,
            "router certificate receipt protocol must be {RECEIPT_PROTOCOL}"
        );
        anyhow::ensure!(
            self.router_lct.starts_with("lct:web4:mb32:b") && self.router_lct.len() <= 256,
            "router certificate router_lct must be canonical mb32"
        );
        anyhow::ensure!(
            self.router_pubkey_hex.len() == 64
                && self.router_pubkey_hex.bytes().all(|b| b.is_ascii_hexdigit()),
            "router certificate router public key must be 32-byte hex"
        );
        anyhow::ensure!(
            self.hub_member_pubkey_hex.len() == 64
                && self.hub_member_pubkey_hex.bytes().all(|b| b.is_ascii_hexdigit()),
            "router certificate Hub-member public key must be 32-byte hex"
        );
        anyhow::ensure!(self.issued_at > 0, "router certificate issued_at must be nonzero");
        Ok(())
    }

    /// Cross-language deterministic signing bytes. No JSON canonicalization is
    /// required: every field is emitted once in a fixed order under an explicit
    /// domain separator. Protocol version changes require a new domain string.
    pub fn signing_bytes(&self) -> Result<Vec<u8>> {
        self.validate_shape()?;
        Ok(format!(
            "HESTIA-ROUTER-INTERFACE-CERT-V1\n\
             protocol={}\n\
             router_lct={}\n\
             router_pubkey_hex={}\n\
             hub_lct_id={}\n\
             hub_member_lct={}\n\
             hub_member_pubkey_hex={}\n\
             interface_binding_id={}\n\
             receipt_protocol={}\n\
             issued_at={}\n",
            self.protocol,
            self.router_lct,
            self.router_pubkey_hex,
            self.hub_lct_id,
            self.hub_member_lct,
            self.hub_member_pubkey_hex,
            self.interface_binding_id,
            self.receipt_protocol,
            self.issued_at,
        )
        .into_bytes())
    }
}

impl RouterInterfaceCertificate {
    pub fn issue(
        payload: RouterInterfaceCertificatePayload,
        router_key: &KeyPair,
        hub_member_key: &KeyPair,
    ) -> Result<Self> {
        payload.validate_shape()?;
        anyhow::ensure!(
            derive_lct_id(&router_key.verifying_key()) == payload.router_lct,
            "router signing key does not derive the certificate router_lct"
        );
        anyhow::ensure!(
            router_key.verifying_key().to_hex() == payload.router_pubkey_hex,
            "router signing key does not match router_pubkey_hex"
        );
        anyhow::ensure!(
            hub_member_key.verifying_key().to_hex() == payload.hub_member_pubkey_hex,
            "Hub membership signing key does not match hub_member_pubkey_hex"
        );
        let bytes = payload.signing_bytes()?;
        Ok(Self {
            router_signature_hex: router_key.sign(&bytes).to_hex(),
            hub_member_signature_hex: hub_member_key.sign(&bytes).to_hex(),
            payload,
        })
    }

    pub fn verify(&self) -> Result<()> {
        let bytes = self.payload.signing_bytes()?;
        let router_pub = public_key_from_hex(&self.payload.router_pubkey_hex)
            .context("router certificate router public key")?;
        let member_pub = public_key_from_hex(&self.payload.hub_member_pubkey_hex)
            .context("router certificate Hub-member public key")?;

        anyhow::ensure!(
            derive_lct_id(&router_pub) == self.payload.router_lct,
            "router certificate LCT does not derive from router_pubkey_hex"
        );

        router_pub
            .verify(&bytes, &signature_from_hex(&self.router_signature_hex)?)
            .context("router certificate router signature")?;
        member_pub
            .verify(&bytes, &signature_from_hex(&self.hub_member_signature_hex)?)
            .context("router certificate Hub-member signature")?;
        Ok(())
    }

    /// Stable evidence handle stored beside a RouterNeighbor.
    pub fn fingerprint(&self) -> Result<String> {
        self.verify()?;
        let mut bytes = self.payload.signing_bytes()?;
        bytes.extend_from_slice(self.router_signature_hex.as_bytes());
        bytes.push(b'\n');
        bytes.extend_from_slice(self.hub_member_signature_hex.as_bytes());
        Ok(format!("sha256-content:{}", web4_core::sha256_hex(&bytes)))
    }

    pub fn from_json_bytes(bytes: &[u8]) -> Result<Self> {
        let cert: Self =
            serde_json::from_slice(bytes).context("parsing router-interface certificate JSON")?;
        cert.verify()?;
        Ok(cert)
    }
}

fn public_key_from_hex(value: &str) -> Result<PublicKey> {
    let raw = hex::decode(value).context("decoding public key hex")?;
    let bytes: [u8; 32] = raw
        .as_slice()
        .try_into()
        .map_err(|_| anyhow::anyhow!("public key must decode to 32 bytes"))?;
    PublicKey::from_bytes(&bytes).context("parsing Ed25519 public key")
}

fn signature_from_hex(value: &str) -> Result<SignatureBytes> {
    let raw = hex::decode(value).context("decoding signature hex")?;
    let bytes: [u8; 64] = raw
        .as_slice()
        .try_into()
        .map_err(|_| anyhow::anyhow!("signature must decode to 64 bytes"))?;
    Ok(SignatureBytes::from_bytes(bytes))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn payload(router: &KeyPair, member: &KeyPair) -> RouterInterfaceCertificatePayload {
        RouterInterfaceCertificatePayload {
            protocol: ROUTER_CERT_PROTOCOL.to_string(),
            router_lct: derive_lct_id(&router.verifying_key()),
            router_pubkey_hex: router.verifying_key().to_hex(),
            hub_lct_id: Uuid::new_v4(),
            hub_member_lct: Uuid::new_v4(),
            hub_member_pubkey_hex: member.verifying_key().to_hex(),
            interface_binding_id: Uuid::new_v4(),
            receipt_protocol: RECEIPT_PROTOCOL.to_string(),
            issued_at: 1_700_000_000,
        }
    }

    #[test]
    fn dual_signed_certificate_verifies_and_has_stable_fingerprint() {
        let router = KeyPair::generate();
        let member = KeyPair::generate();
        let cert = RouterInterfaceCertificate::issue(payload(&router, &member), &router, &member)
            .unwrap();
        cert.verify().unwrap();
        assert_eq!(cert.fingerprint().unwrap(), cert.fingerprint().unwrap());

        let wire = serde_json::to_vec(&cert).unwrap();
        assert_eq!(RouterInterfaceCertificate::from_json_bytes(&wire).unwrap(), cert);
    }

    #[test]
    fn router_lct_is_cryptographically_bound_not_claimed() {
        let router = KeyPair::generate();
        let member = KeyPair::generate();
        let mut p = payload(&router, &member);
        p.router_lct = derive_lct_id(&KeyPair::generate().verifying_key());
        assert!(RouterInterfaceCertificate::issue(p, &router, &member)
            .unwrap_err()
            .to_string()
            .contains("does not derive"));
    }

    #[test]
    fn tampering_any_signed_payload_field_breaks_verification() {
        let router = KeyPair::generate();
        let member = KeyPair::generate();
        let mut cert =
            RouterInterfaceCertificate::issue(payload(&router, &member), &router, &member).unwrap();
        cert.payload.interface_binding_id = Uuid::new_v4();
        assert!(cert.verify().is_err());
    }

    #[test]
    fn both_signatures_are_required() {
        let router = KeyPair::generate();
        let member = KeyPair::generate();
        let wrong = KeyPair::generate();
        let mut cert =
            RouterInterfaceCertificate::issue(payload(&router, &member), &router, &member).unwrap();
        let bytes = cert.payload.signing_bytes().unwrap();
        cert.hub_member_signature_hex = wrong.sign(&bytes).to_hex();
        assert!(cert.verify().is_err());
    }
}
