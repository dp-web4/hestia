//! Display aliases for members — a UI PRESENTATION artifact, never an artifact of record.
//!
//! dp, 2026-09-07 (#998): *"i want a display alias. the name underneath stays what it is,
//! i want the option to change what is displayed in the console. the alias should be marked
//! as such with a small indicator, and deletable at which point the original name is
//! displayed."* And the ruling that shapes this file: *"it's a ui presentation artifact, and
//! should be consistent across all parts of the ui. it isn't an artifact of record."*
//!
//! WHAT THAT MEANS IN CODE. A member's identity IS its `plugin_id`: the member LCT is a hash
//! of it, the registry, the vault seat document, the rendered projection and every chain row
//! name it. None of those may ever carry the alias. The alias exists at exactly one layer —
//! the moment a name is drawn for a human — and nowhere behind it. So:
//!
//!   * it lives in its OWN vault namespace (`ui`), apart from `seat-config` (rendered into
//!     projections), `scope` (authority) and every namespace something witnessed reads from,
//!     so no future author reasonably assumes the document is evidence;
//!   * setting or clearing it is NOT witnessed. A chain row saying "the console now calls X
//!     Y" would make the alias part of the record, which is the exact thing it must not be;
//!   * no API response renames `plugin_id`. The dashboard fetches the alias map separately
//!     and resolves it through one helper at render time, so every screen agrees;
//!   * the leak arm in `http.rs` sets an alias, exercises the acts that produce records, and
//!     asserts the alias string appears in no chain row.
//!
//! This is NOT the identity fold (`POST /api/operator/alias`, "these two ids are one
//! member"), which is an artifact of record and stays witnessed. Same word, opposite thing;
//! the two are kept apart by namespace, route and name.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::vault::Vault;

/// The vault namespace: presentation only. Nothing witnessed reads from it.
pub const NS: &str = "ui";
pub const NAME: &str = "member-aliases";
const LEGACY_FILENAME: &str = "member-aliases.json";

/// Long enough for a name, short enough that a chip stays a chip.
pub const ALIAS_MAX_CHARS: usize = 48;

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct MemberAliases {
    /// `plugin_id` → the label the console shows for it.
    #[serde(default)]
    pub aliases: BTreeMap<String, String>,
}

impl MemberAliases {
    pub fn load(vault: &Vault) -> anyhow::Result<Self> {
        crate::vault::load_doc(vault, NS, NAME, LEGACY_FILENAME)
    }

    pub fn save(&self, vault: &mut Vault) -> anyhow::Result<()> {
        crate::vault::save_doc(vault, NS, NAME, LEGACY_FILENAME, self)
    }

    /// What to DRAW for a member: its alias if one is set, else the id itself.
    pub fn display<'a>(&'a self, plugin_id: &'a str) -> &'a str {
        self.aliases.get(plugin_id).map(String::as_str).unwrap_or(plugin_id)
    }

    /// Set an alias. Refuses what would make the console lie or break: empty, over-long,
    /// control characters, or an alias equal to the id it labels (that is not an alias).
    /// Whether the alias collides with ANOTHER member's real id is the caller's check —
    /// this store does not know the registry, and must not, or it would become one.
    pub fn set(&mut self, plugin_id: &str, alias: &str) -> Result<(), String> {
        let id = plugin_id.trim();
        let alias = alias.trim();
        if id.is_empty() {
            return Err("plugin_id is required".into());
        }
        if alias.is_empty() {
            return Err("an empty alias is a clear, not a set — use clear".into());
        }
        if alias.chars().count() > ALIAS_MAX_CHARS {
            return Err(format!("alias is longer than {ALIAS_MAX_CHARS} characters"));
        }
        if alias.chars().any(|c| c.is_control()) {
            return Err("alias carries a control character".into());
        }
        if alias == id {
            return Err("an alias equal to the id is not an alias; clear it instead".into());
        }
        self.aliases.insert(id.to_string(), alias.to_string());
        Ok(())
    }

    /// Clear an alias; the console shows the id again. Returns whether one was set.
    pub fn clear(&mut self, plugin_id: &str) -> bool {
        self.aliases.remove(plugin_id.trim()).is_some()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn display_falls_back_to_the_id_and_clear_restores_it() {
        let mut a = MemberAliases::default();
        assert_eq!(a.display("claude-code"), "claude-code", "no alias: the id itself");
        a.set("claude-code", "Nugget").unwrap();
        assert_eq!(a.display("claude-code"), "Nugget");
        assert_eq!(a.display("codex"), "codex", "another member is untouched");
        assert!(a.clear("claude-code"), "there was one to clear");
        assert_eq!(a.display("claude-code"), "claude-code", "deleted: the original name is back");
        assert!(!a.clear("claude-code"), "clearing twice is a no-op, reported as such");
    }

    #[test]
    fn set_refuses_what_would_make_the_console_lie_or_break() {
        let mut a = MemberAliases::default();
        assert!(a.set("", "x").is_err(), "no member");
        assert!(a.set("codex", "   ").is_err(), "empty is a clear, not a set");
        assert!(a.set("codex", &"x".repeat(ALIAS_MAX_CHARS + 1)).is_err(), "over-long");
        assert!(a.set("codex", "co\u{7}dex").is_err(), "control character");
        assert!(a.set("codex", "codex").is_err(), "equal to the id is not an alias");
        assert!(a.aliases.is_empty(), "every refusal left the store untouched");
        a.set("  codex  ", "  The Codex  ").unwrap();
        assert_eq!(a.display("codex"), "The Codex", "trimmed on both sides");
    }

    #[test]
    fn the_namespace_is_its_own_and_not_one_anything_witnessed_reads() {
        // The whole design rests on this separation; pin it so a refactor that "tidies"
        // the alias into the seat document or the scope store fails a test, not a ruling.
        assert_ne!(NS, crate::server::seat_config::SEAT_CONFIG_NS, "seat-config renders into projections");
        assert_ne!(NS, "scope", "scope is authority");
        assert_ne!(NS, "presence", "the operator profile syncs to the hub");
    }
}
