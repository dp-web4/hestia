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
use web4_core::crypto::{KeyPair, PublicKey, SignatureBytes};
use web4_core::pair_channel::{self, Sealed};

/// Hub discovery metadata from `/.well-known/web4-hub.json`.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HubInfo {
    pub hub_lct_id: Uuid,
    /// The hub's LCT public key (hex) — the ECDH peer for opening an E2E
    /// member↔hub channel. `None` on hubs that don't expose one (e.g. a
    /// Hestia-mode Sovereign without local-key channel support).
    #[serde(default)]
    pub hub_pubkey_hex: Option<String>,
    #[serde(default)]
    pub api_versions: Vec<String>,
    #[serde(default)]
    pub endpoints: HubEndpoints,
    #[serde(default)]
    pub hubs: Vec<HubSummary>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct HubEndpoints {
    #[serde(default)]
    pub rest: String,
    #[serde(default)]
    pub mcp: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HubSummary {
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

/// An established end-to-end encrypted channel to a hub (the member side).
///
/// Per the hub authz/confidentiality model, every citizen-tier+ request and
/// response travels sealed over a member↔hub channel — never in the clear.
/// This is the member's view of that channel: the `pair_id` agreed at open
/// time and the hub's LCT public key. Sealing/opening uses `web4_core::
/// pair_channel` (X25519 ECDH derived from the LCT identity keys →
/// ChaCha20-Poly1305), the same primitive the hub uses, so the two ends
/// interoperate by construction.
///
/// The member keeps its own `KeyPair` (held by Hestia's vault) and passes it
/// in per call — this type never holds a secret.
#[derive(Clone, Debug)]
pub struct HubChannel {
    /// The hub this channel is to (LCT id).
    pub hub_lct_id: Uuid,
    /// Pair id agreed with the hub at channel-open; salts the session key.
    pub pair_id: Uuid,
    /// The hub's LCT public key — the ECDH peer.
    pub hub_pubkey: PublicKey,
}

impl HubChannel {
    pub fn new(hub_lct_id: Uuid, pair_id: Uuid, hub_pubkey_hex: &str) -> Result<Self> {
        let bytes = hex::decode(hub_pubkey_hex)
            .context("decoding hub pubkey hex")?;
        let arr: [u8; 32] = bytes.as_slice().try_into()
            .map_err(|_| anyhow::anyhow!("hub pubkey must be 32 bytes, got {}", bytes.len()))?;
        let hub_pubkey = PublicKey::from_bytes(&arr).context("parsing hub pubkey")?;
        Ok(Self { hub_lct_id, pair_id, hub_pubkey })
    }

    /// Build a channel from a discovery result + a freshly-minted `pair_id`.
    /// v1 needs no server handshake to open: the hub re-derives the session
    /// key per request from our pinned pubkey + this `pair_id`.
    pub fn from_hub_info(info: &HubInfo, pair_id: Uuid) -> Result<Self> {
        let pubkey_hex = info.hub_pubkey_hex.as_deref().ok_or_else(|| {
            anyhow::anyhow!("hub does not expose a channel pubkey (no hub_pubkey_hex in discovery)")
        })?;
        Self::new(info.hub_lct_id, pair_id, pubkey_hex)
    }

    /// Seal a request for the hub. `my` is the member's LCT keypair (from the
    /// vault). Returns base64 ready for JSON transport. The hub `open`s it with
    /// its own keypair + the member's public key + this `pair_id`.
    pub fn seal_request(&self, my: &KeyPair, request: &serde_json::Value) -> Result<String> {
        let plaintext = serde_json::to_vec(request).context("serializing request")?;
        let sealed = pair_channel::seal(my, &self.hub_pubkey, self.pair_id, &plaintext)
            .context("sealing request to hub")?;
        Ok(sealed.to_base64())
    }

    /// Open a sealed response from the hub.
    pub fn open_response(&self, my: &KeyPair, sealed_b64: &str) -> Result<serde_json::Value> {
        let sealed = Sealed::from_base64(sealed_b64).context("decoding sealed response")?;
        let plaintext = pair_channel::open(my, &self.hub_pubkey, self.pair_id, &sealed)
            .context("opening hub response (AEAD auth failed → tampered or wrong key)")?;
        serde_json::from_slice(&plaintext).context("parsing decrypted response JSON")
    }
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
    pub hubs_joined: Vec<Uuid>,
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
        hub_id: Uuid,
        envelope: &SignedEnvelope,
    ) -> Result<()> {
        let url = format!("{}/hubs/{}/delegations", rest_endpoint, hub_id);
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

    /// Open an E2E channel to a hub: discover its LCT pubkey and mint a fresh
    /// `pair_id`. v1 needs no server round-trip — the hub re-derives the
    /// session key per request. (FS variants come with the Sprint-F handshake.)
    pub async fn open_channel(&self, base_url: &str, pair_id: Uuid) -> Result<HubChannel> {
        let info = self.discover(base_url).await?;
        HubChannel::from_hub_info(&info, pair_id)
    }

    /// Run a query over an established channel. The request `{tool, args}` is
    /// sealed to the hub, POSTed to `/v1/hubs/{hub_id}/channel`, and the sealed
    /// response is opened — nothing in the clear. `my` is the member's vault
    /// keypair; `my_lct_id` identifies which pinned pubkey the hub uses.
    pub async fn channel_query(
        &self,
        rest_endpoint: &str,
        channel: &HubChannel,
        my: &KeyPair,
        my_lct_id: Uuid,
        tool: &str,
        args: serde_json::Value,
    ) -> Result<serde_json::Value> {
        let request = serde_json::json!({ "tool": tool, "args": args });
        let sealed = channel.seal_request(my, &request)?;
        let url = format!(
            "{}/hubs/{}/channel",
            rest_endpoint.trim_end_matches('/'),
            channel.hub_lct_id
        );
        let body = ChannelRequestBody {
            caller_lct_id: my_lct_id,
            pair_id: channel.pair_id,
            sealed,
        };
        let resp = self.http.post(&url).json(&body).send().await
            .with_context(|| format!("posting channel query to {url}"))?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            anyhow::bail!("hub channel returned HTTP {status}: {text}");
        }
        let out: ChannelResponseBody = serde_json::from_str(&text)
            .with_context(|| "parsing sealed channel response")?;
        channel.open_response(my, &out.sealed)
    }
}

/// Wire body for a channel request — matches the hub's `/v1/hubs/{id}/channel`.
#[derive(Serialize)]
struct ChannelRequestBody {
    caller_lct_id: Uuid,
    pair_id: Uuid,
    sealed: String,
}

/// Wire body for the sealed channel response.
#[derive(Deserialize)]
struct ChannelResponseBody {
    sealed: String,
}

trait Pipe: Sized {
    fn pipe<F, R>(self, f: F) -> R where F: FnOnce(Self) -> R { f(self) }
}
impl<T> Pipe for T {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn channel_round_trips_member_to_hub_and_back() {
        // Simulate the two ends: a member (Hestia) and the hub, each with an
        // LCT keypair. They share only public info (each other's pubkey + a
        // pair_id). This proves the member-side HubChannel interoperates with
        // the hub-side `pair_channel` primitive in both directions.
        let member = KeyPair::generate();
        let hub = KeyPair::generate();
        let pair_id = Uuid::new_v4();

        let member_view = HubChannel {
            hub_lct_id: Uuid::new_v4(),
            pair_id,
            hub_pubkey: hub.verifying_key(),
        };

        // Member seals a request → hub opens it.
        let request = serde_json::json!({"tool": "find_members", "query": "rust async review"});
        let sealed_b64 = member_view.seal_request(&member, &request).unwrap();
        let opened = pair_channel::open(
            &hub, &member.verifying_key(), pair_id,
            &Sealed::from_base64(&sealed_b64).unwrap(),
        ).unwrap();
        assert_eq!(serde_json::from_slice::<serde_json::Value>(&opened).unwrap(), request);

        // Hub seals a response → member opens it.
        let response = serde_json::json!({"members": [{"lct": "abc", "score": 0.82}]});
        let resp_sealed = pair_channel::seal(
            &hub, &member.verifying_key(), pair_id,
            &serde_json::to_vec(&response).unwrap(),
        ).unwrap();
        let got = member_view.open_response(&member, &resp_sealed.to_base64()).unwrap();
        assert_eq!(got, response);

        // Wrong pair_id must fail to open (AEAD auth) — confirms the salt binds.
        let wrong = HubChannel { pair_id: Uuid::new_v4(), ..member_view.clone() };
        assert!(wrong.open_response(&member, &resp_sealed.to_base64()).is_err());
    }

    #[test]
    fn hub_channel_new_parses_pubkey_hex() {
        let hub = KeyPair::generate();
        let hex = hub.verifying_key().to_hex();
        let ch = HubChannel::new(Uuid::new_v4(), Uuid::new_v4(), &hex).unwrap();
        assert_eq!(ch.hub_pubkey.to_hex(), hex);
        assert!(HubChannel::new(Uuid::new_v4(), Uuid::new_v4(), "zz").is_err());
    }

    #[test]
    fn from_hub_info_builds_channel_or_errors_when_no_pubkey() {
        let hub = KeyPair::generate();
        let hub_lct = Uuid::new_v4();
        let pair = Uuid::new_v4();
        // With a pubkey in discovery → channel built, keyed to that pubkey.
        let info = HubInfo {
            hub_lct_id: hub_lct,
            hub_pubkey_hex: Some(hub.verifying_key().to_hex()),
            api_versions: vec!["v1".into()],
            endpoints: HubEndpoints::default(),
            hubs: vec![],
        };
        let ch = HubChannel::from_hub_info(&info, pair).unwrap();
        assert_eq!(ch.hub_lct_id, hub_lct);
        assert_eq!(ch.pair_id, pair);
        assert_eq!(ch.hub_pubkey.to_hex(), hub.verifying_key().to_hex());

        // Without one → a clear error (e.g. a Hestia-mode hub).
        let info_no_key = HubInfo { hub_pubkey_hex: None, ..info };
        assert!(HubChannel::from_hub_info(&info_no_key, pair).is_err());
    }

    #[test]
    fn channel_request_body_serializes_for_the_hub() {
        // The wire body must match the hub's /v1/hubs/{id}/channel handler.
        let body = ChannelRequestBody {
            caller_lct_id: Uuid::nil(),
            pair_id: Uuid::nil(),
            sealed: "AAAA".into(),
        };
        let v: serde_json::Value = serde_json::to_value(&body).unwrap();
        assert!(v.get("caller_lct_id").is_some());
        assert!(v.get("pair_id").is_some());
        assert_eq!(v.get("sealed").and_then(|s| s.as_str()), Some("AAAA"));
    }

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
            hubs_joined: vec![],
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
        let payload = serde_json::json!({"action": "join", "hub": "test"});

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
            hubs_joined: vec![],
        });

        assert!(store.find_by_url("https://hub.example.com").is_some());
        assert!(store.find_by_url("https://other.com").is_none());
        assert!(store.find_by_id(id).is_some());
    }
}
