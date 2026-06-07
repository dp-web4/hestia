//! Hub connection — discovery, challenge-response auth, and multi-hub state.
//!
//! Implements the hub HTTP API surface per CBP's spec:
//! - Discovery via `/.well-known/web4-hub.json`
//! - Challenge-nonce flow for replay-protected requests
//! - Signed envelope construction for all consequential requests
//!
//! Local state stored at `~/.hestia/hubs.json`.

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use uuid::Uuid;
use web4_core::crypto::{KeyPair, SignatureBytes};

/// Hub discovery metadata from `/.well-known/web4-hub.json`.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HubInfo {
    pub hub_lct_id: Uuid,
    #[serde(default)]
    pub api_versions: Vec<String>,
    #[serde(default)]
    pub endpoints: HubEndpoints,
    #[serde(default)]
    pub chapters: Vec<ChapterSummary>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct HubEndpoints {
    #[serde(default)]
    pub rest: String,
    #[serde(default)]
    pub mcp: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ChapterSummary {
    pub id: Uuid,
    pub name: String,
    #[serde(default)]
    pub public: bool,
}

/// A challenge nonce from the hub.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ChallengeResponse {
    pub nonce: String,
    pub expires_at: DateTime<Utc>,
}

/// A signed request envelope for hub API calls.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SignedEnvelope {
    pub challenge_nonce: String,
    pub payload: serde_json::Value,
    pub signature: String,
    pub signer_lct_id: Uuid,
}

impl SignedEnvelope {
    pub fn create(
        nonce: String,
        payload: serde_json::Value,
        signer_lct_id: Uuid,
        keypair: &KeyPair,
    ) -> Self {
        let mut signing_data = Vec::new();
        signing_data.extend_from_slice(nonce.as_bytes());
        signing_data.extend_from_slice(payload.to_string().as_bytes());
        let sig = keypair.sign(&signing_data);

        Self {
            challenge_nonce: nonce,
            payload,
            signature: sig.to_hex(),
            signer_lct_id,
        }
    }
}

/// A connected hub — persisted locally.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HubConnection {
    pub id: Uuid,
    pub url: String,
    pub hub_lct_id: Uuid,
    pub our_lct_id: Uuid,
    pub connected_at: DateTime<Utc>,
    pub last_seen: Option<DateTime<Utc>>,
    pub api_version: String,
    pub rest_endpoint: String,
    #[serde(default)]
    pub chapters_joined: Vec<Uuid>,
}

/// Multi-hub connection store — persisted at `~/.hestia/hubs.json`.
#[derive(Debug, Serialize, Deserialize, Default)]
pub struct HubStore {
    pub connections: Vec<HubConnection>,
}

impl HubStore {
    pub fn path(hestia_home: &Path) -> PathBuf {
        hestia_home.join("hubs.json")
    }

    pub fn load(hestia_home: &Path) -> Result<Self> {
        let path = Self::path(hestia_home);
        if !path.exists() {
            return Ok(Self::default());
        }
        let data = std::fs::read_to_string(&path)
            .with_context(|| format!("reading {}", path.display()))?;
        serde_json::from_str(&data)
            .with_context(|| format!("parsing {}", path.display()))
    }

    pub fn save(&self, hestia_home: &Path) -> Result<()> {
        let path = Self::path(hestia_home);
        let data = serde_json::to_string_pretty(self)?;
        std::fs::write(&path, data)
            .with_context(|| format!("writing {}", path.display()))
    }

    pub fn find_by_url(&self, url: &str) -> Option<&HubConnection> {
        self.connections.iter().find(|c| c.url == url)
    }

    pub fn find_by_id(&self, id: Uuid) -> Option<&HubConnection> {
        self.connections.iter().find(|c| c.id == id)
    }
}

/// HTTP client for hub API calls.
pub struct HubClient {
    http: reqwest::Client,
}

impl HubClient {
    pub fn new() -> Self {
        Self {
            http: reqwest::Client::new(),
        }
    }

    /// Discover hub metadata from well-known URL.
    pub async fn discover(&self, base_url: &str) -> Result<HubInfo> {
        let url = format!("{}/.well-known/web4-hub.json", base_url.trim_end_matches('/'));
        let resp = self.http.get(&url).send().await
            .with_context(|| format!("connecting to {url}"))?;

        if !resp.status().is_success() {
            anyhow::bail!("hub discovery failed: HTTP {}", resp.status());
        }

        resp.json::<HubInfo>().await
            .with_context(|| format!("parsing hub info from {url}"))
    }

    /// Request a challenge nonce from the hub.
    pub async fn challenge(&self, rest_endpoint: &str, for_lct_id: Uuid) -> Result<ChallengeResponse> {
        let url = format!("{}/auth/challenge", rest_endpoint);
        let body = serde_json::json!({ "for_lct_id": for_lct_id.to_string() });

        let resp = self.http.post(&url).json(&body).send().await
            .with_context(|| format!("requesting challenge from {url}"))?;

        if !resp.status().is_success() {
            anyhow::bail!("challenge request failed: HTTP {}", resp.status());
        }

        resp.json::<ChallengeResponse>().await
            .with_context(|| "parsing challenge response")
    }

    /// Submit a signed envelope to a hub endpoint.
    pub async fn submit_signed(
        &self,
        url: &str,
        envelope: &SignedEnvelope,
    ) -> Result<serde_json::Value> {
        let resp = self.http.post(url)
            .json(&serde_json::json!({ "envelope": envelope }))
            .send().await
            .with_context(|| format!("submitting to {url}"))?;

        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();

        if !status.is_success() {
            anyhow::bail!("hub returned HTTP {status}: {body}");
        }

        serde_json::from_str(&body).unwrap_or(serde_json::Value::Null).pipe(Ok)
    }

    /// Register a delegation with the hub so it can verify agent signatures.
    pub async fn register_delegation(
        &self,
        rest_endpoint: &str,
        chapter_id: Uuid,
        envelope: &SignedEnvelope,
    ) -> Result<()> {
        let url = format!("{}/chapters/{}/delegations", rest_endpoint, chapter_id);
        let resp = self.http.post(&url)
            .json(&serde_json::json!({ "envelope": envelope }))
            .send().await
            .with_context(|| format!("registering delegation at {url}"))?;

        if !resp.status().is_success() {
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!("delegation registration failed: {body}");
        }
        Ok(())
    }
}

trait Pipe: Sized {
    fn pipe<F, R>(self, f: F) -> R where F: FnOnce(Self) -> R { f(self) }
}
impl<T> Pipe for T {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hub_store_roundtrip() {
        let mut store = HubStore::default();
        store.connections.push(HubConnection {
            id: Uuid::new_v4(),
            url: "https://hub.example.com".into(),
            hub_lct_id: Uuid::new_v4(),
            our_lct_id: Uuid::new_v4(),
            connected_at: Utc::now(),
            last_seen: None,
            api_version: "v1".into(),
            rest_endpoint: "https://hub.example.com/v1".into(),
            chapters_joined: vec![],
        });

        let json = serde_json::to_string(&store).unwrap();
        let recovered: HubStore = serde_json::from_str(&json).unwrap();
        assert_eq!(recovered.connections.len(), 1);
        assert_eq!(recovered.connections[0].url, "https://hub.example.com");
    }

    #[test]
    fn test_signed_envelope() {
        let kp = KeyPair::generate();
        let lct_id = Uuid::new_v4();
        let payload = serde_json::json!({"action": "join", "chapter": "test"});

        let envelope = SignedEnvelope::create(
            "nonce123".into(),
            payload.clone(),
            lct_id,
            &kp,
        );

        assert_eq!(envelope.challenge_nonce, "nonce123");
        assert_eq!(envelope.signer_lct_id, lct_id);
        assert!(!envelope.signature.is_empty());
    }

    #[test]
    fn test_find_by_url() {
        let mut store = HubStore::default();
        let id = Uuid::new_v4();
        store.connections.push(HubConnection {
            id,
            url: "https://hub.example.com".into(),
            hub_lct_id: Uuid::new_v4(),
            our_lct_id: Uuid::new_v4(),
            connected_at: Utc::now(),
            last_seen: None,
            api_version: "v1".into(),
            rest_endpoint: "https://hub.example.com/v1".into(),
            chapters_joined: vec![],
        });

        assert!(store.find_by_url("https://hub.example.com").is_some());
        assert!(store.find_by_url("https://other.com").is_none());
        assert!(store.find_by_id(id).is_some());
    }
}
