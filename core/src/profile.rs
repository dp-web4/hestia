//! Profile links — social/professional presence claims with tiered visibility.
//!
//! Links are part of a person's Web4 presence. Each link carries a platform,
//! URL, visibility tier, and verification status. When connecting to a hub or
//! responding to a peer, Hestia presents only the links appropriate to the
//! relationship context (MRH-scoped).
//!
//! Visibility tiers:
//! - `public` — anyone can see (GitHub, personal site)
//! - `member` — other members of hubs you're in
//! - `trusted` — entities above a T3 threshold
//! - `private` — never shared automatically

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::vault::Vault;

/// Vault namespace + name under which the profile is enclosed (vault doctrine —
/// no plaintext sidecar).
const PROFILE_NS: &str = "presence";
const PROFILE_NAME: &str = "profile";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Platform {
    GitHub,
    LinkedIn,
    Twitter,
    Bluesky,
    Mastodon,
    Website,
    Email,
    YouTube,
    Substack,
    Signal,
    Phone,
    Slack,
    Discord,
    Matrix,
    Telegram,
    Meetup,
    Luma,
    Eventbrite,
    Zoom,
    Custom(String),
}

impl Platform {
    pub fn as_str(&self) -> &str {
        match self {
            Platform::GitHub => "github",
            Platform::LinkedIn => "linkedin",
            Platform::Twitter => "twitter",
            Platform::Bluesky => "bluesky",
            Platform::Mastodon => "mastodon",
            Platform::Website => "website",
            Platform::Email => "email",
            Platform::YouTube => "youtube",
            Platform::Substack => "substack",
            Platform::Signal => "signal",
            Platform::Phone => "phone",
            Platform::Slack => "slack",
            Platform::Discord => "discord",
            Platform::Matrix => "matrix",
            Platform::Telegram => "telegram",
            Platform::Meetup => "meetup",
            Platform::Luma => "luma",
            Platform::Eventbrite => "eventbrite",
            Platform::Zoom => "zoom",
            Platform::Custom(s) => s,
        }
    }

    pub fn is_professional(&self) -> bool {
        matches!(
            self,
            Platform::GitHub | Platform::LinkedIn | Platform::Website
        )
    }
}

pub fn parse_platform(s: &str) -> Platform {
    match s.to_lowercase().as_str() {
        "github" => Platform::GitHub,
        "linkedin" => Platform::LinkedIn,
        "twitter" | "x" => Platform::Twitter,
        "bluesky" | "bsky" => Platform::Bluesky,
        "mastodon" => Platform::Mastodon,
        "website" | "web" | "site" => Platform::Website,
        "email" | "mail" => Platform::Email,
        "youtube" | "yt" => Platform::YouTube,
        "substack" => Platform::Substack,
        "signal" => Platform::Signal,
        "phone" | "tel" => Platform::Phone,
        "slack" => Platform::Slack,
        "discord" => Platform::Discord,
        "matrix" => Platform::Matrix,
        "telegram" => Platform::Telegram,
        "meetup" => Platform::Meetup,
        "luma" => Platform::Luma,
        "eventbrite" => Platform::Eventbrite,
        "zoom" => Platform::Zoom,
        other => Platform::Custom(other.to_string()),
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Visibility {
    Public,
    Member,
    Trusted,
    Private,
}

impl Visibility {
    pub fn as_str(&self) -> &str {
        match self {
            Visibility::Public => "public",
            Visibility::Member => "member",
            Visibility::Trusted => "trusted",
            Visibility::Private => "private",
        }
    }

    pub fn permits(&self, tier: &Visibility) -> bool {
        let rank = |v: &Visibility| match v {
            Visibility::Public => 0,
            Visibility::Member => 1,
            Visibility::Trusted => 2,
            Visibility::Private => 3,
        };
        rank(self) <= rank(tier)
    }
}

pub fn parse_visibility(s: &str) -> anyhow::Result<Visibility> {
    match s.to_lowercase().as_str() {
        "public" => Ok(Visibility::Public),
        "member" => Ok(Visibility::Member),
        "trusted" => Ok(Visibility::Trusted),
        "private" => Ok(Visibility::Private),
        other => anyhow::bail!(
            "unknown visibility: {other} (expected: public, member, trusted, private)"
        ),
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Verification {
    Claimed,
    SelfVerified,
    Attested { by: Uuid },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProfileOwner {
    Member,
    Community(Uuid),
    Group(Uuid),
    Role(Uuid),
    Event(Uuid),
}

impl Default for ProfileOwner {
    fn default() -> Self {
        Self::Member
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ProfileLink {
    pub id: Uuid,
    pub platform: Platform,
    pub url: String,
    pub label: Option<String>,
    pub visibility: Visibility,
    pub verification: Verification,
    pub added_at: DateTime<Utc>,
    #[serde(default)]
    pub owner: ProfileOwner,
    #[serde(default)]
    pub verification_evidence: Option<String>,
    #[serde(default)]
    pub expires_at: Option<DateTime<Utc>>,
    #[serde(default)]
    pub revoked_at: Option<DateTime<Utc>>,
}

impl ProfileLink {
    pub fn new(platform: Platform, url: &str, visibility: Visibility) -> Self {
        Self {
            id: Uuid::new_v4(),
            platform,
            url: url.to_string(),
            label: None,
            visibility,
            verification: Verification::Claimed,
            added_at: Utc::now(),
            owner: ProfileOwner::Member,
            verification_evidence: None,
            expires_at: None,
            revoked_at: None,
        }
    }

    pub fn with_label(mut self, label: &str) -> Self {
        self.label = Some(label.to_string());
        self
    }

    pub fn with_owner(mut self, owner: ProfileOwner) -> Self {
        self.owner = owner;
        self
    }

    pub fn with_self_verification(mut self, evidence: &str) -> anyhow::Result<Self> {
        let evidence = evidence.trim();
        if evidence.is_empty() {
            anyhow::bail!("self-verification requires an evidence reference");
        }
        self.verification = Verification::SelfVerified;
        self.verification_evidence = Some(evidence.to_string());
        Ok(self)
    }

    pub fn with_attestation(mut self, by: Uuid, evidence: &str) -> anyhow::Result<Self> {
        let evidence = evidence.trim();
        if evidence.is_empty() {
            anyhow::bail!("attestation requires an evidence reference");
        }
        self.verification = Verification::Attested { by };
        self.verification_evidence = Some(evidence.to_string());
        Ok(self)
    }

    pub fn with_expiry(mut self, expires_at: DateTime<Utc>) -> Self {
        self.expires_at = Some(expires_at);
        self
    }

    pub fn revoke(&mut self, at: DateTime<Utc>) {
        self.revoked_at = Some(at);
    }

    pub fn is_current(&self, now: DateTime<Utc>) -> bool {
        self.revoked_at.is_none() && self.expires_at.map_or(true, |expiry| expiry > now)
    }

    pub fn verification_is_evidenced(&self) -> bool {
        match self.verification {
            Verification::Claimed => true,
            Verification::SelfVerified | Verification::Attested { .. } => self
                .verification_evidence
                .as_deref()
                .is_some_and(|evidence| !evidence.trim().is_empty()),
        }
    }

    fn projection_is_safe(&self, tier: &Visibility) -> bool {
        self.visibility.permits(tier)
            && (matches!(self.owner, ProfileOwner::Member)
                || !matches!(self.visibility, Visibility::Member)
                || matches!(tier, Visibility::Private))
    }
}

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct ProfileStore {
    pub display_name: Option<String>,
    pub bio: Option<String>,
    pub links: Vec<ProfileLink>,
}

impl ProfileStore {
    /// Load the profile from the vault (migrating a legacy `profile.json` for
    /// older installs). The vault must be unlocked — nothing is read pre-unlock.
    pub fn load(vault: &Vault) -> anyhow::Result<Self> {
        crate::vault::load_doc(vault, PROFILE_NS, PROFILE_NAME, "profile.json")
    }

    /// Persist the profile as an encrypted vault document (and drop any legacy
    /// plaintext `profile.json`).
    pub fn save(&self, vault: &mut Vault) -> anyhow::Result<()> {
        crate::vault::save_doc(vault, PROFILE_NS, PROFILE_NAME, "profile.json", self)
    }

    pub fn add_link(&mut self, link: ProfileLink) {
        self.links.push(link);
    }

    pub fn remove_link(&mut self, id: Uuid) -> bool {
        let len = self.links.len();
        self.links.retain(|l| l.id != id);
        self.links.len() < len
    }

    /// Current, evidenced links safe to project at a given tier. Legacy claimed links remain
    /// visible; self-/attester-verified links with missing evidence do not. A foreign-owned
    /// member-only link is private-only because no external tier, including Trusted, proves
    /// shared membership with its owner.
    pub fn links_for_tier(&self, tier: &Visibility) -> Vec<&ProfileLink> {
        let now = Utc::now();
        self.links
            .iter()
            .filter(|l| l.is_current(now) && l.verification_is_evidenced() && l.projection_is_safe(tier))
            .collect()
    }

    /// Professional links only (GitHub, LinkedIn, Website) at a given tier.
    pub fn professional_links(&self, tier: &Visibility) -> Vec<&ProfileLink> {
        let now = Utc::now();
        self.links
            .iter()
            .filter(|l| {
                l.is_current(now)
                    && l.verification_is_evidenced()
                    && l.platform.is_professional()
                    && l.projection_is_safe(tier)
            })
            .collect()
    }

    /// Flatten the **member-tier** presentation into the hub's plain-language
    /// `MemberProfileUpdated` field map (used by `find_members` discovery).
    /// Only public + member-visible content goes — trusted/private stay home.
    /// Keys are deliberately human-readable (`name`, `bio`, `github`, …) per
    /// the hub's "not schematized" design. An empty map's fields clear nothing;
    /// to clear a field, push it with an empty value (hub merge semantics).
    pub fn hub_fields(&self) -> std::collections::BTreeMap<String, String> {
        let pres = self.present(&Visibility::Member);
        let mut fields = std::collections::BTreeMap::new();
        if let Some(n) = pres.display_name {
            fields.insert("name".to_string(), n);
        }
        if let Some(b) = pres.bio {
            fields.insert("bio".to_string(), b);
        }
        // Platform as key; multiple links of one platform → last wins (rare).
        for link in pres.links {
            fields.insert(link.platform, link.url);
        }
        fields
    }

    /// Non-lossy member-tier links for Hub projection (#563).
    pub fn hub_links(&self) -> Vec<PresentedLink> {
        self.present(&Visibility::Member).links
    }

    /// Build a presentation for a specific context — what to share with a hub or peer.
    pub fn present(&self, tier: &Visibility) -> ProfilePresentation {
        ProfilePresentation {
            display_name: self.display_name.clone(),
            bio: self.bio.clone(),
            links: self
                .links_for_tier(tier)
                .into_iter()
                .map(|l| PresentedLink {
                    platform: l.platform.as_str().to_string(),
                    url: l.url.clone(),
                    label: l.label.clone(),
                    verified: !matches!(l.verification, Verification::Claimed),
                    owner: l.owner.clone(),
                    visibility: l.visibility.clone(),
                    verification: l.verification.clone(),
                    verification_evidence: l.verification_evidence.clone(),
                    expires_at: l.expires_at,
                    revoked_at: l.revoked_at,
                })
                .collect(),
        }
    }
}

/// Tier-correct external projection with ownership, verification, and lifecycle intact.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ProfilePresentation {
    pub display_name: Option<String>,
    pub bio: Option<String>,
    pub links: Vec<PresentedLink>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PresentedLink {
    pub platform: String,
    pub url: String,
    pub label: Option<String>,
    pub verified: bool,
    pub owner: ProfileOwner,
    pub visibility: Visibility,
    pub verification: Verification,
    pub verification_evidence: Option<String>,
    pub expires_at: Option<DateTime<Utc>>,
    pub revoked_at: Option<DateTime<Utc>>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_visibility_tiers() {
        assert!(Visibility::Public.permits(&Visibility::Public));
        assert!(Visibility::Public.permits(&Visibility::Member));
        assert!(Visibility::Public.permits(&Visibility::Trusted));
        assert!(Visibility::Public.permits(&Visibility::Private));

        assert!(!Visibility::Member.permits(&Visibility::Public));
        assert!(Visibility::Member.permits(&Visibility::Member));
        assert!(Visibility::Member.permits(&Visibility::Trusted));

        assert!(!Visibility::Private.permits(&Visibility::Public));
        assert!(!Visibility::Private.permits(&Visibility::Member));
        assert!(!Visibility::Private.permits(&Visibility::Trusted));
        assert!(Visibility::Private.permits(&Visibility::Private));
    }

    #[test]
    fn test_links_for_tier() {
        let mut store = ProfileStore::default();
        store.add_link(ProfileLink::new(
            Platform::GitHub,
            "https://github.com/dp-web4",
            Visibility::Public,
        ));
        store.add_link(ProfileLink::new(
            Platform::LinkedIn,
            "https://linkedin.com/in/dp",
            Visibility::Member,
        ));
        store.add_link(ProfileLink::new(
            Platform::Email,
            "dp@metalinxx.io",
            Visibility::Trusted,
        ));
        store.add_link(ProfileLink::new(
            Platform::Phone,
            "+1-555-0100",
            Visibility::Private,
        ));

        assert_eq!(store.links_for_tier(&Visibility::Public).len(), 1);
        assert_eq!(store.links_for_tier(&Visibility::Member).len(), 2);
        assert_eq!(store.links_for_tier(&Visibility::Trusted).len(), 3);
        assert_eq!(store.links_for_tier(&Visibility::Private).len(), 4);
    }

    #[test]
    fn test_professional_filter() {
        let mut store = ProfileStore::default();
        store.add_link(ProfileLink::new(
            Platform::GitHub,
            "https://github.com/dp-web4",
            Visibility::Public,
        ));
        store.add_link(ProfileLink::new(
            Platform::Twitter,
            "https://twitter.com/dp",
            Visibility::Public,
        ));
        store.add_link(ProfileLink::new(
            Platform::LinkedIn,
            "https://linkedin.com/in/dp",
            Visibility::Member,
        ));

        let pro = store.professional_links(&Visibility::Member);
        assert_eq!(pro.len(), 2); // GitHub + LinkedIn
        assert!(pro.iter().all(|l| l.platform.is_professional()));
    }

    #[test]
    fn test_presentation_strips_internals() {
        let mut store = ProfileStore {
            display_name: Some("Dennis".into()),
            bio: Some("Building Web4".into()),
            links: vec![],
        };
        store.add_link(ProfileLink::new(
            Platform::GitHub,
            "https://github.com/dp-web4",
            Visibility::Public,
        ));
        store.add_link(ProfileLink::new(
            Platform::Phone,
            "+1-555-0100",
            Visibility::Private,
        ));

        let public_view = store.present(&Visibility::Public);
        assert_eq!(public_view.links.len(), 1);
        assert_eq!(public_view.display_name.as_deref(), Some("Dennis"));

        let private_view = store.present(&Visibility::Private);
        assert_eq!(private_view.links.len(), 2);
    }

    #[test]
    fn test_serialization() {
        let mut store = ProfileStore::default();
        store.display_name = Some("Test".into());
        store.add_link(ProfileLink::new(
            Platform::GitHub,
            "https://github.com/test",
            Visibility::Public,
        ));

        let json = serde_json::to_string(&store).unwrap();
        let recovered: ProfileStore = serde_json::from_str(&json).unwrap();
        assert_eq!(recovered.links.len(), 1);
        assert_eq!(recovered.display_name.as_deref(), Some("Test"));
    }

    #[test]
    fn test_hub_fields_member_tier_only() {
        let mut store = ProfileStore {
            display_name: Some("Dennis".into()),
            bio: Some("Building Web4".into()),
            links: vec![],
        };
        store.add_link(ProfileLink::new(
            Platform::GitHub,
            "https://github.com/dp-web4",
            Visibility::Public,
        ));
        store.add_link(ProfileLink::new(
            Platform::LinkedIn,
            "https://linkedin.com/in/dp",
            Visibility::Member,
        ));
        store.add_link(ProfileLink::new(
            Platform::Email,
            "dp@metalinxx.io",
            Visibility::Trusted,
        ));
        store.add_link(ProfileLink::new(
            Platform::Phone,
            "+1-555-0100",
            Visibility::Private,
        ));

        let f = store.hub_fields();
        // name + bio + github + linkedin = 4. email/phone (trusted/private) excluded.
        assert_eq!(f.len(), 4);
        assert_eq!(f.get("name").map(String::as_str), Some("Dennis"));
        assert_eq!(f.get("bio").map(String::as_str), Some("Building Web4"));
        assert_eq!(
            f.get("github").map(String::as_str),
            Some("https://github.com/dp-web4")
        );
        assert_eq!(
            f.get("linkedin").map(String::as_str),
            Some("https://linkedin.com/in/dp")
        );
        assert!(!f.contains_key("email"));
        assert!(!f.contains_key("phone"));
    }

    #[test]
    fn community_platforms_have_stable_names() {
        for (name, expected) in [
            ("slack", "slack"),
            ("discord", "discord"),
            ("matrix", "matrix"),
            ("telegram", "telegram"),
            ("meetup", "meetup"),
            ("luma", "luma"),
            ("eventbrite", "eventbrite"),
            ("zoom", "zoom"),
        ] {
            assert_eq!(parse_platform(name).as_str(), expected);
        }
    }

    #[test]
    fn hub_links_preserve_multiplicity_ownership_verification_and_tiers() {
        let community = Uuid::new_v4();
        let attester = Uuid::new_v4();
        let mut store = ProfileStore::default();
        store.add_link(
            ProfileLink::new(Platform::Slack, "https://chat.example/general", Visibility::Public)
                .with_owner(ProfileOwner::Community(community))
                .with_label("General")
                .with_self_verification("chain:self-proof")
                .unwrap(),
        );
        store.add_link(
            ProfileLink::new(Platform::Slack, "https://chat.example/members", Visibility::Member)
                .with_label("Members")
                .with_attestation(attester, "chain:attestation")
                .unwrap(),
        );
        store.add_link(
            ProfileLink::new(Platform::Slack, "https://chat.example/foreign-members", Visibility::Member)
                .with_owner(ProfileOwner::Role(Uuid::new_v4()))
                .with_attestation(attester, "chain:foreign-attestation")
                .unwrap(),
        );
        store.add_link(ProfileLink::new(
            Platform::Email,
            "private@example.invalid",
            Visibility::Trusted,
        ));

        let links = store.hub_links();
        assert_eq!(links.len(), 2, "same-platform links must not collapse");
        assert_eq!(links[0].label.as_deref(), Some("General"));
        assert_eq!(links[0].owner, ProfileOwner::Community(community));
        assert_eq!(links[0].visibility, Visibility::Public);
        assert!(matches!(links[0].verification, Verification::SelfVerified));
        assert_eq!(links[0].verification_evidence.as_deref(), Some("chain:self-proof"));
        assert_eq!(links[1].visibility, Visibility::Member);
        assert!(matches!(links[1].verification, Verification::Attested { by } if by == attester));
        assert_eq!(links[1].verification_evidence.as_deref(), Some("chain:attestation"));
        assert_eq!(links[1].owner, ProfileOwner::Member);
        assert!(links.iter().all(|link| link.platform == "slack"));
        assert!(links.iter().all(|link| link.url != "https://chat.example/foreign-members"));
        assert!(store.hub_fields().values().all(|url| url != "https://chat.example/foreign-members"));
        let trusted = store.present(&Visibility::Trusted);
        assert_eq!(trusted.links.len(), 3);
        assert!(trusted.links.iter().all(|link| link.url != "https://chat.example/foreign-members"),
                "trust in an outsider is not proof of membership in the link owner's group");
        assert_eq!(store.present(&Visibility::Private).links.len(), 4,
                   "external projection restrictions must not erase local/private access");
    }

    #[test]
    fn naked_verification_and_stale_links_do_not_project() {
        let mut naked = ProfileLink::new(Platform::Matrix, "https://chat.example/naked", Visibility::Public);
        naked.verification = Verification::SelfVerified;
        let mut store = ProfileStore {
            display_name: None,
            bio: None,
            links: vec![naked],
        };
        assert!(store.hub_links().is_empty());
        assert!(ProfileLink::new(Platform::Zoom, "https://meet.example/self", Visibility::Public)
            .with_self_verification(" ")
            .is_err());

        let now = Utc::now();
        let mut expiring = ProfileLink::new(Platform::Zoom, "https://meet.example/self", Visibility::Public)
            .with_self_verification("chain:self-proof")
            .unwrap()
            .with_expiry(now - chrono::Duration::seconds(1));
        store.links = vec![expiring.clone()];
        assert!(store.hub_links().is_empty());
        expiring.expires_at = Some(now + chrono::Duration::hours(1));
        store.links = vec![expiring.clone()];
        assert_eq!(store.hub_links().len(), 1);
        expiring.revoke(now);
        store.links = vec![expiring];
        assert!(store.hub_links().is_empty());
    }

    #[test]
    fn legacy_links_without_new_fields_remain_readable() {
        let legacy = serde_json::json!({
            "display_name": null,
            "bio": null,
            "links": [{
                "id": Uuid::nil(),
                "platform": "slack",
                "url": "https://chat.example/legacy",
                "label": null,
                "visibility": "public",
                "verification": "claimed",
                "added_at": "2026-01-01T00:00:00Z"
            }]
        });
        let store: ProfileStore = serde_json::from_value(legacy).unwrap();
        let links = store.hub_links();
        assert_eq!(links.len(), 1);
        assert_eq!(links[0].owner, ProfileOwner::Member);
        assert_eq!(links[0].visibility, Visibility::Public);
        assert_eq!(links[0].verification_evidence, None);
    }

    #[test]
    fn legacy_serialized_verification_without_evidence_is_hidden_not_projected() {
        let legacy = serde_json::json!({
            "display_name": null,
            "bio": null,
            "links": [
                {
                    "id": Uuid::nil(),
                    "platform": "slack",
                    "url": "https://chat.example/self-naked",
                    "label": null,
                    "visibility": "public",
                    "verification": "self_verified",
                    "added_at": "2026-01-01T00:00:00Z"
                },
                {
                    "id": Uuid::new_v4(),
                    "platform": "zoom",
                    "url": "https://meet.example/attested-naked",
                    "label": null,
                    "visibility": "member",
                    "verification": {"attested": {"by": Uuid::new_v4()}},
                    "added_at": "2026-01-01T00:00:00Z"
                }
            ]
        });
        let store: ProfileStore = serde_json::from_value(legacy).unwrap();
        assert!(store.links.iter().all(|link| !link.verification_is_evidenced()));
        assert!(store.hub_links().is_empty());
        assert!(store.hub_fields().is_empty(), "the legacy flattened projection must not leak naked endpoints");
    }

    #[test]
    fn lifecycle_boundaries_are_exact() {
        let now = Utc::now();
        let mut link = ProfileLink::new(Platform::Zoom, "https://meet.example/boundary", Visibility::Public)
            .with_expiry(now);
        assert!(!link.is_current(now), "expiry at this instant is no longer current");
        link.expires_at = Some(now - chrono::Duration::nanoseconds(1));
        assert!(!link.is_current(now), "one nanosecond before expiry is already expired");
        link.expires_at = Some(now + chrono::Duration::nanoseconds(1));
        assert!(link.is_current(now), "one nanosecond after expiry is still current");
        link.expires_at = None;
        assert!(link.is_current(now));
        link.revoke(now);
        assert!(!link.is_current(now), "revocation at this instant is no longer current");
        link.revoked_at = Some(now - chrono::Duration::nanoseconds(1));
        assert!(!link.is_current(now), "an earlier revocation is also not current");
    }

    #[test]
    fn profile_round_trips_through_the_vault_no_plaintext() {
        let dir = tempfile::tempdir().unwrap();
        let vpath = dir.path().join("vault.enc");
        let mut vault = Vault::init(vpath.clone(), "pw".into()).unwrap();

        let mut store = ProfileStore::default();
        store.display_name = Some("DP".into());
        store.save(&mut vault).unwrap();

        // No plaintext profile.json on disk — it's an encrypted vault document.
        assert!(!dir.path().join("profile.json").exists());

        // Round-trips through a fresh vault open.
        let vault2 = Vault::open(vpath, "pw".into()).unwrap();
        let loaded = ProfileStore::load(&vault2).unwrap();
        assert_eq!(loaded.display_name.as_deref(), Some("DP"));
    }

    #[test]
    fn profile_migrates_legacy_plaintext_then_removes_it() {
        let dir = tempfile::tempdir().unwrap();
        let vpath = dir.path().join("vault.enc");
        let mut vault = Vault::init(vpath, "pw".into()).unwrap();

        // A pre-doctrine plaintext profile.json next to the vault.
        let legacy = dir.path().join("profile.json");
        std::fs::write(
            &legacy,
            serde_json::to_vec(&serde_json::json!({"display_name":"Old","bio":null,"links":[]}))
                .unwrap(),
        )
        .unwrap();

        // load() reads the legacy file (migration source)...
        let loaded = ProfileStore::load(&vault).unwrap();
        assert_eq!(loaded.display_name.as_deref(), Some("Old"));
        // ...and the first save() imports it to the vault + deletes the plaintext.
        loaded.save(&mut vault).unwrap();
        assert!(
            !legacy.exists(),
            "legacy plaintext should be removed after migration"
        );
        assert!(vault.get_document(PROFILE_NS, PROFILE_NAME).is_some());
    }
}
