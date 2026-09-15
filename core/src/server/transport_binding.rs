//! Transport bindings — who carries a member's mesh act off this host, and where the
//! answer belongs (#1030, phase A).
//!
//! WHY THIS EXISTS. A being's `member_notify` to `peer/member` was witnessed as the being
//! and forwarded "by" the being, while at the hub the envelope was signed by the SEAT: the
//! SAGE drain picked a signing key by whether an env file happened to exist on disk, and
//! fell back to the seat silently. Replies follow the envelope signer, so they reached the
//! seat's mailbox and never the being. Measured 2026-09-14 on CBP (87 forwarded rows, all
//! `forwarded_by: cbp-being`, all seat-signed at the hub), Legion (every legion-being notice
//! seat-signed; no identity file on the host) and McNugget; Sprout signed correctly because
//! its file existed. One being asked the same peers 92 times in 30 hours because nothing it
//! could see distinguished "unanswered" from "misrouted".
//!
//! THE INVARIANT IS NOT actor == carrier (GPT review of #1030). A seat relaying for a being
//! is legitimate. What was wrong is that the delegation was implicit, unbound, unwitnessed
//! and silently changed the return path. So the binding names four things an act can have,
//! separately:
//!
//! * the **member** (actor) the binding is for;
//! * the **mode**: `direct` (the member's own hub identity signs), `relay` (another identity
//!   signs on the member's behalf, under a named delegation), or `direct_required` (the
//!   member must sign as itself and holds no carrier yet — its routed sends are refused in
//!   its own turn, never forwarded under someone else's key);
//! * the **carrier_lct**: the hub member whose key signs the envelope;
//! * the **reply_to_lct**: the identity the answer belongs to (phase C routes on it).
//!
//! Operator-written, vault-persisted, member-readable. A member cannot write its own binding:
//! choosing one's own carrier is choosing whose name one's acts travel under.
//!
//! A member with NO binding keeps today's behaviour (the drain chooses), and every forwarded
//! witness for it says `transport: "unbound"`. Enforcement is per member, by binding, so the
//! fleet's existing mesh keeps working while bindings are provisioned.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

/// Hub scope for a binding. Phase A forwards through the one hub a host's drain uses, so
/// bindings are written for `ANY_HUB`; the field exists so a host joined to several hubs can
/// bind a member differently per hub without a schema change.
pub const ANY_HUB: &str = "*";

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TransportMode {
    Direct,
    Relay,
    DirectRequired,
}

impl TransportMode {
    pub fn parse(s: &str) -> Option<Self> {
        match s.trim() {
            "direct" => Some(Self::Direct),
            "relay" => Some(Self::Relay),
            "direct_required" => Some(Self::DirectRequired),
            _ => None,
        }
    }
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Direct => "direct",
            Self::Relay => "relay",
            Self::DirectRequired => "direct_required",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct TransportBinding {
    pub member: String,
    #[serde(default = "any_hub")]
    pub hub: String,
    pub mode: TransportMode,
    #[serde(default)]
    pub carrier_lct: Option<String>,
    #[serde(default)]
    pub reply_to_lct: Option<String>,
    /// For `relay`: what authorises the carrier to sign for the member (a delegation id, a
    /// ruling hash, an operator note reference). Required so a relay is never anonymous.
    #[serde(default)]
    pub delegation_ref: Option<String>,
    pub reason: String,
    #[serde(default)]
    pub set_by: String,
    #[serde(default)]
    pub set_at: u64,
    /// The store generation that wrote this binding. Stamped onto every row queued under it,
    /// so a row whose binding changed while it waited is detectable (falsifier 6).
    #[serde(default)]
    pub version: u64,
}

fn any_hub() -> String {
    ANY_HUB.to_string()
}

impl TransportBinding {
    /// The contract a row carries. Everything the drain needs to honour the binding, and the
    /// version to prove the row was queued under the binding still in force.
    pub fn stamp(&self) -> Value {
        json!({
            "mode": self.mode.as_str(),
            "carrier_lct": self.carrier_lct,
            "reply_to_lct": self.reply_to_lct,
            "delegation_ref": self.delegation_ref,
            "hub": self.hub,
            "version": self.version,
        })
    }
}

/// Validate a binding before it is written. Returned text is the operator-facing refusal.
pub fn validate(b: &TransportBinding) -> Result<(), String> {
    if b.member.trim().is_empty() {
        return Err("member is required".into());
    }
    if b.reason.trim().is_empty() {
        return Err("reason is required: a binding decides whose name a member's acts travel \
                    under, so the record has to say why"
            .into());
    }
    let carrier = b.carrier_lct.as_deref().map(str::trim).filter(|c| !c.is_empty());
    match b.mode {
        TransportMode::Direct if carrier.is_none() => Err(
            "mode `direct` needs carrier_lct: the member's own hub member id. With no carrier \
             yet, bind `direct_required`, which refuses the member's routed sends in its own \
             turn instead of letting another key carry them"
                .into(),
        ),
        TransportMode::Relay if carrier.is_none() => {
            Err("mode `relay` needs carrier_lct: the hub member that signs on the member's behalf".into())
        }
        TransportMode::Relay
            if b.delegation_ref.as_deref().map(str::trim).unwrap_or("").is_empty() =>
        {
            Err("mode `relay` needs delegation_ref: a relay that cannot name what authorises it \
                 is the implicit delegation this binding exists to end"
                .into())
        }
        TransportMode::DirectRequired if carrier.is_some() => Err(
            "mode `direct_required` takes no carrier_lct; once the member holds its own hub \
             identity, bind it `direct` with that carrier"
                .into(),
        ),
        _ => Ok(()),
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct TransportBindingStore {
    #[serde(default)]
    pub bindings: Vec<TransportBinding>,
    /// Moves on every durable mutation; a binding's `version` is the generation that wrote it.
    #[serde(default)]
    pub generation: u64,
}

impl TransportBindingStore {
    /// The binding in force for `member` on `hub`: an exact hub match first, then `ANY_HUB`.
    pub fn get(&self, member: &str, hub: &str) -> Option<&TransportBinding> {
        self.bindings
            .iter()
            .find(|b| b.member == member && b.hub == hub)
            .or_else(|| self.bindings.iter().find(|b| b.member == member && b.hub == ANY_HUB))
    }

    /// Insert or replace the binding for (member, hub). Returns the version it was written at.
    pub fn set(&mut self, mut b: TransportBinding) -> u64 {
        self.generation += 1;
        b.version = self.generation;
        self.bindings.retain(|x| !(x.member == b.member && x.hub == b.hub));
        self.bindings.push(b);
        self.generation
    }

    /// Remove the binding for (member, hub). The generation moves only on a real removal, so
    /// rows stamped under the removed binding read as stale against "no binding".
    pub fn remove(&mut self, member: &str, hub: &str) -> bool {
        let before = self.bindings.len();
        self.bindings.retain(|x| !(x.member == member && x.hub == hub));
        let removed = self.bindings.len() != before;
        if removed {
            self.generation += 1;
        }
        removed
    }

    pub fn for_member(&self, member: &str) -> Vec<&TransportBinding> {
        self.bindings.iter().filter(|b| b.member == member).collect()
    }
}

/// Is a queued row still travelling under the binding its sender has NOW? `stamped` is the
/// version on the row (None = queued unbound), `current` the version of the sender's binding
/// in force (None = unbound now). Any difference, including unbound -> bound and bound ->
/// removed, is a change the row was not queued under (falsifier 6). Checked at LIST time,
/// before the drain sends anything: a stale row is failed toward its author, never relabelled.
pub fn stamp_is_current(stamped: Option<u64>, current: Option<u64>) -> bool {
    stamped == current
}

/// The version a row was stamped with, if it was stamped at all.
pub fn stamped_version(stamp: Option<&Value>) -> Option<u64> {
    stamp.and_then(|s| s.get("version")).and_then(|v| v.as_u64())
}

/// What a drainer reported against what the row was stamped with, decided in one place so the
/// handler cannot drift from the tests. Judged against the STAMP, not the binding in force:
/// by the time a drainer marks a row the send has happened, under the contract it was listed
/// with, and staleness was the list arm's question.
#[derive(Debug, PartialEq, Eq)]
pub enum ForwardVerdict {
    /// No stamp: the member was unbound when it sent. Forwarded as today, labelled unbound.
    Unbound,
    /// Stamped, and the reported carrier is the stamped one.
    Honoured,
    /// Stamped, but the drainer did not say which identity signed.
    CarrierUnreported,
    /// Stamped, and the reported carrier is not the stamped one.
    CarrierMismatch { stamped: String, reported: String },
}

pub fn judge_forward(stamp: Option<&Value>, reported_carrier: Option<&str>) -> ForwardVerdict {
    let Some(stamp) = stamp else {
        return ForwardVerdict::Unbound;
    };
    let stamped = stamp
        .get("carrier_lct")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let reported = reported_carrier.map(str::trim).unwrap_or("");
    if reported.is_empty() {
        return ForwardVerdict::CarrierUnreported;
    }
    if !stamped.eq_ignore_ascii_case(reported) {
        return ForwardVerdict::CarrierMismatch { stamped, reported: reported.to_string() };
    }
    ForwardVerdict::Honoured
}

#[cfg(test)]
mod tests {
    use super::*;

    fn b(member: &str, mode: TransportMode, carrier: Option<&str>, deleg: Option<&str>) -> TransportBinding {
        TransportBinding {
            member: member.into(),
            hub: ANY_HUB.into(),
            mode,
            carrier_lct: carrier.map(Into::into),
            reply_to_lct: None,
            delegation_ref: deleg.map(Into::into),
            reason: "test".into(),
            set_by: "operator".into(),
            set_at: 1,
            version: 0,
        }
    }

    #[test]
    fn validation_names_what_each_mode_needs() {
        assert!(validate(&b("m", TransportMode::Direct, None, None)).unwrap_err().contains("direct_required"));
        assert!(validate(&b("m", TransportMode::Direct, Some("c"), None)).is_ok());
        assert!(validate(&b("m", TransportMode::Relay, Some("seat"), None)).unwrap_err().contains("delegation_ref"));
        assert!(validate(&b("m", TransportMode::Relay, Some("seat"), Some("d1"))).is_ok());
        assert!(validate(&b("m", TransportMode::DirectRequired, None, None)).is_ok());
        assert!(validate(&b("m", TransportMode::DirectRequired, Some("c"), None)).is_err());
        let mut no_reason = b("m", TransportMode::DirectRequired, None, None);
        no_reason.reason = " ".into();
        assert!(validate(&no_reason).unwrap_err().contains("reason"));
    }

    #[test]
    fn set_replaces_by_member_and_hub_and_versions_by_generation() {
        let mut s = TransportBindingStore::default();
        assert_eq!(s.set(b("being", TransportMode::DirectRequired, None, None)), 1);
        assert_eq!(s.set(b("being", TransportMode::Direct, Some("lct-b"), None)), 2);
        assert_eq!(s.bindings.len(), 1, "one binding per (member, hub)");
        let got = s.get("being", "hub-x").expect("ANY_HUB applies to every hub");
        assert_eq!((got.mode, got.version), (TransportMode::Direct, 2));
        assert!(s.remove("being", ANY_HUB) && s.generation == 3);
        assert!(!s.remove("being", ANY_HUB) && s.generation == 3, "no-op removal does not move generation");
    }

    #[test]
    fn a_forward_is_judged_against_its_stamp() {
        let mut store = TransportBindingStore::default();
        store.set(b("being", TransportMode::Direct, Some("LCT-B"), None));
        let stamp = store.get("being", ANY_HUB).unwrap().stamp();
        assert_eq!(judge_forward(None, Some("seat")), ForwardVerdict::Unbound);
        assert_eq!(judge_forward(Some(&stamp), Some("lct-b")), ForwardVerdict::Honoured, "LCT compare ignores case");
        assert_eq!(judge_forward(Some(&stamp), Some("  ")), ForwardVerdict::CarrierUnreported);
        assert_eq!(
            judge_forward(Some(&stamp), Some("SEAT")),
            ForwardVerdict::CarrierMismatch { stamped: "LCT-B".into(), reported: "SEAT".into() }
        );
    }

    #[test]
    fn staleness_counts_binding_added_and_removed_as_changes() {
        let mut store = TransportBindingStore::default();
        store.set(b("being", TransportMode::Direct, Some("LCT-B"), None));
        let stamp = store.get("being", ANY_HUB).unwrap().stamp();
        assert_eq!(stamped_version(Some(&stamp)), Some(1));
        assert!(stamp_is_current(Some(1), Some(1)));
        assert!(stamp_is_current(None, None), "unbound then, unbound now: forwarded as today");
        assert!(!stamp_is_current(None, Some(1)), "queued unbound, bound since: not the contract it was queued under");
        assert!(!stamp_is_current(Some(1), None), "binding removed while the row waited");
        assert!(!stamp_is_current(Some(1), Some(2)));
    }
}
