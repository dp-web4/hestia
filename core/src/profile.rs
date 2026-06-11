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
use std::path::{Path, PathBuf};
use uuid::Uuid;

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
            Platform::Custom(s) => s,
        }
    }

    pub fn is_professional(&self) -> bool {
        matches!(self, Platform::GitHub | Platform::LinkedIn | Platform::Website)
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
        other => anyhow::bail!("unknown visibility: {other} (expected: public, member, trusted, private)"),
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Verification {
    Claimed,
    SelfVerified,
    Attested { by: Uuid },
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
        }
    }

    pub fn with_label(mut self, label: &str) -> Self {
        self.label = Some(label.to_string());
        self
    }
}

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct ProfileStore {
    pub display_name: Option<String>,
    pub bio: Option<String>,
    pub links: Vec<ProfileLink>,
}

impl ProfileStore {
    pub fn path(hestia_home: &Path) -> PathBuf {
        hestia_home.join("profile.json")
    }

    pub fn load(hestia_home: &Path) -> anyhow::Result<Self> {
        let path = Self::path(hestia_home);
        if !path.exists() {
            return Ok(Self::default());
        }
        let data = std::fs::read_to_string(&path)?;
        Ok(serde_json::from_str(&data)?)
    }

    pub fn save(&self, hestia_home: &Path) -> anyhow::Result<()> {
        let path = Self::path(hestia_home);
        let data = serde_json::to_string_pretty(self)?;
        std::fs::write(&path, data)?;
        Ok(())
    }

    pub fn add_link(&mut self, link: ProfileLink) {
        self.links.push(link);
    }

    pub fn remove_link(&mut self, id: Uuid) -> bool {
        let len = self.links.len();
        self.links.retain(|l| l.id != id);
        self.links.len() < len
    }

    /// Links visible at a given tier — returns everything the caller is allowed to see.
    pub fn links_for_tier(&self, tier: &Visibility) -> Vec<&ProfileLink> {
        self.links.iter().filter(|l| l.visibility.permits(tier)).collect()
    }

    /// Professional links only (GitHub, LinkedIn, Website) at a given tier.
    pub fn professional_links(&self, tier: &Visibility) -> Vec<&ProfileLink> {
        self.links.iter()
            .filter(|l| l.platform.is_professional() && l.visibility.permits(tier))
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

    /// Build a presentation for a specific context — what to share with a hub or peer.
    pub fn present(&self, tier: &Visibility) -> ProfilePresentation {
        ProfilePresentation {
            display_name: self.display_name.clone(),
            bio: self.bio.clone(),
            links: self.links_for_tier(tier).into_iter().map(|l| PresentedLink {
                platform: l.platform.as_str().to_string(),
                url: l.url.clone(),
                label: l.label.clone(),
                verified: !matches!(l.verification, Verification::Claimed),
            }).collect(),
        }
    }
}

/// What gets shared with a hub or peer — no internal IDs, no visibility metadata.
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
        store.add_link(ProfileLink::new(Platform::GitHub, "https://github.com/dp-web4", Visibility::Public));
        store.add_link(ProfileLink::new(Platform::LinkedIn, "https://linkedin.com/in/dp", Visibility::Member));
        store.add_link(ProfileLink::new(Platform::Email, "dp@metalinxx.io", Visibility::Trusted));
        store.add_link(ProfileLink::new(Platform::Phone, "+1-555-0100", Visibility::Private));

        assert_eq!(store.links_for_tier(&Visibility::Public).len(), 1);
        assert_eq!(store.links_for_tier(&Visibility::Member).len(), 2);
        assert_eq!(store.links_for_tier(&Visibility::Trusted).len(), 3);
        assert_eq!(store.links_for_tier(&Visibility::Private).len(), 4);
    }

    #[test]
    fn test_professional_filter() {
        let mut store = ProfileStore::default();
        store.add_link(ProfileLink::new(Platform::GitHub, "https://github.com/dp-web4", Visibility::Public));
        store.add_link(ProfileLink::new(Platform::Twitter, "https://twitter.com/dp", Visibility::Public));
        store.add_link(ProfileLink::new(Platform::LinkedIn, "https://linkedin.com/in/dp", Visibility::Member));

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
        store.add_link(ProfileLink::new(Platform::GitHub, "https://github.com/dp-web4", Visibility::Public));
        store.add_link(ProfileLink::new(Platform::Phone, "+1-555-0100", Visibility::Private));

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
        store.add_link(ProfileLink::new(Platform::GitHub, "https://github.com/test", Visibility::Public));

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
        store.add_link(ProfileLink::new(Platform::GitHub, "https://github.com/dp-web4", Visibility::Public));
        store.add_link(ProfileLink::new(Platform::LinkedIn, "https://linkedin.com/in/dp", Visibility::Member));
        store.add_link(ProfileLink::new(Platform::Email, "dp@metalinxx.io", Visibility::Trusted));
        store.add_link(ProfileLink::new(Platform::Phone, "+1-555-0100", Visibility::Private));

        let f = store.hub_fields();
        // name + bio + github + linkedin = 4. email/phone (trusted/private) excluded.
        assert_eq!(f.len(), 4);
        assert_eq!(f.get("name").map(String::as_str), Some("Dennis"));
        assert_eq!(f.get("bio").map(String::as_str), Some("Building Web4"));
        assert_eq!(f.get("github").map(String::as_str), Some("https://github.com/dp-web4"));
        assert_eq!(f.get("linkedin").map(String::as_str), Some("https://linkedin.com/in/dp"));
        assert!(!f.contains_key("email"));
        assert!(!f.contains_key("phone"));
    }
}
