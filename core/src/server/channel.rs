//! Channel sends — a member's message to a BOUND recipient, in shadow (#1344, slice 1).
//!
//! WHAT THIS SLICE IS. `hestia_channel_send` (and SAGE's `channel_send`) lets a member ask to
//! send a message over a channel the OPERATOR bound for it: today an email address, later any
//! adapter. In this slice NOTHING LEAVES THE MACHINE. Every send is judged exactly as it would
//! be enforced, recorded on the chain, and kept in a sealed outbox; the reply says what would
//! have happened. The delivery slice (sprout-claude's email adapter, a separate process outside
//! the daemon) reads the outbox later.
//!
//! THE ORDER IS THE CONTRACT (#1344 amendment, item 3):
//! 1. attribute the caller (`resolve_attributed_caller`, never the latest session);
//! 2. resolve the binding (`hestia.channel_unbound` when none);
//! 3. gate on the target BUILT FROM THE BINDING (`{channel_id}:{recipient_class}`): caller
//!    text never reaches the gate target;
//! 4. sweep the content for the innate secret tokens (`FORBIDDEN_DEFAULT`, a source-parity
//!    copy of the Python gate's tuple);
//! 5. the unanswered budget;
//! 6. record: a chain row, and an outbox row.
//!
//! THE BUDGET IS UNANSWERED MESSAGES, NOT A RATE (dp, 2026-10-21, decision c). A member may
//! have at most `UNANSWERED_LIMIT` unanswered sends on a channel within the current clock hour;
//! the next one would be refused once enforced. The count is DERIVED from outbox rows on every
//! send, so a daemon restart forgets nothing (the in-memory `RateLimiter` would).

use serde::{Deserialize, Serialize};

/// The innate secret tokens, as the Python gate holds them (`hestia_gate_core.FORBIDDEN_DEFAULT`).
/// A source-parity test reads the Python tuple and fails on any difference, so the daemon's
/// sweep cannot drift from the gate's. Seat-specific extras stay seat-side: this is the innate
/// list only (#1344 amendment, item 1).
pub const FORBIDDEN_DEFAULT: &[&str] =
    &["/.ssh", ".env", "credentials", "id_rsa", "id_ed25519", "/.git/config", "secrets"];

/// The first innate token the text carries (case-insensitive, as the Python gate lowers), or None.
pub fn forbidden_token(text: &str) -> Option<&'static str> {
    let low = text.to_lowercase();
    FORBIDDEN_DEFAULT.iter().copied().find(|t| low.contains(t))
}

/// At most this many unanswered sends per member per channel per clock hour.
pub const UNANSWERED_LIMIT: u32 = 3;
/// The budget window: the current clock hour.
pub const WINDOW_SECS: u64 = 3600;
/// The longest message this slice accepts.
pub const MAX_CONTENT_CHARS: usize = 8000;

/// The start of the clock hour holding `now` (epoch seconds), and when it ends.
pub fn window(now: u64) -> (u64, u64) {
    let start = now - now % WINDOW_SECS;
    (start, start + WINDOW_SECS)
}

/// A channel the operator bound for a member: WHERE its sends to `channel_id` go, and what
/// class of recipient that is. The recipient address is the operator's, never the member's:
/// a member cannot choose who its messages reach.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ChannelBinding {
    /// The member (plugin id) the binding is for.
    pub member: String,
    /// The member-facing name of the channel (`dp`, `operator`, ...): what the member asks for.
    pub channel_id: String,
    /// The kind of recipient (`operator`, `human`, `peer`): part of the gate target, so law can
    /// rule on it.
    pub recipient_class: String,
    /// The adapter that will carry it (`email` in the delivery slice).
    pub adapter: String,
    /// Where the adapter delivers (an address). Never shown to the member.
    pub address: String,
    pub reason: String,
    #[serde(default)]
    pub set_by: String,
    #[serde(default)]
    pub set_at: u64,
    #[serde(default)]
    pub version: u64,
}

fn ident_ok(s: &str) -> bool {
    !s.is_empty() && s.len() <= 64 && s.chars().all(|c| c.is_ascii_alphanumeric() || "-_.".contains(c))
}

impl ChannelBinding {
    /// The gate target, built from the binding alone (#1344 amendment, item 3).
    pub fn target(&self) -> String {
        format!("{}:{}", self.channel_id, self.recipient_class)
    }
}

/// Validate a binding before it is written. Returned text is the operator-facing refusal.
pub fn validate(b: &ChannelBinding) -> Result<(), String> {
    if b.member.trim().is_empty() {
        return Err("member is required".into());
    }
    if !ident_ok(&b.channel_id) {
        return Err("channel_id is required: letters, digits, - _ . (at most 64)".into());
    }
    if !ident_ok(&b.recipient_class) {
        return Err("recipient_class is required: letters, digits, - _ . (at most 64), e.g. operator".into());
    }
    if !ident_ok(&b.adapter) {
        return Err("adapter is required, e.g. email".into());
    }
    if b.address.trim().is_empty() {
        return Err("address is required: where the adapter delivers".into());
    }
    if b.reason.trim().is_empty() {
        return Err("reason is required: a binding decides who a member's messages reach, so the \
                    record has to say why"
            .into());
    }
    Ok(())
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ChannelBindingStore {
    #[serde(default)]
    pub bindings: Vec<ChannelBinding>,
    #[serde(default)]
    pub generation: u64,
}

impl ChannelBindingStore {
    pub fn get(&self, member: &str, channel_id: &str) -> Option<&ChannelBinding> {
        self.bindings.iter().find(|b| b.member == member && b.channel_id == channel_id)
    }

    pub fn for_member(&self, member: &str) -> Vec<&ChannelBinding> {
        self.bindings.iter().filter(|b| b.member == member).collect()
    }

    /// Insert or replace the binding for (member, channel_id). Returns the version written.
    pub fn set(&mut self, mut b: ChannelBinding) -> u64 {
        self.generation += 1;
        b.version = self.generation;
        self.bindings.retain(|x| !(x.member == b.member && x.channel_id == b.channel_id));
        self.bindings.push(b);
        self.generation
    }

    pub fn remove(&mut self, member: &str, channel_id: &str) -> bool {
        let before = self.bindings.len();
        self.bindings.retain(|x| !(x.member == member && x.channel_id == channel_id));
        let removed = self.bindings.len() != before;
        if removed {
            self.generation += 1;
        }
        removed
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn b(member: &str, ch: &str) -> ChannelBinding {
        ChannelBinding {
            member: member.into(), channel_id: ch.into(), recipient_class: "operator".into(),
            adapter: "email".into(), address: "op@example.invalid".into(), reason: "r".into(),
            set_by: "operator".into(), set_at: 0, version: 0,
        }
    }

    /// The Rust token list is the Python gate's tuple, read from its source (#1344 amendment 1).
    #[test]
    fn forbidden_default_matches_the_python_gate_source() {
        let src = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"),
                                                  "/../plugins/_shared/hestia_gate_core.py"))
            .expect("the Python gate core is in this repo");
        let start = src.find("FORBIDDEN_DEFAULT = (").expect("FORBIDDEN_DEFAULT tuple");
        let body = &src[start..start + src[start..].find(')').expect("tuple end")];
        let py: Vec<&str> = body.split('"').skip(1).step_by(2).collect();
        assert!(!py.is_empty(), "parsed no tokens from the Python tuple");
        assert_eq!(py, FORBIDDEN_DEFAULT, "the daemon's innate list drifted from the Python gate's");
    }

    #[test]
    fn the_sweep_is_case_insensitive_and_names_the_token() {
        assert_eq!(forbidden_token("see ~/.SSH/known"), Some("/.ssh"));
        assert_eq!(forbidden_token("my SECRETS file"), Some("secrets"));
        assert_eq!(forbidden_token("a plain note about the board"), None);
    }

    #[test]
    fn the_window_is_the_clock_hour() {
        assert_eq!(window(7200), (7200, 10800));
        assert_eq!(window(10799), (7200, 10800));
    }

    #[test]
    fn a_binding_needs_every_field_and_a_reason() {
        assert!(validate(&b("being", "dp")).is_ok());
        let mut x = b("being", "dp");
        x.reason = " ".into();
        assert!(validate(&x).is_err());
        let mut x = b("being", "dp/../x");
        x.channel_id = "dp/../x".into();
        assert!(validate(&x).is_err(), "a channel id is a name, not a path");
        let mut x = b("being", "dp");
        x.address = "".into();
        assert!(validate(&x).is_err());
    }

    #[test]
    fn the_target_is_built_from_the_binding() {
        assert_eq!(b("being", "dp").target(), "dp:operator");
    }

    #[test]
    fn the_store_replaces_per_member_and_channel() {
        let mut st = ChannelBindingStore::default();
        st.set(b("a", "dp"));
        st.set(b("a", "dp"));
        st.set(b("b", "dp"));
        assert_eq!(st.bindings.len(), 2);
        assert_eq!(st.get("a", "dp").unwrap().version, 2);
        assert!(st.get("a", "other").is_none());
        assert!(st.remove("a", "dp") && !st.remove("a", "dp"));
    }
}
