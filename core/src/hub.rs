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
use uuid::Uuid;
use web4_core::crypto::{KeyPair, PublicKey};
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

/// Outcome of a self-add join attempt.
#[derive(Clone, Debug)]
pub enum JoinOutcome {
    /// Admitted immediately — the member is pinned and acts will verify.
    Admitted(serde_json::Value),
    /// The hub verified the request but hub law escalates admission to the
    /// Sovereign. The member is NOT yet pinned; acts will 401 until approved.
    Escalated { reason: String },
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
        let bytes = hex::decode(hub_pubkey_hex).context("decoding hub pubkey hex")?;
        let arr: [u8; 32] = bytes
            .as_slice()
            .try_into()
            .map_err(|_| anyhow::anyhow!("hub pubkey must be 32 bytes, got {}", bytes.len()))?;
        let hub_pubkey = PublicKey::from_bytes(&arr).context("parsing hub pubkey")?;
        Ok(Self {
            hub_lct_id,
            pair_id,
            hub_pubkey,
        })
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

    /// Open a notification the hub **pushed** to us (the citizen side). A
    /// notification is the member↔hub channel *reversed*: the hub seals to our
    /// pinned pubkey, we open with our keypair. Same crypto as
    /// [`open_response`](Self::open_response); named for the inbound direction
    /// so the `notify` MCP method reads clearly. (HUB's `ReferencedAct{to:
    /// Citizen, sealed_body}` — this opens the `sealed_body`.)
    pub fn open_notification(&self, my: &KeyPair, sealed_b64: &str) -> Result<serde_json::Value> {
        self.open_response(my, sealed_b64)
    }

    /// Seal an ACK back to the hub confirming receipt of a notification, so the
    /// hub can mark it delivered and stop queuing it. Same sealing as a request.
    pub fn seal_ack(&self, my: &KeyPair, ack: &NotificationAck) -> Result<String> {
        let value = serde_json::to_value(ack).context("serializing notification ack")?;
        self.seal_request(my, &value)
    }
}

// [retired 2026-07-20] `SealedSecret` / `seal_secret_for_peer` / `open_secret_from_peer`
// were the member→member send_secret path (peer-sealed body relayed opaquely, the
// receiver resolving the sender's operational key from the registry). Secrets now
// ride confirmed paired channels as `pair_message`s (`crate::pairing`, v2 forward-
// secret); the pairing keys make that per-send seal + registry-PKI resolution
// unnecessary. Dogfooded CBP→Thor 2026-07-20. See `crate::pairing::seal_over_pair`.

/// A notification the hub delivers to a citizen's LCT MCP, or that the citizen
/// drains from its pending mailbox over the existing sealed channel (push and
/// poll are the same mailbox — push is the optimization, poll is the floor).
///
/// This is the **citizen-side wire shape** for HUB's notification leg: it
/// carries the `pair_id` (which channel to open it on) and the `sealed`
/// `ReferencedAct.sealed_body`. The citizen opens `sealed` with its member
/// keypair via [`HubChannel::open_notification`].
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Notification {
    /// The channel the body was sealed on (selects the session key to open it).
    pub pair_id: Uuid,
    /// The act kind, in the clear so the citizen can route/filter without
    /// opening the body (e.g. "notify:intro_accepted", "notify:pair_message").
    pub kind: String,
    /// The sealed `ReferencedAct.sealed_body` (base64); opened by the recipient.
    pub sealed: String,
    /// Optional clear pointer to off-channel substance (forum URL, /pairs/:id).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pointer_uri: Option<String>,
}

/// The receipt the citizen returns after opening a [`Notification`] — sealed
/// back to the hub so delivery is confirmed (un-acked notifications stay queued
/// in the hub's per-citizen mailbox and are re-delivered or polled).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct NotificationAck {
    /// Echoes the act being acknowledged (from the opened body).
    pub act_id: Uuid,
    /// Receipt time (the citizen's clock; informational).
    pub received_at: DateTime<Utc>,
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

/// Which key signs member-tier acts (join, `profile push`) to a given hub.
///
/// The hub pins exactly **one** verifying key per member LCT, and every envelope
/// that member signs verifies against it (`web4/hub` `MapResolver`: one `Lct`
/// per `signer_lct_id`, `insert` overwrites). A member whose non-interactive mesh
/// watcher must use a raw on-disk *channel* key — a systemd service can't open
/// the passphrase-sealed vault — has that **channel key** pinned. So its
/// interactive acts must sign with the *same* channel key, not the sealed vault
/// identity, or the hub returns `BadSignature`/401. Defaulting to the vault
/// identity keeps normal members (who pinned `ai_identity`) unchanged.
/// See forum/legion-to-sprout-reconcile-decision-a-*-2026-07-05.
#[derive(Clone, Debug, Serialize, Deserialize, Default, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum MemberKeySource {
    /// Sign with `ai_identity_secret` from the sealed vault — the key
    /// `hestia hub join` pins for a normal member. Default.
    #[default]
    VaultIdentity,
    /// Sign with a raw 32-byte Ed25519 seed file — the operational channel key
    /// pinned for a member running a non-interactive mesh watcher.
    ChannelKeyFile { path: String },
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
    /// Which key signs member-tier acts to this hub (defaults to the sealed
    /// vault identity; backward-compatible for connections saved before this).
    #[serde(default)]
    pub member_key_source: MemberKeySource,
}

/// Multi-hub connection store — persisted at `~/.hestia/hubs.json`.
#[derive(Debug, Serialize, Deserialize, Default)]
pub struct HubStore {
    pub connections: Vec<HubConnection>,
}

impl HubStore {
    /// Load hub connections from the vault (migrating a legacy `hubs.json`).
    pub fn load(vault: &crate::vault::Vault) -> Result<Self> {
        crate::vault::load_doc(vault, "presence", "hubs", "hubs.json")
    }

    /// Persist hub connections as an encrypted vault document.
    pub fn save(&self, vault: &mut crate::vault::Vault) -> Result<()> {
        crate::vault::save_doc(vault, "presence", "hubs", "hubs.json", self)
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
        let url = format!(
            "{}/.well-known/web4-hub.json",
            base_url.trim_end_matches('/')
        );
        let resp = self
            .http
            .get(&url)
            .send()
            .await
            .with_context(|| format!("connecting to {url}"))?;

        if !resp.status().is_success() {
            anyhow::bail!("hub discovery failed: HTTP {}", resp.status());
        }

        resp.json::<HubInfo>()
            .await
            .with_context(|| format!("parsing hub info from {url}"))
    }

    /// Request a challenge nonce from the hub.
    pub async fn challenge(
        &self,
        rest_endpoint: &str,
        for_lct_id: Uuid,
    ) -> Result<ChallengeResponse> {
        let url = format!("{}/auth/challenge", rest_endpoint);
        let body = serde_json::json!({ "for_lct_id": for_lct_id.to_string() });

        let resp = self
            .http
            .post(&url)
            .json(&body)
            .send()
            .await
            .with_context(|| format!("requesting challenge from {url}"))?;

        if !resp.status().is_success() {
            anyhow::bail!("challenge request failed: HTTP {}", resp.status());
        }

        resp.json::<ChallengeResponse>()
            .await
            .with_context(|| "parsing challenge response")
    }

    /// Self-add as a member (V2-12). Signs a `member_join_request` envelope
    /// with the member keypair and POSTs to `/v1/hubs/{id}/members/join`. The
    /// hub bootstraps verification from the supplied pubkey and pins it via a
    /// Sovereign-signed `MemberAdded`, so subsequent self-attested acts (e.g.
    /// `push_profile`) verify against the resolver.
    pub async fn join(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        member_lct_id: Uuid,
        member_keypair: &KeyPair,
        name: Option<String>,
    ) -> Result<JoinOutcome> {
        let rest = rest_endpoint.trim_end_matches('/');
        let challenge = self.challenge(rest, member_lct_id).await?;

        let mut payload = serde_json::json!({
            "action": "member_join_request",
            "member_lct_id": member_lct_id,
            "member_pubkey_hex": member_keypair.verifying_key().to_hex(),
        });
        if let Some(n) = name {
            payload["name"] = serde_json::Value::String(n);
        }

        let envelope =
            SignedEnvelope::create(challenge.nonce, payload, member_lct_id, member_keypair);

        let url = format!("{rest}/hubs/{hub_id}/members/join");
        let resp = self
            .http
            .post(&url)
            .json(&envelope)
            .send()
            .await
            .with_context(|| format!("posting join to {url}"))?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        let body: serde_json::Value =
            serde_json::from_str(&text).unwrap_or(serde_json::Value::Null);

        // 202 = the hub verified our request but hub law escalates admission
        // to the Sovereign (not auto-admitted). Distinct from a hard failure.
        if status.as_u16() == 202 {
            let reason = body
                .get("error")
                .and_then(|v| v.as_str())
                .or_else(|| body.get("reason").and_then(|v| v.as_str()))
                .unwrap_or("admission escalated to Sovereign")
                .to_string();
            return Ok(JoinOutcome::Escalated { reason });
        }
        if !status.is_success() {
            anyhow::bail!("hub /members/join returned HTTP {status}: {text}");
        }
        Ok(JoinOutcome::Admitted(body))
    }

    /// Push the member-tier profile to a hub as a `MemberProfileUpdated` act.
    ///
    /// Full self-attested act flow: mint a challenge nonce, build the
    /// `update_profile` payload (member-visible fields only — see
    /// `ProfileStore::hub_fields`), sign with the member keypair, and POST the
    /// signed envelope to `/v1/hubs/{hub_id}/events`. The hub merges the fields
    /// into the member's profile for `find_members` discovery.
    ///
    /// Only public + member-visible links travel; trusted/private stay home.
    pub async fn push_profile(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        member_lct_id: Uuid,
        member_keypair: &KeyPair,
        fields: std::collections::BTreeMap<String, String>,
    ) -> Result<serde_json::Value> {
        let rest = rest_endpoint.trim_end_matches('/');

        // 1. Challenge nonce, bound to our LCT.
        let challenge = self.challenge(rest, member_lct_id).await?;

        // 2. Build the update_profile action payload.
        let payload = serde_json::json!({
            "action": "update_profile",
            "member_lct_id": member_lct_id,
            "fields": fields,
        });

        // 3. Sign (nonce ++ canonical(payload)) — matches the hub's
        //    SignedEnvelope::signing_bytes exactly.
        let envelope =
            SignedEnvelope::create(challenge.nonce, payload, member_lct_id, member_keypair);

        // 4. POST the envelope directly to /events (not wrapped).
        let url = format!("{rest}/hubs/{hub_id}/events");
        let resp = self
            .http
            .post(&url)
            .json(&envelope)
            .send()
            .await
            .with_context(|| format!("posting profile act to {url}"))?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            anyhow::bail!("hub /events returned HTTP {status}: {text}");
        }
        serde_json::from_str(&text).with_context(|| "parsing /events response")
    }

    /// Submit a signed envelope to a hub endpoint.
    pub async fn submit_signed(
        &self,
        url: &str,
        envelope: &SignedEnvelope,
    ) -> Result<serde_json::Value> {
        let resp = self
            .http
            .post(url)
            .json(&serde_json::json!({ "envelope": envelope }))
            .send()
            .await
            .with_context(|| format!("submitting to {url}"))?;

        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();

        if !status.is_success() {
            anyhow::bail!("hub returned HTTP {status}: {body}");
        }

        serde_json::from_str(&body)
            .unwrap_or(serde_json::Value::Null)
            .pipe(Ok)
    }

    /// Register a delegation with the hub so it can verify agent signatures.
    pub async fn register_delegation(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        envelope: &SignedEnvelope,
    ) -> Result<()> {
        let url = format!("{}/hubs/{}/delegations", rest_endpoint, hub_id);
        let resp = self
            .http
            .post(&url)
            .json(&serde_json::json!({ "envelope": envelope }))
            .send()
            .await
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
    /// Resolve a member LCT by display name via the hub roster
    /// (`GET {base}/tools/list_members`). Exact (case-insensitive) name match
    /// first, then a unique prefix (`thor` → `thor-sage`); an ambiguous prefix
    /// fails closed. Mirrors the mesh `hub-notify.sh` fallback so a peer name
    /// resolves the same way whether the sender is the shell watcher or hestia.
    pub async fn resolve_member_by_name(&self, base_url: &str, name: &str) -> Result<Uuid> {
        let url = format!("{}/tools/list_members", base_url.trim_end_matches('/'));
        let resp = self
            .http
            .get(&url)
            .send()
            .await
            .with_context(|| format!("listing members at {url}"))?;
        if !resp.status().is_success() {
            anyhow::bail!("hub /tools/list_members returned HTTP {}", resp.status());
        }
        let body: serde_json::Value = resp.json().await.context("parsing list_members response")?;
        let members = body
            .get("members")
            .and_then(|m| m.as_array())
            .ok_or_else(|| anyhow::anyhow!("list_members response has no `members` array"))?;
        let want = name.to_lowercase();
        let name_of = |m: &serde_json::Value| {
            m.get("name")
                .and_then(|n| n.as_str())
                .unwrap_or("")
                .to_lowercase()
        };
        let lct_of = |m: &serde_json::Value| {
            m.get("lct_id")
                .and_then(|l| l.as_str())
                .and_then(|s| Uuid::parse_str(s).ok())
        };
        if let Some(m) = members.iter().find(|m| name_of(m) == want) {
            return lct_of(m).ok_or_else(|| anyhow::anyhow!("member '{name}' has no valid lct_id"));
        }
        let pref: Vec<&serde_json::Value> = members
            .iter()
            .filter(|m| name_of(m).starts_with(&want))
            .collect();
        match pref.as_slice() {
            [m] => lct_of(m).ok_or_else(|| anyhow::anyhow!("member '{name}' has no valid lct_id")),
            [] => anyhow::bail!("no hub member matches name '{name}'"),
            _ => anyhow::bail!(
                "ambiguous member name '{name}' — matches {} members; use the LCT id",
                pref.len()
            ),
        }
    }

    pub async fn channel_query(
        &self,
        rest_endpoint: &str,
        channel: &HubChannel,
        my: &KeyPair,
        my_lct_id: Uuid,
        tool: &str,
        args: serde_json::Value,
    ) -> Result<serde_json::Value> {
        // H-007 (mesh-freshness): the request carries `nonce` + `issued_at`
        // (see `channel_inner_request`) so the hub's ReplayGuard can dedup a
        // re-sealed write and reject out-of-window requests.
        let request = channel_inner_request(tool, args);
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
        let resp = self
            .http
            .post(&url)
            .json(&body)
            .send()
            .await
            .with_context(|| format!("posting channel query to {url}"))?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            anyhow::bail!("hub channel returned HTTP {status}: {text}");
        }
        let out: ChannelResponseBody =
            serde_json::from_str(&text).with_context(|| "parsing sealed channel response")?;
        channel.open_response(my, &out.sealed)
    }

    /// Present a constellation attestation over the channel for assurance-tier
    /// resolution (MFA). Flow:
    /// 1. `constellation_challenge` → hub returns a fresh nonce
    /// 2. Build the attestation locally (owner signs, devices co-sign)
    /// 3. `present_constellation` → hub verifies sigs, derives the assurance
    ///    tier, binds it to this channel's pair_id
    ///
    /// Returns the hub's response (granted assurance tier + validity window).
    pub async fn present_constellation(
        &self,
        rest_endpoint: &str,
        channel: &HubChannel,
        my: &KeyPair,
        my_lct_id: Uuid,
        build_attestation: impl FnOnce(&str) -> Result<crate::constellation::ConstellationAttestation>,
    ) -> Result<serde_json::Value> {
        // Step 1: get a challenge nonce from the hub (over the channel,
        // so even the challenge exchange is sealed).
        let challenge = self
            .channel_query(
                rest_endpoint,
                channel,
                my,
                my_lct_id,
                "constellation_challenge",
                serde_json::json!({}),
            )
            .await?;
        let nonce = challenge
            .get("nonce")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("hub challenge response missing nonce"))?;

        // Step 2: caller builds + signs the attestation against that nonce.
        let attestation = build_attestation(nonce)?;

        // Step 3: present it.
        self.channel_query(
            rest_endpoint,
            channel,
            my,
            my_lct_id,
            "present_constellation",
            serde_json::to_value(&attestation)?,
        )
        .await
    }

    /// Publish one LCT to the hub registry — the live half of the
    /// `LctPublished` seam (`lct_publish.rs` builds and self-checks the
    /// payload; this sends it). One challenge nonce and one [`SignedEnvelope`]
    /// per payload (nonces are single-use), and the envelope is POSTed
    /// DIRECTLY as the body — the hub's route takes `Json<SignedEnvelope>`,
    /// not an `{"envelope": …}` wrapper.
    ///
    /// The hub binds `payload.published_by` to `envelope.signer_lct_id`
    /// (hard 403 on mismatch), so callers must build the payload with the
    /// SAME identity that signs here — see [`resolve_publish_identity`].
    pub async fn publish_lct(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        signer_lct_id: Uuid,
        keypair: &KeyPair,
        payload: &crate::lct_publish::LctPublishPayload,
    ) -> Result<LctPublishAccepted> {
        let rest = rest_endpoint.trim_end_matches('/');
        let challenge = self.challenge(rest, signer_lct_id).await?;
        let envelope = SignedEnvelope::create(
            challenge.nonce,
            serde_json::to_value(payload)?,
            signer_lct_id,
            keypair,
        );
        let url = format!("{rest}/hubs/{hub_id}/lcts/publish");
        let resp = self
            .http
            .post(&url)
            .json(&envelope)
            .send()
            .await
            .with_context(|| format!("posting lct publish to {url}"))?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            anyhow::bail!("hub /lcts/publish returned HTTP {status}: {text}");
        }
        serde_json::from_str(&text).with_context(|| "parsing /lcts/publish response")
    }

    /// List the hub registry (`GET /v1/hubs/{hub_id}/lcts`). Read-only —
    /// used after a publish to verify what the registry actually serves,
    /// rather than trusting the acceptance receipts alone.
    pub async fn list_lcts(&self, rest_endpoint: &str, hub_id: Uuid) -> Result<serde_json::Value> {
        let url = format!(
            "{}/hubs/{}/lcts",
            rest_endpoint.trim_end_matches('/'),
            hub_id
        );
        let resp = self
            .http
            .get(&url)
            .send()
            .await
            .with_context(|| format!("listing registry at {url}"))?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            anyhow::bail!("hub /lcts returned HTTP {status}: {text}");
        }
        serde_json::from_str(&text).with_context(|| "parsing /lcts response")
    }

    /// Resolve one LCT document from the registry by canonical id
    /// (`GET /v1/hubs/:id/lcts/:lct_id`). The offline-verifiable path a recipient
    /// uses to resolve a peer's OPERATIONAL key (ruling B / #540) for opening a
    /// peer-sealed secret — no hub-private roster, the published vouch is the
    /// authority.
    pub async fn resolve_lct(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        lct_id: &str,
    ) -> Result<web4_core::Lct> {
        let url = format!(
            "{}/hubs/{}/lcts/{}",
            rest_endpoint.trim_end_matches('/'),
            hub_id,
            lct_id
        );
        let resp = self
            .http
            .get(&url)
            .send()
            .await
            .with_context(|| format!("resolving LCT at {url}"))?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            anyhow::bail!("hub /lcts/:id returned HTTP {status}: {text}");
        }
        // The registry serves { lct_id, document, provenance, ... }.
        let v: serde_json::Value =
            serde_json::from_str(&text).context("parsing /lcts/:id response")?;
        let doc = v.get("document").cloned().unwrap_or(v);
        serde_json::from_value(doc).context("parsing resolved LCT document")
    }

    /// Resolve a peer's pinned static pairing pubkey by their hub-member
    /// **uuid** — the v2 sealed-channel authentication half. Single keyed lookup
    /// against the hub pin map (`GET /v1/hubs/:id/members/:uuid/pubkey`), keyed
    /// by the same member uuid the hub membership gate authorizes.
    ///
    /// Supersedes the old `resolve_lct_by_member_uuid` registry scan, which
    /// matched `document.id == member_uuid` — structurally unsatisfiable, since a
    /// member uuid only ever appears as a document's `published_by`, never as its
    /// own `doc.id`. (Thor's repro, 2026-07-19.) The pin is also the unambiguous
    /// source: a publisher's constellation carries many keys across its docs;
    /// the pin is the one the hub actually verifies acts against.
    ///
    /// Fail-closed: a 404 (peer unpinned — sovereign, not yet admitted) is an
    /// error, never a guess.
    pub async fn resolve_member_pubkey(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        member_uuid: Uuid,
    ) -> Result<PublicKey> {
        let url = format!(
            "{}/hubs/{}/members/{}/pubkey",
            rest_endpoint.trim_end_matches('/'),
            hub_id,
            member_uuid
        );
        let resp = self
            .http
            .get(&url)
            .send()
            .await
            .with_context(|| format!("resolving member pubkey at {url}"))?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            anyhow::bail!(
                "hub /members/:uuid/pubkey returned HTTP {status}: {text} \
                 (peer not an admitted/pinned member?)"
            );
        }
        let v: serde_json::Value =
            serde_json::from_str(&text).context("parsing /members/:uuid/pubkey response")?;
        let hex_str = v
            .get("pubkey_hex")
            .and_then(|x| x.as_str())
            .ok_or_else(|| anyhow::anyhow!("member pubkey response missing pubkey_hex"))?;
        let bytes: [u8; 32] = hex::decode(hex_str)
            .ok()
            .and_then(|b| b.try_into().ok())
            .ok_or_else(|| anyhow::anyhow!("member pubkey_hex is not 32-byte hex"))?;
        PublicKey::from_bytes(&bytes).context("decoding member pinned pubkey")
    }

    // -----------------------------------------------------------------------
    // Paired-channel broker client (CBP sprints A–F). The hub is the
    // authentication controller: it admits the pairing under chapter law and
    // establishes the sealed channel; these are the member-side calls that
    // drive it. All mutating calls are challenge → SignedEnvelope → direct POST
    // (the pair endpoints take `Json<SignedEnvelope>`). See `crate::pairing`.
    // -----------------------------------------------------------------------

    /// Sign a payload for a pair endpoint: fetch a fresh challenge for our
    /// member uuid and wrap the payload in a `SignedEnvelope`.
    async fn sign_pair_payload(
        &self,
        rest_endpoint: &str,
        our_uuid: Uuid,
        our_kp: &KeyPair,
        payload: serde_json::Value,
    ) -> Result<SignedEnvelope> {
        let challenge = self.challenge(rest_endpoint, our_uuid).await?;
        Ok(SignedEnvelope::create(
            challenge.nonce,
            payload,
            our_uuid,
            our_kp,
        ))
    }

    fn pairs_base(rest_endpoint: &str, hub_id: Uuid) -> String {
        format!(
            "{}/hubs/{}/pairs",
            rest_endpoint.trim_end_matches('/'),
            hub_id
        )
    }

    /// `POST /pairs/request` — propose a pairing (carrying our initiator
    /// ephemeral pubkey). Returns the hub-assigned `pair_id`.
    pub async fn pair_request(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        our_uuid: Uuid,
        our_kp: &KeyPair,
        payload: &crate::pairing::PairRequestPayload,
    ) -> Result<Uuid> {
        let env = self
            .sign_pair_payload(
                rest_endpoint,
                our_uuid,
                our_kp,
                serde_json::to_value(payload)?,
            )
            .await?;
        let url = format!("{}/request", Self::pairs_base(rest_endpoint, hub_id));
        let resp = self
            .http
            .post(&url)
            .json(&env)
            .send()
            .await
            .with_context(|| format!("POST {url}"))?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            anyhow::bail!("pair_request failed: HTTP {status}: {text}");
        }
        let accepted: crate::pairing::PairAccepted =
            serde_json::from_str(&text).context("parsing PairAccepted")?;
        Ok(accepted.pair_id)
    }

    /// `POST /pairs/:id/confirm` — accept a pairing (carrying our counterparty
    /// ephemeral pubkey). After this the channel is active for both sides.
    pub async fn pair_confirm(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        our_uuid: Uuid,
        our_kp: &KeyPair,
        pair_id: Uuid,
        payload: &crate::pairing::PairConfirmPayload,
    ) -> Result<()> {
        let env = self
            .sign_pair_payload(
                rest_endpoint,
                our_uuid,
                our_kp,
                serde_json::to_value(payload)?,
            )
            .await?;
        let url = format!(
            "{}/{}/confirm",
            Self::pairs_base(rest_endpoint, hub_id),
            pair_id
        );
        let resp = self
            .http
            .post(&url)
            .json(&env)
            .send()
            .await
            .with_context(|| format!("POST {url}"))?;
        let status = resp.status();
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            anyhow::bail!("pair_confirm failed: HTTP {status}: {text}");
        }
        Ok(())
    }

    /// `POST /pairs/:id/revoke` — end the pair. Either party may revoke; after
    /// this the channel is inactive and the caller should wipe its ephemeral
    /// secret (forward secrecy). The hub records the revocation kind + reason.
    pub async fn pair_revoke(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        our_uuid: Uuid,
        our_kp: &KeyPair,
        pair_id: Uuid,
        payload: &crate::pairing::PairRevokePayload,
    ) -> Result<()> {
        let env = self
            .sign_pair_payload(
                rest_endpoint,
                our_uuid,
                our_kp,
                serde_json::to_value(payload)?,
            )
            .await?;
        let url = format!(
            "{}/{}/revoke",
            Self::pairs_base(rest_endpoint, hub_id),
            pair_id
        );
        let resp = self
            .http
            .post(&url)
            .json(&env)
            .send()
            .await
            .with_context(|| format!("POST {url}"))?;
        let status = resp.status();
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            anyhow::bail!("pair_revoke failed: HTTP {status}: {text}");
        }
        Ok(())
    }

    /// `GET /pairs/:id` — the pair detail carrying both sides' ephemeral pubkeys
    /// (the hub-brokered pairing keys) and the effective status.
    pub async fn get_pair(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        pair_id: Uuid,
    ) -> Result<crate::pairing::PairView> {
        let url = format!("{}/{}", Self::pairs_base(rest_endpoint, hub_id), pair_id);
        let resp = self
            .http
            .get(&url)
            .send()
            .await
            .with_context(|| format!("GET {url}"))?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            anyhow::bail!("get_pair failed: HTTP {status}: {text}");
        }
        serde_json::from_str(&text).context("parsing PairView")
    }

    /// `POST /pairs/:id/messages` — relay a sealed body over the active channel.
    /// The hub stores it opaque and witnesses only its `payload_hash`.
    pub async fn post_pair_message(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        our_uuid: Uuid,
        our_kp: &KeyPair,
        pair_id: Uuid,
        body_b64: String,
    ) -> Result<()> {
        let payload = crate::pairing::PairMessagePayload {
            action: "pair_message",
            pair_id,
            body: body_b64,
        };
        let env = self
            .sign_pair_payload(
                rest_endpoint,
                our_uuid,
                our_kp,
                serde_json::to_value(&payload)?,
            )
            .await?;
        let url = format!(
            "{}/{}/messages",
            Self::pairs_base(rest_endpoint, hub_id),
            pair_id
        );
        let resp = self
            .http
            .post(&url)
            .json(&env)
            .send()
            .await
            .with_context(|| format!("POST {url}"))?;
        let status = resp.status();
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            anyhow::bail!("post_pair_message failed: HTTP {status}: {text}");
        }
        Ok(())
    }

    /// `GET /pairs/:id/messages?since=` — fetch relayed sealed bodies. Caller
    /// opens each with `crate::pairing::open_over_pair`.
    pub async fn get_pair_messages(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        pair_id: Uuid,
        since: Option<u64>,
    ) -> Result<Vec<crate::pairing::PairMessageView>> {
        let mut url = format!(
            "{}/{}/messages",
            Self::pairs_base(rest_endpoint, hub_id),
            pair_id
        );
        if let Some(s) = since {
            url.push_str(&format!("?since={s}"));
        }
        let resp = self
            .http
            .get(&url)
            .send()
            .await
            .with_context(|| format!("GET {url}"))?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            anyhow::bail!("get_pair_messages failed: HTTP {status}: {text}");
        }
        let parsed: crate::pairing::PairMessagesResponse =
            serde_json::from_str(&text).context("parsing PairMessagesResponse")?;
        Ok(parsed.messages)
    }

    // -----------------------------------------------------------------------
    // Constellation device enrollment (GPT self-authentication fix, Phase 3).
    // The owner (this member) commits a device's pubkey + class to the hub as
    // AUTHORITATIVE state the constellation verifier resolves against — so a
    // presented attestation can't self-authenticate its device facts. Self-
    // attested: the envelope signer IS the owner.
    // -----------------------------------------------------------------------

    /// `POST /constellation/enroll` — enroll (or rotate) one of our devices.
    /// Returns the hub-assigned enrollment version.
    pub async fn enroll_device(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        our_uuid: Uuid,
        our_kp: &KeyPair,
        device_lct_id: Uuid,
        device_pubkey_hex: &str,
        device_class: &crate::constellation::DeviceType,
    ) -> Result<u64> {
        let payload = serde_json::json!({
            "action": "device_enroll",
            "device_lct_id": device_lct_id,
            "device_pubkey_hex": device_pubkey_hex,
            "device_class": device_class,
        });
        let env = self
            .sign_pair_payload(rest_endpoint, our_uuid, our_kp, payload)
            .await?;
        let url = format!(
            "{}/hubs/{}/constellation/enroll",
            rest_endpoint.trim_end_matches('/'),
            hub_id
        );
        let resp = self
            .http
            .post(&url)
            .json(&env)
            .send()
            .await
            .with_context(|| format!("POST {url}"))?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            anyhow::bail!("device_enroll failed: HTTP {status}: {text}");
        }
        let v: serde_json::Value =
            serde_json::from_str(&text).context("parsing enroll response")?;
        Ok(v.get("enrollment_version")
            .and_then(|x| x.as_u64())
            .unwrap_or(0))
    }

    /// `POST /constellation/revoke` — revoke one of our enrolled devices.
    pub async fn revoke_device(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        our_uuid: Uuid,
        our_kp: &KeyPair,
        device_lct_id: Uuid,
    ) -> Result<()> {
        let payload = serde_json::json!({
            "action": "device_revoke",
            "device_lct_id": device_lct_id,
        });
        let env = self
            .sign_pair_payload(rest_endpoint, our_uuid, our_kp, payload)
            .await?;
        let url = format!(
            "{}/hubs/{}/constellation/revoke",
            rest_endpoint.trim_end_matches('/'),
            hub_id
        );
        let resp = self
            .http
            .post(&url)
            .json(&env)
            .send()
            .await
            .with_context(|| format!("POST {url}"))?;
        let status = resp.status();
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            anyhow::bail!("device_revoke failed: HTTP {status}: {text}");
        }
        Ok(())
    }

    /// `GET /constellation/:owner/devices` — the owner's enrolled devices as the
    /// hub holds them (the authoritative set the verifier resolves against).
    pub async fn list_enrolled_devices(
        &self,
        rest_endpoint: &str,
        hub_id: Uuid,
        owner_uuid: Uuid,
    ) -> Result<serde_json::Value> {
        let url = format!(
            "{}/hubs/{}/constellation/{}/devices",
            rest_endpoint.trim_end_matches('/'),
            hub_id,
            owner_uuid
        );
        let resp = self
            .http
            .get(&url)
            .send()
            .await
            .with_context(|| format!("GET {url}"))?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            anyhow::bail!("list enrolled devices failed: HTTP {status}: {text}");
        }
        serde_json::from_str(&text).context("parsing enrolled devices response")
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

/// The hub's acceptance receipt for one registry publish — mirrors the hub's
/// `LctPublishAccepted` (web4 `hub-daemon` rest.rs) field-for-field.
#[derive(Clone, Debug, Deserialize)]
pub struct LctPublishAccepted {
    pub lct_id: String,
    /// The version this publish landed as (1 on first publish of a key;
    /// republishing the same key overwrites in place and bumps this).
    pub version: u32,
    pub entry_index: u64,
    pub entry_hash: String,
}

/// Decide which identity signs — and is named as `published_by` in — a
/// registry publish through a connection, and whether the connection's cached
/// `our_lct_id` needs repair.
///
/// The hub rejects `published_by != envelope.signer_lct_id` (403), so both
/// must come from ONE source of truth:
/// - [`MemberKeySource::VaultIdentity`]: the vault's `ai_identity_lct_id` is
///   authoritative — that is the LCT whose key the hub pinned at join. A
///   diverging `our_lct_id` is a stale cache (the 2026-07-13 live dry-run
///   caught ours holding the HUB peer's member id) and is flagged for repair.
/// - [`MemberKeySource::ChannelKeyFile`]: the pinned key is the channel key
///   bound to `our_lct_id`; there is no vault-side authority to repair from.
///
/// Returns `(signer_lct_id, needs_repair)`. Pure, so the repair decision is
/// testable without a vault.
pub fn resolve_publish_identity(
    conn_our_lct_id: Uuid,
    source: &MemberKeySource,
    vault_identity_lct_id: Option<Uuid>,
) -> Result<(Uuid, bool)> {
    match source {
        MemberKeySource::VaultIdentity => {
            let id = vault_identity_lct_id.ok_or_else(|| {
                anyhow::anyhow!(
                    "vault has no ai_identity_lct_id — run `hestia init --ai` before publishing"
                )
            })?;
            Ok((id, id != conn_our_lct_id))
        }
        MemberKeySource::ChannelKeyFile { .. } => Ok((conn_our_lct_id, false)),
    }
}

trait Pipe: Sized {
    fn pipe<F, R>(self, f: F) -> R
    where
        F: FnOnce(Self) -> R,
    {
        f(self)
    }
}
impl<T> Pipe for T {}

/// Build the sealed `ChannelInner` request body for a hub tool call, stamped with
/// the H-007 mesh-freshness fields (`nonce` + `issued_at`) so the hub's
/// ReplayGuard can dedup a re-sealed write and reject out-of-window requests.
/// Byte-compatible with the hub's `ChannelInner` (rest.rs) + the `channel_client`
/// example. Fields are serde-optional on the hub, so this is Phase-1 backward-
/// compatible; enforcement (Phase 2) lands only once every write-sender emits them.
///
/// INVARIANT: every sealed channel request MUST be built here. This is the single
/// choke point where freshness fields are stamped — any future sealed path that
/// bypasses this builder would be silently non-compliant under Phase-2 enforcement.
fn channel_inner_request(tool: &str, args: serde_json::Value) -> serde_json::Value {
    serde_json::json!({
        "tool": tool,
        "args": args,
        "nonce": Uuid::new_v4().to_string(),
        "issued_at": Utc::now().to_rfc3339(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use web4_core::crypto::KeyPair;

    // [retired 2026-07-20] sealed_secret_roundtrips_e2e_and_fails_closed tested the
    // send_secret primitives; superseded by `crate::pairing`'s pair-channel tests.

    /// The registry seam's identity rule: `published_by` == envelope signer
    /// (hub 403s a mismatch), so a vault-identity member signs as the vault's
    /// `ai_identity_lct_id` and a diverging store cache is REPAIRED — the
    /// exact defect the 2026-07-13 live dry-run caught (store held the HUB
    /// peer's member id).
    #[test]
    fn publish_identity_vault_source_repairs_a_stale_store_entry() {
        let vault_id = Uuid::new_v4();
        let stale = Uuid::new_v4(); // e.g. the peer hub's member id
        let (signer, repair) =
            resolve_publish_identity(stale, &MemberKeySource::VaultIdentity, Some(vault_id))
                .unwrap();
        assert_eq!(signer, vault_id, "the vault identity is authoritative");
        assert!(repair, "a diverging cache must be flagged for repair");
        // Idempotent: once repaired, a second resolve is a no-op.
        let (signer2, repair2) =
            resolve_publish_identity(vault_id, &MemberKeySource::VaultIdentity, Some(vault_id))
                .unwrap();
        assert_eq!(signer2, vault_id);
        assert!(!repair2, "a matching cache needs no repair");
    }

    #[test]
    fn publish_identity_channel_key_source_trusts_the_store() {
        // A channel-key member's pinned key is bound to `our_lct_id`; the
        // vault identity (even if present) is NOT the pinned identity here.
        let ours = Uuid::new_v4();
        let (signer, repair) = resolve_publish_identity(
            ours,
            &MemberKeySource::ChannelKeyFile { path: "/k".into() },
            Some(Uuid::new_v4()),
        )
        .unwrap();
        assert_eq!(signer, ours);
        assert!(!repair);
    }

    #[test]
    fn publish_identity_vault_source_without_identity_refuses() {
        let err = resolve_publish_identity(Uuid::new_v4(), &MemberKeySource::VaultIdentity, None)
            .unwrap_err();
        assert!(err.to_string().contains("ai_identity_lct_id"));
    }

    /// Wire-shape lock for the send path: what `publish_lct` POSTs is the
    /// BARE `SignedEnvelope` the hub's route deserializes — payload fields
    /// verbatim at `.payload`, signer at `.signer_lct_id`, no `{"envelope":…}`
    /// wrapper — and the hub's acceptance receipt parses field-for-field.
    #[test]
    fn publish_envelope_wire_shape_is_the_bare_signed_envelope() {
        let (mut doc, kp) = web4_core::Lct::new(web4_core::EntityType::Role, None);
        doc.sign_binding(&kp);
        let signer = Uuid::new_v4();
        let payload = crate::lct_publish::LctPublishPayload {
            lct_id: doc.lct_id(),
            document: doc,
            published_by: signer,
            provenance: crate::lct_publish::LctProvenance::SelfIssued,
            published_at: Utc::now(),
        };
        let envelope = SignedEnvelope::create(
            "nonce-1".into(),
            serde_json::to_value(&payload).unwrap(),
            signer,
            &KeyPair::generate(),
        );
        let v = serde_json::to_value(&envelope).unwrap();
        for key in ["challenge_nonce", "payload", "signature", "signer_lct_id"] {
            assert!(v.get(key).is_some(), "envelope field `{key}` on the wire");
        }
        assert_eq!(v["payload"]["lct_id"], payload.lct_id);
        assert_eq!(
            v["payload"]["published_by"], v["signer_lct_id"],
            "published_by must equal the envelope signer or the hub 403s"
        );

        let receipt: LctPublishAccepted = serde_json::from_str(
            r#"{"lct_id":"lct:web4:mb32:x","version":1,"entry_index":481,"entry_hash":"abc"}"#,
        )
        .unwrap();
        assert_eq!(receipt.version, 1);
        assert_eq!(receipt.entry_index, 481);
    }

    /// H-007 regression guard: every sealed channel request must carry a fresh,
    /// unique `nonce` + an `issued_at`, or the hub's replay defense is toothless.
    #[test]
    fn channel_inner_request_carries_fresh_h007_fields() {
        let r = channel_inner_request("record_reputation", serde_json::json!({"x": 1}));
        assert_eq!(r["tool"], "record_reputation");
        assert_eq!(r["args"]["x"], 1);
        assert!(
            r.get("nonce")
                .and_then(|n| n.as_str())
                .is_some_and(|s| !s.is_empty()),
            "nonce must be present + non-empty"
        );
        assert!(
            r.get("issued_at").and_then(|t| t.as_str()).is_some(),
            "issued_at must be present"
        );
        // Distinct per call — a fixed nonce would BE the replay token it guards against.
        let r2 = channel_inner_request("record_reputation", serde_json::json!({"x": 1}));
        assert_ne!(
            r["nonce"], r2["nonce"],
            "each request must get a unique nonce"
        );
    }

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
            &hub,
            &member.verifying_key(),
            pair_id,
            &Sealed::from_base64(&sealed_b64).unwrap(),
        )
        .unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&opened).unwrap(),
            request
        );

        // Hub seals a response → member opens it.
        let response = serde_json::json!({"members": [{"lct": "abc", "score": 0.82}]});
        let resp_sealed = pair_channel::seal(
            &hub,
            &member.verifying_key(),
            pair_id,
            &serde_json::to_vec(&response).unwrap(),
        )
        .unwrap();
        let got = member_view
            .open_response(&member, &resp_sealed.to_base64())
            .unwrap();
        assert_eq!(got, response);

        // Wrong pair_id must fail to open (AEAD auth) — confirms the salt binds.
        let wrong = HubChannel {
            pair_id: Uuid::new_v4(),
            ..member_view.clone()
        };
        assert!(
            wrong
                .open_response(&member, &resp_sealed.to_base64())
                .is_err()
        );
    }

    #[test]
    fn hub_pushes_a_notification_citizen_opens_and_acks() {
        // The notification leg: the hub→citizen direction. Same channel,
        // reversed — the hub seals a notice to the citizen's pinned pubkey, the
        // citizen opens it with its keypair and seals an ACK the hub can open.
        let citizen = KeyPair::generate();
        let hub = KeyPair::generate();
        let pair_id = Uuid::new_v4();
        let act_id = Uuid::new_v4();

        let citizen_view = HubChannel {
            hub_lct_id: Uuid::new_v4(),
            pair_id,
            hub_pubkey: hub.verifying_key(),
        };

        // Hub seals a notice body to the citizen and wraps it in a Notification.
        let body = serde_json::json!({"act_id": act_id, "text": "intro from Nomad accepted"});
        let sealed = pair_channel::seal(
            &hub,
            &citizen.verifying_key(),
            pair_id,
            &serde_json::to_vec(&body).unwrap(),
        )
        .unwrap();
        let notif = Notification {
            pair_id,
            kind: "notify:intro_accepted".into(),
            sealed: sealed.to_base64(),
            pointer_uri: Some("/v1/hubs/h/pairs/abc".into()),
        };

        // Citizen routes on the cleartext `kind`, then opens the sealed body.
        assert!(notif.kind.starts_with("notify:"));
        let opened = citizen_view
            .open_notification(&citizen, &notif.sealed)
            .unwrap();
        assert_eq!(opened, body);

        // Citizen seals an ACK → the hub opens it to mark delivered.
        let ack = NotificationAck {
            act_id,
            received_at: Utc::now(),
        };
        let ack_sealed = citizen_view.seal_ack(&citizen, &ack).unwrap();
        let hub_got = pair_channel::open(
            &hub,
            &citizen.verifying_key(),
            pair_id,
            &Sealed::from_base64(&ack_sealed).unwrap(),
        )
        .unwrap();
        let hub_ack: NotificationAck = serde_json::from_slice(&hub_got).unwrap();
        assert_eq!(hub_ack.act_id, act_id);

        // A foreign keypair cannot open the notice (confidentiality holds).
        let intruder = KeyPair::generate();
        assert!(
            citizen_view
                .open_notification(&intruder, &notif.sealed)
                .is_err()
        );
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
        let info_no_key = HubInfo {
            hub_pubkey_hex: None,
            ..info
        };
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
            member_key_source: Default::default(),
        });

        let json = serde_json::to_string(&store).unwrap();
        let recovered: HubStore = serde_json::from_str(&json).unwrap();
        assert_eq!(recovered.connections.len(), 1);
        assert_eq!(recovered.connections[0].url, "https://hub.example.com");
        assert_eq!(
            recovered.connections[0].member_key_source,
            MemberKeySource::VaultIdentity
        );
    }

    #[test]
    fn test_signed_envelope() {
        let kp = KeyPair::generate();
        let lct_id = Uuid::new_v4();
        let payload = serde_json::json!({"action": "join", "hub": "test"});

        let envelope = SignedEnvelope::create("nonce123".into(), payload.clone(), lct_id, &kp);

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
            member_key_source: Default::default(),
        });

        assert!(store.find_by_url("https://hub.example.com").is_some());
        assert!(store.find_by_url("https://other.com").is_none());
        assert!(store.find_by_id(id).is_some());
    }
}
