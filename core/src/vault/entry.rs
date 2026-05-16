//! Vault entry type — the cleartext representation of a single credential.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VaultEntry {
    /// Unique ID; stable across vault rotations
    pub id: Uuid,

    /// Human-readable name (e.g. "anthropic_api_key", "github_pat", "npm_publish_token")
    pub name: String,

    /// Scope tags — `["publish"]`, `["infer"]`, `["billing"]`, etc.
    /// Used by plugins to filter requests by intent.
    pub scope: Vec<String>,

    /// User-applied tags for organization
    pub tags: Vec<String>,

    /// The credential value (in cleartext when entries are in memory;
    /// the vault file as a whole is encrypted on disk).
    pub secret: String,

    /// Plugin IDs allowed to request this credential. Empty list = none.
    pub allowed_consumers: Vec<String>,

    /// When this entry was first added
    pub created_at: DateTime<Utc>,

    /// When this entry was last rotated (None if never rotated)
    pub last_rotated: Option<DateTime<Utc>>,
}

impl VaultEntry {
    pub fn new(name: impl Into<String>, secret: impl Into<String>) -> Self {
        Self {
            id: Uuid::new_v4(),
            name: name.into(),
            scope: Vec::new(),
            tags: Vec::new(),
            secret: secret.into(),
            allowed_consumers: Vec::new(),
            created_at: Utc::now(),
            last_rotated: None,
        }
    }

    pub fn with_scope(mut self, scope: Vec<String>) -> Self {
        self.scope = scope;
        self
    }

    pub fn with_tags(mut self, tags: Vec<String>) -> Self {
        self.tags = tags;
        self
    }

    pub fn with_consumers(mut self, consumers: Vec<String>) -> Self {
        self.allowed_consumers = consumers;
        self
    }

    /// Is this plugin allowed to read this credential?
    /// Empty `allowed_consumers` = nobody allowed (deny by default).
    pub fn allows(&self, plugin_id: &str) -> bool {
        self.allowed_consumers.iter().any(|p| p == plugin_id)
    }

    /// Is this credential in scope for the requested scope tags?
    /// A credential matches if any of its scope tags appears in the request.
    /// If the credential has no scope tags, it matches anything (open).
    pub fn matches_scope(&self, requested: &[String]) -> bool {
        if self.scope.is_empty() {
            return true;
        }
        requested.iter().any(|r| self.scope.iter().any(|s| s == r))
    }
}
