//! Member addressing — the one place the member-id charset and the routed
//! address grammar are defined (r6-routing border-router v1).
//!
//! # Why this module exists at all
//!
//! The system keeps minting **separators around an unconstrained id** and each
//! new one re-opens the same ambiguity:
//!
//! - [`crate::lct_publish`] mints `member:{plugin_id}` labels — a `:` in a
//!   plugin_id corrupts that namespace **today**, with no forwarding involved.
//! - border-router v1 mints `peer/member` addresses — a `/` in a plugin_id would
//!   make an address parse two ways.
//!
//! Thor asked (r6-routing, 2026-07-26) for a `trust_store.list()` audit to prove
//! no registered id already contains `/`. **That audit cannot be run**: the trust
//! store is encrypted at rest, so ids are not readable offline. The reason the
//! audit is impossible is the reason the constraint belongs at *registration*
//! rather than in a migration — you cannot retroactively audit ids you cannot
//! read. So: constrain once, here, and let every separator the system invents
//! inherit the guarantee.
//!
//! # Two rules, not one — and the split is deliberate
//!
//! | rule | applies to | strictness |
//! |---|---|---|
//! | [`is_mintable_member_id`] | ids seen for the **first time** (mint path) | strict `[a-z0-9-]` |
//! | [`is_addressable_member_id`] | ids **used as an address** (send path) | structural only |
//!
//! A single strict rule applied at both sites would retroactively silence any
//! already-minted member whose id predates the rule — the bookkeeping-silences-a-
//! real-member failure that `tool_member_notify` explicitly refuses to commit for
//! unknown recipients. So the strict charset is a **pure addition going forward**
//! (already-minted members short-circuit on the registry hot path and never reach
//! it), while the send path enforces only what is *structurally* required for an
//! address to parse unambiguously: no separator characters, no whitespace.
//!
//! Everything already minted keeps working. Nothing new can be minted that breaks
//! a namespace. That is the whole trade.

/// Upper bound on a member id. Not a security property — a sanity bound so an id
/// cannot become a payload channel in the labels and paths it is interpolated into.
pub const MAX_MEMBER_ID_BYTES: usize = 64;

/// Characters that are structurally forbidden in a member id **everywhere**,
/// because the system mints identifiers *around* ids using them. Adding a new
/// minted separator means adding it here; that is the maintenance contract.
///
/// - `/` — the routed-address separator ([`parse_address`])
/// - `:` — the LCT/label separator (`member:{plugin_id}`, `lct:web4:member:…`)
/// - `#` — the pointer fragment separator (thread/undelivered fragments)
const STRUCTURAL_SEPARATORS: &[char] = &['/', ':', '#'];

/// Strict charset for a **newly minted** member id: `[a-z0-9-]`, non-empty,
/// bounded, and starting with an alphanumeric so an id can never be confused with
/// a flag or an option in any path that shells out.
///
/// Deliberately narrower than [`is_addressable_member_id`]: this is the rule for
/// ids that do not exist yet, where narrowing costs nothing and every future
/// separator the system invents is covered in advance.
pub fn is_mintable_member_id(id: &str) -> bool {
    if id.is_empty() || id.len() > MAX_MEMBER_ID_BYTES {
        return false;
    }
    if !id.starts_with(|c: char| c.is_ascii_lowercase() || c.is_ascii_digit()) {
        return false;
    }
    id.chars()
        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

/// Structural rule for an id **used as an address**. Grandfathers every
/// already-minted id (mixed case, dots, underscores all pass) and rejects only
/// what makes an address ambiguous or unsafe to interpolate.
pub fn is_addressable_member_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= MAX_MEMBER_ID_BYTES
        && !id
            .chars()
            .any(|c| c.is_whitespace() || c.is_control() || STRUCTURAL_SEPARATORS.contains(&c))
}

/// A parsed `to_plugin_id`. The router only ever decides **local vs. one next
/// hop**, so the grammar has exactly two shapes and no third.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Address {
    /// A bare id: a member of *this* society. Branch 1.
    Local(String),
    /// `peer/member`: a member of another society, reached via that peer. Branch 2.
    Routed { peer: String, member: String },
}

/// Why an address could not be parsed. Each variant is a distinct, *nameable*
/// failure — the point of branch 4 is that a report means something, so "bad
/// address" is never one undifferentiated error.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AddressError {
    /// Empty, or an empty segment (`/thor`, `thor/`).
    EmptySegment,
    /// Three or more components: `fleet/thor/claude-code`.
    ///
    /// **Never truncated to the first two.** A 3+-component path is *source
    /// routing* — it asks this node to know another society's interior — and
    /// silently dropping the tail is the silent-drop defect in miniature (Kimi,
    /// r6-routing review §2.2). v1 refuses it with the reason named.
    SourceRouting { components: usize },
    /// A segment carries a structural separator, whitespace, or is over-long.
    BadSegment { segment: String },
}

/// Parse a `to_plugin_id` into a routing decision. Pure — no table lookup, no
/// I/O. Resolution of the peer *name* is a separate step ([`resolve_peer`]) so
/// that "this address is malformed" and "I have no route for this peer" stay
/// distinguishable all the way to the caller.
pub fn parse_address(to: &str) -> Result<Address, AddressError> {
    let components: Vec<&str> = to.split('/').collect();
    match components.as_slice() {
        [single] => {
            if single.is_empty() {
                return Err(AddressError::EmptySegment);
            }
            if !is_addressable_member_id(single) {
                return Err(AddressError::BadSegment {
                    segment: (*single).to_string(),
                });
            }
            Ok(Address::Local((*single).to_string()))
        }
        [peer, member] => {
            if peer.is_empty() || member.is_empty() {
                return Err(AddressError::EmptySegment);
            }
            for seg in [peer, member] {
                if !is_addressable_member_id(seg) {
                    return Err(AddressError::BadSegment {
                        segment: (*seg).to_string(),
                    });
                }
            }
            Ok(Address::Routed {
                peer: (*peer).to_string(),
                member: (*member).to_string(),
            })
        }
        more => Err(AddressError::SourceRouting {
            components: more.len(),
        }),
    }
}

/// The outcome of resolving a peer *name* to a roster-validated LCT.
///
/// Three outcomes, not two, and the split is load-bearing (McNugget, r6-routing
/// review §3). A gap in **my own** table must never manufacture durable,
/// peer-facing evidence against a **healthy peer** — that is worse than the black
/// hole it replaces, because §5.1 makes misrouting a trust signal. So:
///
/// - [`PeerResolution::Known`] — route it.
/// - [`PeerResolution::NoRoute`] — the table exists and this peer is not in it.
///   A **local** defect. Reported synchronously to the (always local) sender;
///   never emitted as a witnessed unreachable *about the peer*.
/// - [`PeerResolution::NoTable`] — there is no table to have a gap in. Also
///   local, and a *different* fact: the Sprout stale-map incident (2026-07-14)
///   became a false "Sprout is not a member" precisely because these two were
///   collapsed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PeerResolution {
    Known { name: String, lct_id: String },
    NoRoute { known: Vec<String> },
    NoTable { consulted: String },
}

/// Peer table truth order, stated because it degrades silently otherwise
/// (McNugget's second requested change: *state the resolver and its truth order,
/// including behaviour when `list_members` 404s*).
///
/// 1. `<daemon home>/peers.json` — an explicit table this daemon owns. Absent by
///    default; this is the hook for a machine whose hub-mesh state lives
///    elsewhere, and it is what makes routing testable without touching process
///    environment.
/// 2. `~/.local/state/hub-mesh/members.json` — written **opportunistically by the
///    send path** (`hub-notify`), only on a 2xx from `GET /tools/list_members`,
///    which the hardened hub daemon gates to **404**. So it can be permanently
///    absent — it is on McNugget today. That is [`PeerResolution::NoTable`], and
///    it is why NoTable is a first-class outcome rather than an error case.
///
/// There is deliberately **no** fallback to a hand-maintained snapshot (`PEERS.md`
/// is a 2026-07-04 snapshot and stays out of the routing path): a stale map that
/// routes is worse than no map that refuses, because a refusal is visible at the
/// sender and a misroute is not. That is the Sprout stale-map incident
/// (2026-07-14) — caught only because the miss failed loudly at the sender.
pub fn peer_table_path(daemon_home: &std::path::Path) -> Option<std::path::PathBuf> {
    let owned = daemon_home.join("peers.json");
    if owned.exists() {
        return Some(owned);
    }
    dirs::home_dir().map(|h| h.join(".local/state/hub-mesh/members.json"))
}

/// Resolve a peer name against the roster, exact match only (case-insensitive).
///
/// **No prefix matching**, unlike `hub-notify`'s `startswith` resolver. Under a
/// prefix resolver an address changes meaning when an unrelated member joins the
/// fleet — the wrong property for an identifier in a system where misrouting is
/// evidence (McNugget §4). Case-insensitive because the live roster contains
/// `Sovereign`, `Sprout` and `thor-sage`: peer names are not member ids and were
/// never under the mint-time charset rule.
///
/// Returns the **LCT**, not the name. The transport is already LCT-addressed;
/// names are an edge concern. Resolving once here and routing on a
/// roster-validated LCT is what keeps `peer_lct()`'s pass-any-uuid-through
/// behaviour from being an oracle: the roster check and the LCT are one
/// requirement, not two.
pub fn resolve_peer(daemon_home: &std::path::Path, name: &str) -> PeerResolution {
    let Some(path) = peer_table_path(daemon_home) else {
        return PeerResolution::NoTable {
            consulted: "<no home directory>".to_string(),
        };
    };
    resolve_peer_at(&path, name)
}

/// [`resolve_peer`] against an explicit table. Split out so the resolution rules
/// are testable without touching process environment (env-var mutation races
/// across Rust's parallel test threads, and a flaky guard is worse than none).
pub fn resolve_peer_at(path: &std::path::Path, name: &str) -> PeerResolution {
    let consulted = path.display().to_string();
    let Ok(raw) = std::fs::read_to_string(path) else {
        return PeerResolution::NoTable { consulted };
    };
    let Ok(doc) = serde_json::from_str::<serde_json::Value>(&raw) else {
        // A corrupt table is NOT an empty table. Treating unparseable as "peer
        // unknown" would turn a local file defect into evidence about a peer.
        return PeerResolution::NoTable { consulted };
    };
    let Some(members) = doc.get("members").and_then(|m| m.as_array()) else {
        return PeerResolution::NoTable { consulted };
    };
    let mut known = Vec::new();
    for m in members {
        let (Some(n), Some(lct)) = (
            m.get("name").and_then(|v| v.as_str()),
            m.get("lct_id").and_then(|v| v.as_str()),
        ) else {
            continue;
        };
        if n.eq_ignore_ascii_case(name) {
            return PeerResolution::Known {
                name: n.to_string(),
                lct_id: lct.to_string(),
            };
        }
        known.push(n.to_string());
    }
    known.sort();
    PeerResolution::NoRoute { known }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mintable_is_strict_and_addressable_is_structural() {
        assert!(is_mintable_member_id("claude-code"));
        assert!(is_mintable_member_id("codex2"));
        // the separators the system mints around — rejected at mint
        assert!(!is_mintable_member_id("thor/claude-code"));
        assert!(!is_mintable_member_id("member:claude"));
        assert!(!is_mintable_member_id("a#b"));
        // strict-only rejections: these are grandfathered at the send path
        assert!(!is_mintable_member_id("Claude-Code"));
        assert!(!is_mintable_member_id("claude_code"));
        assert!(is_addressable_member_id("Claude-Code"));
        assert!(is_addressable_member_id("claude_code"));
        // structural rejections hold at both
        assert!(!is_addressable_member_id("thor/claude"));
        assert!(!is_addressable_member_id("member:claude"));
        assert!(!is_addressable_member_id("has space"));
        assert!(!is_addressable_member_id(""));
        assert!(!is_addressable_member_id(
            &"a".repeat(MAX_MEMBER_ID_BYTES + 1)
        ));
    }

    #[test]
    fn bare_id_is_local_and_unchanged() {
        assert_eq!(
            parse_address("kimi-code").unwrap(),
            Address::Local("kimi-code".to_string())
        );
    }

    #[test]
    fn two_components_route() {
        assert_eq!(
            parse_address("thor/claude-code").unwrap(),
            Address::Routed {
                peer: "thor".to_string(),
                member: "claude-code".to_string()
            }
        );
    }

    /// The finding this test exists for: `split_once('/')` on
    /// `fleet/thor/claude-code` yields peer=`fleet`, member=`thor/claude-code`
    /// — a source route accepted silently, addressed to a member that cannot
    /// exist. Refuse with the reason named.
    #[test]
    fn source_routing_is_refused_not_truncated() {
        assert_eq!(
            parse_address("fleet/thor/claude-code").unwrap_err(),
            AddressError::SourceRouting { components: 3 }
        );
    }

    #[test]
    fn empty_segments_are_refused() {
        assert_eq!(
            parse_address("/thor").unwrap_err(),
            AddressError::EmptySegment
        );
        assert_eq!(
            parse_address("thor/").unwrap_err(),
            AddressError::EmptySegment
        );
        assert_eq!(parse_address("").unwrap_err(), AddressError::EmptySegment);
    }

    #[test]
    fn colon_bearing_id_is_refused_at_the_send_path_too() {
        // `member:{plugin_id}` label corruption, refused before it can be minted
        // into an address.
        assert!(matches!(
            parse_address("member:claude").unwrap_err(),
            AddressError::BadSegment { .. }
        ));
    }

    #[test]
    fn no_table_and_no_route_are_different_facts() {
        let dir = tempfile::TempDir::new().unwrap();
        let missing = dir.path().join("absent.json");
        assert!(matches!(
            resolve_peer_at(&missing, "thor"),
            PeerResolution::NoTable { .. }
        ));

        let present = dir.path().join("members.json");
        std::fs::write(
            &present,
            r#"{"members":[{"lct_id":"dbbf02a0-1","name":"thor-sage"},
                           {"lct_id":"c888-2","name":"Sovereign"}]}"#,
        )
        .unwrap();
        assert!(matches!(
            resolve_peer_at(&present, "nobody"),
            PeerResolution::NoRoute { .. }
        ));
        // exact match only — `thor` must NOT prefix-match `thor-sage`
        assert!(matches!(
            resolve_peer_at(&present, "thor"),
            PeerResolution::NoRoute { .. }
        ));
        // …but case is not part of a peer name's identity
        match resolve_peer_at(&present, "sovereign") {
            PeerResolution::Known { lct_id, .. } => assert_eq!(lct_id, "c888-2"),
            other => panic!("expected Known, got {other:?}"),
        }
    }

    /// A corrupt local file must not become evidence about a peer.
    #[test]
    fn corrupt_table_reads_as_no_table_not_no_route() {
        let dir = tempfile::TempDir::new().unwrap();
        let bad = dir.path().join("members.json");
        std::fs::write(&bad, "{not json").unwrap();
        assert!(matches!(
            resolve_peer_at(&bad, "thor"),
            PeerResolution::NoTable { .. }
        ));
    }
}
