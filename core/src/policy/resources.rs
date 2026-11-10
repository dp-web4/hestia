//! GATED RESOURCES (#1548): can the community afford this act, right now?
//!
//! dp, 2026-11-10: *"a seat brings an action to the community resource. can the community afford
//! it right now? if the action crashes the machine or interrupts a critical process, everyone
//! loses. and just like hestia gate, it's a negotiation process - refusal should say why, and what
//! changes (smaller job, later run, wait in queue) would be allowed."* And: *"it really comes back
//! to metabolic proprioception, at community level"*; *"we should be implementing r6 for all of
//! this"*.
//!
//! A [`GatedResource`] is local law: a named, scarce thing on one machine (cbp's scratch disk and
//! cargo, thor's GPU, sprout's memory), the acts that consume it ([`GatedResource::consumers`],
//! the same match language rules use), the live readings it depends on ([`Floor`]s over
//! [`Probe`]s), the price of an act in ATP at the current readings ([`Pricing`]), what a refused
//! act may do instead ([`GatedResource::alternatives`]), and what the operator is asked to fix when
//! a floor fails ([`GatedResource::remedy`]).
//!
//! THE PRICE IS SITUATIONAL. An act's ATP cost is `base × surge`, where surge is 1 while every
//! reading is at or above its `comfortable` level, rises as a reading approaches its floor, and is
//! unbounded at the floor (R6 `resource.pricing.surge_multiplier`). The floor is therefore not a
//! second mechanism beside the price: it is where the price exceeds anything a member could pay.
//! Before balances exist, an unbounded price is the only one that refuses.
//!
//! OBSERVE FIRST. In [`ResourceMode::Observe`] the assessment is computed and witnessed for every
//! matching act and the verdict is untouched. In [`ResourceMode::Enforce`] a refusing assessment
//! adds an enforced deny to the strictest fold. Either way an assessment can only ever ADD a deny:
//! nothing here can turn a deny into an allow (kimi-code's review of #1548, points 1-2).
//!
//! Units are integers throughout (MB for disk and memory, milli-ATP for prices), so the law that
//! carries them hashes the same in every language (kimi-code, point 5).
//!
//! This module is pure: probes are read by a [`Sampler`] the caller supplies, so the daemon can
//! sample off its async workers with a deadline and tests can hand in fixed readings.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use super::types::{PolicyDecision, PolicyEvaluation, PolicyMatch};

/// Observe (record what the gate would do) or enforce (refuse).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ResourceMode {
    #[default]
    Observe,
    Enforce,
}

impl ResourceMode {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Observe => "observe",
            Self::Enforce => "enforce",
        }
    }
}

/// A live reading of the machine. Every probe reads an integer.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Probe {
    /// Megabytes free to an unprivileged writer on the filesystem holding `path`.
    ///
    /// Name the path that actually runs out. On a WSL machine `/` reports the free space of a
    /// virtual disk that can still grow; what runs out is the Windows drive the `.vhdx` lives on
    /// (cbp, 2026-11-10: 656 GB "free" on `/`, 66 GB really free on C:).
    DiskFree { path: String },
    /// Free space on the filesystem holding `path`, in tenths of a percent of its size (0-1000).
    /// For floors stated as a share of the disk ("don't start a large build below 5% free").
    DiskFreePermille { path: String },
    /// `MemAvailable` from `/proc/meminfo`, in megabytes.
    MemAvailable,
    /// How many processes have a command line containing `pattern`. Pair with a `max` floor to
    /// keep an act from starting while a critical process runs.
    ProcessRunning { pattern: String },
}

impl Probe {
    /// What the reading measures, for refusal text.
    pub fn describe(&self) -> String {
        match self {
            Self::DiskFree { path } => format!("free disk at {path}"),
            Self::DiskFreePermille { path } => format!("free share of the disk at {path}"),
            Self::MemAvailable => "available memory".to_string(),
            Self::ProcessRunning { pattern } => format!("processes matching `{pattern}`"),
        }
    }

    fn unit(&self) -> &'static str {
        match self {
            Self::DiskFree { .. } | Self::MemAvailable => " MB",
            Self::DiskFreePermille { .. } => "‰",
            Self::ProcessRunning { .. } => "",
        }
    }
}

/// A condition on one live reading. The act is unaffordable while the reading is AT OR BELOW
/// `min` (at the floor the price is unbounded) or above `max`. Between `min` and `comfortable`
/// the price surges.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Floor {
    pub id: String,
    pub probe: Probe,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub min: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max: Option<u64>,
    /// At or above this reading the surge is 1×. Must exceed `min`. Absent: no surge, the floor is
    /// a plain threshold.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub comfortable: Option<u64>,
}

/// The price of one act, in milli-ATP before the surge.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Pricing {
    pub base_milli_atp: u64,
}

/// The sanctioned way to run a consumer of this resource (e.g. `cargo-serial`). Every invocation
/// that consumes the resource must BE a runner invocation: the runner has to be the command that
/// runs, not a word found elsewhere in the line (`cargo-serial check && cargo test` runs the
/// second build unserialised; codex, kimi-code and NOVA on #1551). The runner is where
/// serialisation, cleaning and priority are applied.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Runner {
    /// Shown in refusal text, e.g. `/home/dp/ai-workspace/scripts/cargo-serial <cargo args>`.
    pub usage: String,
    /// Regex over the invoked command's basename (after wrappers such as `env`, `nice` and
    /// `timeout` are looked through), e.g. `^cargo-serial$`.
    pub pattern: String,
}

/// What a lost reading means in enforce mode. There is no default: NOVA's review of #1551 is
/// right that an unknown reading must not impersonate affordability, and equally a hung probe
/// should not silently stop all work. The operator chooses, per resource.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum OnUnknown {
    /// An unread floor does not refuse (the reading is recorded as unknown).
    Allow,
    /// An unread floor refuses, like a failed one.
    Refuse,
}

/// One gated resource, declared in local law.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GatedResource {
    pub id: String,
    pub description: String,
    #[serde(default)]
    pub mode: ResourceMode,
    /// Acts that consume this resource. Any one matching makes the act a consumer. Same fields as
    /// a rule's `match`, except `rate_limit`, which would make a capacity check optional.
    pub consumers: Vec<PolicyMatch>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub floors: Vec<Floor>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pricing: Option<Pricing>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub runner: Option<Runner>,
    /// What a refused act may do instead: a smaller job, a later run, a place in the queue.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub alternatives: Vec<String>,
    /// What the operator is asked to fix when a floor fails, e.g. "free or add disk on C:".
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub remedy: Option<String>,
    /// What an unread floor means. Required in enforce mode when floors are declared.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub on_unknown: Option<OnUnknown>,
}

impl GatedResource {
    /// Refuse a declaration the gate could not apply faithfully. Called when law is written, so a
    /// bad declaration is rejected at the operator's desk, not discovered at a member's act.
    pub fn validate(&self) -> Result<(), String> {
        if self.id.trim().is_empty() {
            return Err("a gated resource needs an id".into());
        }
        if self.consumers.is_empty() {
            return Err(format!("resource `{}` declares no consumers", self.id));
        }
        for (i, c) in self.consumers.iter().enumerate() {
            if c == &PolicyMatch::default() {
                return Err(format!(
                    "resource `{}` consumer {i} matches every act",
                    self.id
                ));
            }
            if c.rate_limit.is_some() {
                return Err(format!(
                    "resource `{}` consumer {i} sets rate_limit: under a limit a rule skips firing, \
                     and an affordability check must never become optional that way",
                    self.id
                ));
            }
            let regexes = c
                .target_patterns
                .iter()
                .flatten()
                .filter(|_| c.target_patterns_are_regex)
                .chain(
                    c.command_patterns
                        .iter()
                        .flatten()
                        .filter(|_| c.command_patterns_are_regex),
                );
            for p in regexes {
                regex::Regex::new(p)
                    .map_err(|e| format!("resource `{}` consumer {i}: bad regex: {e}", self.id))?;
            }
        }
        let mut seen = std::collections::HashSet::new();
        for f in &self.floors {
            if !seen.insert(f.id.as_str()) {
                return Err(format!(
                    "resource `{}` repeats floor id `{}`",
                    self.id, f.id
                ));
            }
            if !super::resource_probes::supported(&f.probe) {
                return Err(format!(
                    "floor `{}`: this platform ({}) cannot read {}, so the floor could never \
                     apply; declare a probe this machine can read",
                    f.id,
                    std::env::consts::OS,
                    f.probe.describe()
                ));
            }
            if f.min.is_none() && f.max.is_none() {
                return Err(format!("floor `{}` sets neither min nor max", f.id));
            }
            if let Some(c) = f.comfortable {
                match f.min {
                    Some(m) if c > m => {}
                    _ => {
                        return Err(format!(
                            "floor `{}`: comfortable must be above min (the surge runs between them)",
                            f.id
                        ));
                    }
                }
            }
        }
        if let Some(r) = &self.runner {
            regex::Regex::new(&r.pattern)
                .map_err(|e| format!("resource `{}` runner pattern: {e}", self.id))?;
        }
        if self.mode == ResourceMode::Enforce
            && !self.floors.is_empty()
            && self.on_unknown.is_none()
        {
            return Err(format!(
                "resource `{}` is enforced but does not say what an unread floor means: set \
                 on_unknown to \"allow\" or \"refuse\" (a lost reading must be a decision, not \
                 a default)",
                self.id
            ));
        }
        Ok(())
    }

    /// The resource as one sentence of published law, so a member reads what it is bound by
    /// before it hits it.
    pub fn law_text(&self) -> String {
        let mut s = format!("{} ", self.description.trim_end_matches('.'));
        let conds: Vec<String> = self
            .floors
            .iter()
            .map(|f| match (f.min, f.max) {
                (Some(m), _) => {
                    format!("{} above {}", f.probe.describe(), fmt_reading(&f.probe, m))
                }
                (None, Some(m)) => format!(
                    "{} at most {}",
                    f.probe.describe(),
                    fmt_reading(&f.probe, m)
                ),
                _ => f.probe.describe(),
            })
            .collect();
        if !conds.is_empty() {
            s.push_str(&format!(
                "(acts that consume it need: {}). ",
                conds.join(", ")
            ));
        }
        s.push_str(&format!(
            "Consumed by: {}. Matched on each command the line runs (through wrappers, `sh -c` \
             and substitutions), not on what a script it starts goes on to do. ",
            self.consumers_text()
        ));
        if let Some(r) = &self.runner {
            s.push_str(&format!(
                "Run consumers through: {} (recognised as a command matching `{}`). ",
                r.usage, r.pattern
            ));
        }
        if let Some(u) = self.on_unknown {
            s.push_str(match u {
                OnUnknown::Allow => "An unread floor does not refuse. ",
                OnUnknown::Refuse => "An unread floor refuses. ",
            });
        }
        if let Some(p) = &self.pricing {
            s.push_str(&format!(
                "Price: {} milli-ATP per act, surging as a reading nears its floor. ",
                p.base_milli_atp
            ));
        }
        if !self.alternatives.is_empty() {
            s.push_str(&format!("If refused: {}. ", self.alternatives.join("; ")));
        }
        s.push_str(match self.mode {
            ResourceMode::Observe => {
                "Mode: observe (assessed and witnessed on every consuming act; \
                                     nothing is refused yet)."
            }
            ResourceMode::Enforce => "Mode: enforce (an unaffordable act is refused).",
        });
        s
    }

    /// Every probe this resource reads, deduplicated.
    pub fn probes(&self) -> Vec<Probe> {
        let mut out: Vec<Probe> = Vec::new();
        for f in &self.floors {
            if !out.contains(&f.probe) {
                out.push(f.probe.clone());
            }
        }
        out
    }

    /// The consumers as published text: what a member reads to know which acts this governs.
    pub fn consumers_text(&self) -> String {
        self.consumers
            .iter()
            .map(|c| serde_json::to_string(c).unwrap_or_default())
            .collect::<Vec<_>>()
            .join(" or ")
    }

    /// Is `head` (an invoked command's basename) this resource's runner?
    pub fn is_runner(&self, head: &str) -> bool {
        self.runner
            .as_ref()
            .is_some_and(|r| regex::Regex::new(&r.pattern).is_ok_and(|re| re.is_match(head)))
    }
}

/// One command a shell line would run, after looking through wrappers: its basename and the text
/// consumers are matched against (`<basename> <args…>`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Invocation {
    pub head: String,
    pub text: String,
}

/// Commands that run another command named in their arguments. Looked through, so
/// `nice -n 10 cargo build` is an invocation of `cargo`. Shell keywords and `!` that prefix a
/// command (`if …; then cargo build`, `! cargo test`) are looked through the same way.
const WRAPPERS: &[&str] = &[
    "env", "nice", "ionice", "nohup", "time", "timeout", "stdbuf", "command", "builtin", "exec",
    "xargs", "sudo", "doas", "chrt", "taskset", "setsid", "unbuffer", "flock", "!", "then", "do",
    "else", "elif", "if", "while", "until", "{",
];

/// Shells whose `-c` argument (alone or in a flag cluster: `-lc`, `-ec`, `-xc`) is a command
/// line of its own.
const SHELLS: &[&str] = &["sh", "bash", "dash", "zsh", "ksh", "fish"];

/// A word as the shell would run it: backslash escapes removed (`c\argo` runs `cargo`).
fn unescape(word: &str) -> String {
    let mut out = String::with_capacity(word.len());
    let mut chars = word.chars();
    while let Some(c) = chars.next() {
        if c == '\\' {
            if let Some(n) = chars.next() {
                out.push(n);
            }
        } else {
            out.push(c);
        }
    }
    out
}

fn basename(word: &str) -> String {
    word.rsplit('/').next().unwrap_or(word).to_string()
}

/// The bodies of `$( … )` and backtick substitutions in `cmd`, outermost first. Each is a command
/// line that runs, so it is searched for consumers like the line itself.
fn substitutions(cmd: &str) -> Option<Vec<String>> {
    let ch: Vec<char> = cmd.chars().collect();
    let mut out = Vec::new();
    let mut i = 0;
    while i < ch.len() {
        if ch[i] == '$' && ch.get(i + 1) == Some(&'(') {
            let mut depth = 1;
            let mut j = i + 2;
            while j < ch.len() && depth > 0 {
                match ch[j] {
                    '(' => depth += 1,
                    ')' => depth -= 1,
                    _ => {}
                }
                j += 1;
            }
            if depth != 0 {
                return None;
            }
            out.push(ch[i + 2..j - 1].iter().collect());
            i = j;
        } else if ch[i] == '`' {
            let end = ch[i + 1..].iter().position(|&c| c == '`')? + i + 1;
            out.push(ch[i + 1..end].iter().collect());
            i = end + 1;
        } else {
            i += 1;
        }
    }
    Some(out)
}

/// Every command `cmd` would run: each simple command (looking through wrappers), each `sh -c`
/// script, and each substitution, to a bounded depth. `None` when any part cannot be parsed with
/// confidence: the caller must then fail closed.
pub fn invocations(cmd: &str) -> Option<Vec<Invocation>> {
    fn push_from(words: &[String], depth: u8, out: &mut Vec<Invocation>) -> Option<()> {
        let Some(first) = words.first() else {
            return Some(());
        };
        let head = basename(first);
        if WRAPPERS.contains(&head.as_str()) {
            // A wrapper's options may take separate values (`timeout -s KILL 30 cmd`,
            // `sudo -u dp cmd`, `env -u VAR cmd`), and a table of which do will always miss one
            // (codex, kimi-code, claude-code on #1551). So every word after the wrapper that is
            // not itself an option is a CANDIDATE command: whichever candidate a consumer
            // matches is the command that runs. A wrong candidate can only add a match, never
            // hide one, so this errs toward assessing.
            for i in 1..words.len() {
                if !words[i].starts_with('-') {
                    push_from(&words[i..], depth, out)?;
                }
            }
            return Some(());
        }
        if SHELLS.contains(&head.as_str()) {
            // `-c` alone or in a short-flag cluster (`-lc`, `-ec`): the next non-option word is
            // a command line. A shell given a script file is opaque (documented limitation).
            let cluster = |w: &str| {
                w.starts_with('-')
                    && !w.starts_with("--")
                    && w[1..].chars().all(|c| c.is_ascii_alphabetic())
                    && w.contains('c')
            };
            if let Some(pos) = words.iter().position(|w| cluster(w)) {
                let script = words[pos + 1..].iter().find(|w| !w.starts_with('-'))?;
                walk(script, depth + 1, out)?;
            }
        }
        let text = std::iter::once(head.clone())
            .chain(words[1..].iter().cloned())
            .collect::<Vec<_>>()
            .join(" ");
        out.push(Invocation { head, text });
        Some(())
    }
    fn walk(cmd: &str, depth: u8, out: &mut Vec<Invocation>) -> Option<()> {
        if depth > 3 {
            return None;
        }
        for sub in substitutions(cmd)? {
            walk(&sub, depth + 1, out)?;
        }
        for sc in super::shell::simple_commands(cmd)? {
            let words: Vec<String> = sc
                .head
                .into_iter()
                .chain(sc.args)
                .map(|w| unescape(&w))
                .collect();
            push_from(&words, depth, out)?;
        }
        Some(())
    }
    let mut out = Vec::new();
    walk(cmd, 0, &mut out)?;
    Some(out)
}

/// Reads probes. The daemon's implementation samples the live machine with a deadline; tests
/// supply fixed readings. `None` means the reading could not be taken.
pub trait Sampler {
    fn sample(&self, probe: &Probe) -> Option<u64>;
}

impl Sampler for HashMap<Probe, Option<u64>> {
    fn sample(&self, probe: &Probe) -> Option<u64> {
        self.get(probe).copied().flatten()
    }
}

/// How one floor read at decision time.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FloorStatus {
    Ok,
    /// Below `min` or above `max`: the act is unaffordable.
    Short,
    /// The reading could not be taken. Refuses only where the resource says `on_unknown:
    /// refuse`; always recorded, so the gap is countable.
    Unknown,
    /// This platform cannot read the probe at all. Treated as `Unknown` for `on_unknown`; kept
    /// distinct so a declaration that can never bite is visible as such.
    Unsupported,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct FloorReading {
    pub floor_id: String,
    pub probe: Probe,
    pub reading: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub min: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub comfortable: Option<u64>,
    pub status: FloorStatus,
    /// Surge this floor contributes, in thousandths (1000 = 1×). `None` when short.
    pub surge_milli: Option<u64>,
}

impl FloorReading {
    /// Short because the resource is SCARCE (below a `min`), which only the operator can fix,
    /// as opposed to CONTENDED (above a `max`, e.g. a critical process running), which passes
    /// by itself and calls for a later run, not a remedy.
    pub fn is_scarce(&self) -> bool {
        self.status == FloorStatus::Short
            && matches!((self.reading, self.min), (Some(v), Some(m)) if v <= m)
    }
}

/// What the gate concluded about one act against one resource. Serialises as the R6 record.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Assessment {
    pub resource_id: String,
    pub mode: ResourceMode,
    pub routed: Option<bool>,
    pub floors: Vec<FloorReading>,
    /// Max over the floors (the scarcest reading sets the price). `None` when any floor is short.
    pub surge_milli: Option<u64>,
    pub base_milli_atp: Option<u64>,
    /// `base × surge`. `None` when unpriced or unaffordable.
    pub required_milli_atp: Option<u64>,
    pub reasons: Vec<String>,
    pub alternatives: Vec<String>,
    pub runner_usage: Option<String>,
    pub remedy: Option<String>,
}

impl Assessment {
    /// Would the community refuse this act? (In observe mode it is recorded, not refused.)
    pub fn refuses(&self) -> bool {
        !self.reasons.is_empty()
    }

    /// Floors short for scarcity: the conditions a remedy request is raised for.
    pub fn short_floors(&self) -> impl Iterator<Item = &FloorReading> {
        self.floors.iter().filter(|f| f.is_scarce())
    }

    /// The refusal, written as a negotiation: why, then what would be allowed instead.
    pub fn negotiation(&self) -> String {
        let mut s = format!(
            "gated resource `{}` ({}): the community cannot afford this act right now. Why: {}.",
            self.resource_id,
            self.mode.as_str(),
            self.reasons.join("; ")
        );
        let mut doors: Vec<String> = Vec::new();
        if self.routed == Some(false) {
            if let Some(u) = &self.runner_usage {
                doors.push(format!("run it through the runner: {u}"));
            }
        }
        doors.extend(self.alternatives.iter().cloned());
        if !doors.is_empty() {
            s.push_str(" Allowed instead: ");
            s.push_str(&doors.join("; "));
            s.push('.');
        }
        if self.short_floors().next().is_some() {
            if let Some(r) = &self.remedy {
                // States the remedy, not that a request was filed: the request is opened after
                // this text is composed and may fail to commit (codex/kimi-code on #1551). The
                // reply's `resourcesWitnessed` and the dashboard say whether it did.
                s.push_str(&format!(" What would fix it (the operator's to do): {r}."));
            }
        }
        s
    }

    /// The enforced deny an assessment adds to the fold (enforce mode, refusing only).
    pub fn as_evaluation(&self) -> Option<PolicyEvaluation> {
        if self.mode != ResourceMode::Enforce || !self.refuses() {
            return None;
        }
        let rule_id = format!("resource:{}", self.resource_id);
        Some(PolicyEvaluation {
            decision: PolicyDecision::Deny,
            rule_id: Some(rule_id.clone()),
            rule_name: Some(format!("gated resource: {}", self.resource_id)),
            reason: self.negotiation(),
            enforced: true,
            constraints: vec![
                format!("resource:{}", self.resource_id),
                "decision:deny".into(),
                format!("rule:{rule_id}"),
            ],
            inert_content_skipped: false,
        })
    }

    /// The act as an R6 record (`web4-standard/core-spec/r6-framework.md`): Rules, Role, Request,
    /// Reference, Resource, Result. `ctx` carries the parts the gate knows and this module does
    /// not (law hash, role, request). `result` is pending: settlement (what the act actually
    /// consumed, and the ATP discharged to ADP) is recorded after the act.
    pub fn to_r6(&self, ctx: &R6Context<'_>) -> Value {
        json!({
            "rules": {
                "lawHash": ctx.law_hash,
                "resource": self.resource_id,
                "mode": self.mode.as_str(),
            },
            "role": {
                "actor": ctx.actor,
                "roleLCT": ctx.role_lct,
            },
            "request": {
                "action": ctx.tool_name,
                "target": ctx.target,
                "actionId": ctx.action_id,
            },
            "reference": {
                "readings": self.floors,
                "routedThroughRunner": self.routed,
            },
            "resource": {
                "required": { "atp_milli": self.required_milli_atp },
                "pricing": {
                    "base_atp_milli": self.base_milli_atp,
                    "surge_multiplier_milli": self.surge_milli,
                },
                "affordable": !self.refuses(),
                "reasons": self.reasons,
                "alternatives": self.alternatives,
            },
            "result": { "status": "pending" },
        })
    }
}

/// What the gate knows about the act that this module does not.
pub struct R6Context<'a> {
    pub law_hash: &'a str,
    pub actor: &'a str,
    pub role_lct: &'a str,
    pub tool_name: &'a str,
    pub target: Option<&'a str>,
    pub action_id: &'a str,
}

fn surge_for(min: u64, comfortable: u64, reading: u64) -> u64 {
    if reading >= comfortable {
        return 1000;
    }
    let span = u128::from(comfortable - min);
    let left = u128::from(reading - min).max(1);
    u64::try_from(span * 1000 / left)
        .unwrap_or(u64::MAX)
        .max(1000)
}

fn fmt_reading(probe: &Probe, v: u64) -> String {
    format!("{v}{}", probe.unit())
}

/// Assess one act against one resource with the readings `sampler` gives.
pub fn assess(resource: &GatedResource, routed: Option<bool>, sampler: &dyn Sampler) -> Assessment {
    let mut reasons = Vec::new();
    if routed == Some(false) {
        reasons.push(format!(
            "this act consumes `{}` but does not go through its runner",
            resource.id
        ));
    }
    let mut floors = Vec::with_capacity(resource.floors.len());
    let mut surge: Option<u64> = Some(1000);
    for f in &resource.floors {
        let platform_reads = super::resource_probes::supported(&f.probe);
        let reading = if platform_reads {
            sampler.sample(&f.probe)
        } else {
            None
        };
        let refuse_unread = resource.on_unknown == Some(OnUnknown::Refuse);
        let (status, contrib) = match reading {
            None => {
                let status = if platform_reads {
                    FloorStatus::Unknown
                } else {
                    FloorStatus::Unsupported
                };
                if refuse_unread {
                    reasons.push(format!(
                        "{} could not be read ({}), and this resource refuses on an unread \
                         floor (`{}`)",
                        f.probe.describe(),
                        if platform_reads {
                            "no answer in time"
                        } else {
                            "unsupported here"
                        },
                        f.id
                    ));
                    (status, None)
                } else {
                    (status, Some(1000))
                }
            }
            Some(v) => {
                // AT the floor is short: that is where the price is unbounded (codex/kimi #5).
                let below = f.min.is_some_and(|m| v <= m);
                let above = f.max.is_some_and(|m| v > m);
                if below {
                    reasons.push(format!(
                        "{} is {}, at or below the floor of {} (`{}`)",
                        f.probe.describe(),
                        fmt_reading(&f.probe, v),
                        fmt_reading(&f.probe, f.min.unwrap_or(0)),
                        f.id
                    ));
                    (FloorStatus::Short, None)
                } else if above {
                    reasons.push(format!(
                        "{} is {}, above the limit of {} (`{}`)",
                        f.probe.describe(),
                        fmt_reading(&f.probe, v),
                        fmt_reading(&f.probe, f.max.unwrap_or(0)),
                        f.id
                    ));
                    (FloorStatus::Short, None)
                } else {
                    let s = match (f.min, f.comfortable) {
                        (Some(m), Some(c)) => surge_for(m, c, v),
                        _ => 1000,
                    };
                    (FloorStatus::Ok, Some(s))
                }
            }
        };
        surge = match (surge, contrib) {
            (Some(a), Some(b)) => Some(a.max(b)),
            _ => None,
        };
        floors.push(FloorReading {
            floor_id: f.id.clone(),
            probe: f.probe.clone(),
            reading,
            min: f.min,
            max: f.max,
            comfortable: f.comfortable,
            status,
            surge_milli: contrib,
        });
    }
    let base = resource.pricing.as_ref().map(|p| p.base_milli_atp);
    let required = match (base, surge) {
        (Some(b), Some(s)) => {
            Some(u64::try_from(u128::from(b) * u128::from(s) / 1000).unwrap_or(u64::MAX))
        }
        _ => None,
    };
    Assessment {
        resource_id: resource.id.clone(),
        mode: resource.mode,
        routed,
        floors,
        surge_milli: surge,
        base_milli_atp: base,
        required_milli_atp: required,
        reasons,
        alternatives: resource.alternatives.clone(),
        runner_usage: resource.runner.as_ref().map(|r| r.usage.clone()),
        remedy: resource.remedy.clone(),
    }
}

/// The published shape of the resources section, for `hestia_operating_law`: members read what
/// they are bound by before they hit it.
pub fn publish(resources: &[GatedResource]) -> Value {
    Value::Array(
        resources
            .iter()
            .map(|r| {
                json!({
                    "id": r.id,
                    "description": r.description,
                    "mode": r.mode.as_str(),
                    "floors": r.floors,
                    "pricing": r.pricing,
                    "consumers": r.consumers,
                    "runner": r.runner,
                    "on_unknown": r.on_unknown,
                    "law": r.law_text(),
                    "alternatives": r.alternatives,
                    "remedy": r.remedy,
                })
            })
            .collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::policy::types::PolicyAction;

    fn cargo_resource(mode: ResourceMode) -> GatedResource {
        serde_json::from_value(json!({
            "id": "cargo",
            "description": "one cargo run at a time on cbp; scratch is C:",
            "mode": mode.as_str(),
            "consumers": [
                {"tools": ["Bash"], "target_patterns_scope": "executable_positions",
                 "target_patterns_are_regex": true,
                 "target_patterns": ["^cargo(-serial)?\\s+(\\+\\S+\\s+)?(build|b|test|t|check|c|clippy|run|r|doc|bench|nextest|install)\\b"]}
            ],
            "floors": [
                {"id": "scratch", "probe": {"kind": "disk_free", "path": "/mnt/c"},
                 "min": 60000, "comfortable": 150000},
                {"id": "memory", "probe": {"kind": "mem_available"}, "min": 4000}
            ],
            "pricing": {"base_milli_atp": 5000},
            "runner": {"usage": "cargo-serial <cargo args>", "pattern": "^cargo-serial$"},
            "on_unknown": "allow",
            "alternatives": ["a smaller job: cargo test -p <crate>", "a later run, when the reading recovers"],
            "remedy": "free or add disk on C: (compact the vhdx, clean targets)"
        }))
        .unwrap()
    }

    fn readings(disk: Option<u64>, mem: Option<u64>) -> HashMap<Probe, Option<u64>> {
        let mut m = HashMap::new();
        m.insert(
            Probe::DiskFree {
                path: "/mnt/c".into(),
            },
            disk,
        );
        m.insert(Probe::MemAvailable, mem);
        m
    }

    fn bash(cmd: &str) -> PolicyAction<'_> {
        PolicyAction {
            tool_name: "Bash",
            category: "command",
            target: Some(cmd),
            full_command: Some(cmd),
        }
    }

    #[test]
    fn the_cargo_declaration_validates() {
        cargo_resource(ResourceMode::Observe).validate().unwrap();
    }

    #[test]
    fn a_comfortable_reading_costs_the_base_price() {
        let r = cargo_resource(ResourceMode::Observe);
        let a = assess(&r, Some(true), &readings(Some(200_000), Some(16_000)));
        assert!(!a.refuses());
        assert_eq!(a.surge_milli, Some(1000));
        assert_eq!(a.required_milli_atp, Some(5000));
    }

    #[test]
    fn the_price_surges_as_scratch_approaches_its_floor() {
        let r = cargo_resource(ResourceMode::Observe);
        // 90 GB free: a third of the way from the floor (60) to comfortable (150) => 3x.
        let a = assess(&r, Some(true), &readings(Some(90_000), Some(16_000)));
        assert!(!a.refuses());
        assert_eq!(a.surge_milli, Some(3000));
        assert_eq!(a.required_milli_atp, Some(15_000));
        // Closer still costs more.
        let b = assess(&r, Some(true), &readings(Some(61_000), Some(16_000)));
        assert!(b.required_milli_atp.unwrap() > a.required_milli_atp.unwrap());
    }

    #[test]
    fn at_the_floor_the_act_is_unaffordable_and_the_refusal_negotiates() {
        let r = cargo_resource(ResourceMode::Enforce);
        let a = assess(&r, Some(true), &readings(Some(41_000), Some(16_000)));
        assert!(a.refuses());
        assert_eq!(a.surge_milli, None);
        assert_eq!(a.required_milli_atp, None);
        let text = a.negotiation();
        assert!(
            text.contains("free disk at /mnt/c is 41000 MB, at or below the floor of 60000 MB"),
            "{text}"
        );
        assert!(text.contains("a smaller job"), "{text}");
        assert!(
            text.contains("What would fix it (the operator's to do)"),
            "{text}"
        );
        assert_eq!(a.short_floors().count(), 1);
    }

    #[test]
    fn an_unreadable_probe_never_refuses() {
        let r = cargo_resource(ResourceMode::Enforce);
        let a = assess(&r, Some(true), &readings(None, None));
        assert!(!a.refuses());
        assert!(a.floors.iter().all(|f| f.status == FloorStatus::Unknown));
        assert!(a.as_evaluation().is_none());
    }

    #[test]
    fn observe_mode_records_but_adds_no_deny() {
        let r = cargo_resource(ResourceMode::Observe);
        let a = assess(&r, Some(true), &readings(Some(10_000), Some(16_000)));
        assert!(a.refuses());
        assert!(a.as_evaluation().is_none());
    }

    #[test]
    fn enforce_mode_adds_an_enforced_deny_that_never_loosens_the_fold() {
        let r = cargo_resource(ResourceMode::Enforce);
        let a = assess(&r, Some(true), &readings(Some(10_000), Some(16_000)));
        let deny = a.as_evaluation().unwrap();
        assert_eq!(deny.decision, PolicyDecision::Deny);
        assert!(deny.enforced);
        // Folding into an existing enforced deny keeps a deny; folding into an allow tightens it.
        let allow = PolicyEvaluation {
            decision: PolicyDecision::Allow,
            rule_id: None,
            rule_name: None,
            reason: "Default policy: allow".into(),
            enforced: true,
            constraints: vec![],
            inert_content_skipped: false,
        };
        let folded = super::super::types::fold_strictest(allow, deny.clone());
        assert_eq!(folded.decision, PolicyDecision::Deny);
        let destructive = PolicyEvaluation {
            decision: PolicyDecision::Deny,
            rule_id: Some("destructive".into()),
            rule_name: Some("destructive".into()),
            reason: "destructive".into(),
            enforced: true,
            constraints: vec![],
            inert_content_skipped: false,
        };
        let folded = super::super::types::fold_strictest(destructive, deny);
        assert_eq!(folded.decision, PolicyDecision::Deny);
        assert_eq!(
            folded.rule_id.as_deref(),
            Some("destructive"),
            "a tie keeps the base deny"
        );
    }

    /// What the engine concludes for one command: `None` if the act consumes nothing, else
    /// whether it was routed through the runner.
    fn routed(r: &GatedResource, cmd: &str) -> Option<Option<bool>> {
        let mut cfg = crate::policy::get_preset("safety").unwrap().config;
        cfg.resources = vec![r.clone()];
        let engine = crate::policy::PolicyEngine::new(cfg);
        engine
            .matching_resources(&bash(cmd))
            .first()
            .map(|(_, routed)| *routed)
    }

    #[test]
    fn the_runner_must_be_the_command_that_consumes() {
        let r = cargo_resource(ResourceMode::Enforce);
        assert_eq!(routed(&r, "cargo test -q"), Some(Some(false)));
        assert_eq!(
            routed(&r, "/home/dp/ai-workspace/scripts/cargo-serial test -q"),
            Some(Some(true))
        );
        assert_eq!(
            routed(&r, "cd core && cargo-serial check"),
            Some(Some(true))
        );
        // Kimi's and codex's reproductions on #1551: the runner elsewhere in the line does not
        // route the consumer that runs after it.
        assert_eq!(
            routed(&r, "cargo-serial check && cargo test"),
            Some(Some(false))
        );
        assert_eq!(
            routed(&r, "echo cargo-serial && cargo build"),
            Some(Some(false))
        );
        assert_eq!(
            routed(&r, "echo 'use cargo-serial' && cargo build"),
            Some(Some(false))
        );
    }

    #[test]
    fn wrappers_shells_and_substitutions_are_looked_through() {
        let r = cargo_resource(ResourceMode::Enforce);
        assert_eq!(routed(&r, "nice -n 10 cargo-serial test"), Some(Some(true)));
        assert_eq!(
            routed(&r, "env CARGO_BUILD_JOBS=2 timeout 3600 cargo-serial build"),
            Some(Some(true))
        );
        assert_eq!(routed(&r, "timeout 600 cargo test"), Some(Some(false)));
        assert_eq!(routed(&r, "bash -c 'cargo build'"), Some(Some(false)));
        assert_eq!(routed(&r, "echo $(cargo build)"), Some(Some(false)));
        assert_eq!(routed(&r, "ls | xargs cargo check"), Some(Some(false)));
    }

    #[test]
    fn rereview_shell_forms_are_assessed() {
        // kimi-code's five public-API reproductions and codex's two, on #1551 at 72fc2005: each
        // returned no matching resource. Every one must be a consumer that is not routed.
        let r = cargo_resource(ResourceMode::Enforce);
        for cmd in [
            "env -u CARGO_TERM_COLOR cargo build",
            "timeout -s KILL 30 cargo test",
            "timeout --signal TERM 30 cargo build",
            "sudo -u dp cargo check",
            "c\\argo build",
            "! cargo test",
            "bash -lc 'cargo build'",
            "sh -ec 'cargo test -q'",
            "xargs -I {} cargo build {}",
            "stdbuf -o L cargo test",
            "if true; then cargo build; fi",
        ] {
            assert_eq!(routed(&r, cmd), Some(Some(false)), "{cmd}");
        }
        // The same forms around the runner are routed.
        for cmd in [
            "timeout -s KILL 3600 cargo-serial test",
            "sudo -u dp cargo-serial check",
            "bash -lc 'cargo-serial build'",
        ] {
            assert_eq!(routed(&r, cmd), Some(Some(true)), "{cmd}");
        }
    }

    #[test]
    fn a_mention_is_not_a_consumer() {
        let r = cargo_resource(ResourceMode::Enforce);
        assert_eq!(routed(&r, "echo 'cargo build'"), None);
        assert_eq!(routed(&r, "git commit -m 'fix cargo test flake'"), None);
        assert_eq!(routed(&r, "grep -n 'cargo test' README.md"), None);
        assert_eq!(routed(&r, "cargo fmt"), None);
    }

    #[test]
    fn a_direct_cargo_run_is_refused_for_routing_with_the_runner_named() {
        let r = cargo_resource(ResourceMode::Enforce);
        let a = assess(
            &r,
            routed(&r, "cargo build").unwrap(),
            &readings(Some(200_000), Some(16_000)),
        );
        assert!(a.refuses());
        assert!(
            a.negotiation()
                .contains("run it through the runner: cargo-serial <cargo args>")
        );
        // Routing is not a disk condition: no remedy is owed for it.
        assert_eq!(a.short_floors().count(), 0);
        assert!(!a.negotiation().contains("remedy"));
    }

    #[test]
    fn a_process_limit_refuses_while_a_critical_process_runs() {
        let mut r = cargo_resource(ResourceMode::Enforce);
        let beat = Probe::ProcessRunning {
            pattern: "sage.gateway.heartbeat".into(),
        };
        r.floors = vec![Floor {
            id: "heartbeat".into(),
            probe: beat.clone(),
            min: None,
            max: Some(0),
            comfortable: None,
        }];
        let mut m = HashMap::new();
        m.insert(beat.clone(), Some(1));
        let busy = assess(&r, Some(true), &m);
        assert!(busy.refuses());
        // Contention, not scarcity: it passes by itself, so no remedy is owed to the operator.
        assert_eq!(busy.short_floors().count(), 0);
        assert!(!busy.negotiation().contains("remedy request"));
        m.insert(beat, Some(0));
        assert!(!assess(&r, Some(true), &m).refuses());
    }

    #[test]
    fn a_percentage_floor_reads_in_permille() {
        let mut r = cargo_resource(ResourceMode::Observe);
        let share = Probe::DiskFreePermille {
            path: "/mnt/c".into(),
        };
        r.floors = vec![Floor {
            id: "scratch-share".into(),
            probe: share.clone(),
            min: Some(50),
            max: None,
            comfortable: Some(150),
        }];
        let mut m = HashMap::new();
        m.insert(share.clone(), Some(69)); // 6.9% free, cbp on 2026-11-10
        let a = assess(&r, Some(true), &m);
        assert!(!a.refuses());
        assert_eq!(a.surge_milli, Some(5263)); // (150-50)/(69-50) = 5.26x
        m.insert(share, Some(34)); // 3.4%, cbp on 2026-11-08
        let b = assess(&r, Some(true), &m);
        assert!(b.refuses());
        assert!(
            b.negotiation()
                .contains("is 34‰, at or below the floor of 50‰"),
            "{}",
            b.negotiation()
        );
    }

    #[test]
    fn exactly_at_the_floor_is_unaffordable() {
        // codex/kimi-code finding 5 on #1551: reading == min allowed the act at a finite price.
        let r = cargo_resource(ResourceMode::Enforce);
        let a = assess(&r, Some(true), &readings(Some(60_000), Some(16_000)));
        assert!(a.refuses(), "at the floor the price is unbounded");
        assert_eq!(a.required_milli_atp, None);
        assert_eq!(
            a.short_floors().count(),
            1,
            "and it is scarcity, so a remedy is owed"
        );
        let just_above = assess(&r, Some(true), &readings(Some(60_001), Some(16_000)));
        assert!(!just_above.refuses());
        assert!(just_above.required_milli_atp.unwrap() > 5000 * 1000);
    }

    #[test]
    fn an_unread_floor_refuses_only_where_the_operator_said_so() {
        let mut r = cargo_resource(ResourceMode::Enforce);
        assert!(!assess(&r, Some(true), &readings(None, Some(16_000))).refuses());
        r.on_unknown = Some(OnUnknown::Refuse);
        let a = assess(&r, Some(true), &readings(None, Some(16_000)));
        assert!(a.refuses());
        assert!(
            a.negotiation()
                .contains("could not be read (no answer in time)"),
            "{}",
            a.negotiation()
        );
        assert_eq!(
            a.short_floors().count(),
            0,
            "an unread probe is not scarcity"
        );
    }

    #[test]
    fn enforce_mode_requires_a_decision_about_unread_floors() {
        let mut r = cargo_resource(ResourceMode::Enforce);
        r.on_unknown = None;
        assert!(r.validate().unwrap_err().contains("on_unknown"));
        r.mode = ResourceMode::Observe;
        r.validate().unwrap();
    }

    #[test]
    fn published_law_says_what_it_governs() {
        let a = cargo_resource(ResourceMode::Enforce);
        let mut b = a.clone();
        b.consumers[0].target_patterns = Some(vec!["^make\\b".into()]);
        let (pa, pb) = (publish(&[a.clone()]), publish(&[b]));
        assert_ne!(
            pa, pb,
            "declarations differing only in consumers must publish differently"
        );
        assert_eq!(pa[0]["consumers"], json!(a.consumers));
        assert_eq!(pa[0]["runner"]["pattern"], "^cargo-serial$");
        assert!(a.law_text().contains("Consumed by:"));
        assert!(a.law_text().contains("^cargo-serial$"));
    }

    #[test]
    fn validation_refuses_what_the_gate_could_not_apply() {
        let mut r = cargo_resource(ResourceMode::Observe);
        r.consumers[0].rate_limit = Some(super::super::types::RateLimitSpec {
            max_count: 1,
            window_ms: 1000,
        });
        assert!(r.validate().unwrap_err().contains("rate_limit"));

        let mut r = cargo_resource(ResourceMode::Observe);
        r.consumers = vec![PolicyMatch::default()];
        assert!(r.validate().unwrap_err().contains("matches every act"));

        let mut r = cargo_resource(ResourceMode::Observe);
        r.floors[0].comfortable = Some(1);
        assert!(
            r.validate()
                .unwrap_err()
                .contains("comfortable must be above min")
        );

        let mut r = cargo_resource(ResourceMode::Observe);
        r.floors[1].min = None;
        assert!(r.validate().unwrap_err().contains("neither min nor max"));

        let mut r = cargo_resource(ResourceMode::Observe);
        r.consumers = vec![];
        assert!(r.validate().is_err());
    }

    #[test]
    fn the_r6_record_carries_all_six_parts() {
        let r = cargo_resource(ResourceMode::Observe);
        let a = assess(&r, Some(true), &readings(Some(90_000), Some(16_000)));
        let ctx = R6Context {
            law_hash: "abc",
            actor: "kimi-code",
            role_lct: "role:constellation:member",
            tool_name: "Bash",
            target: Some("cargo-serial test"),
            action_id: "00000000-0000-0000-0000-000000000000",
        };
        let v = a.to_r6(&ctx);
        for part in [
            "rules",
            "role",
            "request",
            "reference",
            "resource",
            "result",
        ] {
            assert!(v.get(part).is_some(), "missing {part}");
        }
        assert_eq!(v["resource"]["pricing"]["surge_multiplier_milli"], 3000);
        assert_eq!(v["resource"]["required"]["atp_milli"], 15_000);
        assert_eq!(v["result"]["status"], "pending");
        assert_eq!(v["reference"]["readings"][0]["reading"], 90_000);
    }
}
