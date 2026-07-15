//! Hestia CLI — `hestia` binary.
//!
//! Phase 1 commands focus on vault management. The MCP server / society
//! state commands come in later sessions.

use anyhow::{Context, Result as AnyResult};
use clap::{Parser, Subcommand};
use std::path::PathBuf;

use hestia::constellation::{ConstellationStore, DeviceType};
use hestia::delegation::{self, DelegationStore};
use hestia::profile::{self, ProfileLink, ProfileStore};
use hestia::hub::{HubClient, HubStore};
use hestia::vault::{default_hestia_home, vault_path, Vault, VaultEntry};

/// Reported by `--version`: the semver plus the exact build provenance
/// (`git describe`), baked at build time by `build.rs`. Can't go stale — it
/// reflects the commit the binary was built from, not a hand-edited constant.
const VERSION: &str = concat!(
    env!("CARGO_PKG_VERSION"),
    " (",
    env!("HESTIA_GIT_VERSION"),
    ")"
);

#[derive(Parser, Debug)]
#[command(
    name = "hestia",
    version = VERSION,
    about = "Local-first Web4 trust layer for AI agents",
    long_about = "Hestia — local-first Web4 trust layer. Manages a credential vault, \
                  a Web4 society identity, a witness chain across all your AI agents, \
                  and an MCP server exposing all of that to plugged-in agent clients."
)]
struct Cli {
    /// Override hestia home directory (default: ~/.hestia)
    #[arg(long, global = true, env = "HESTIA_HOME")]
    home: Option<PathBuf>,

    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// Initialize a new hestia home + empty vault.
    Init {
        /// Overwrite existing vault if present (DESTRUCTIVE)
        #[arg(long)]
        force: bool,

        /// AI-autonomous mode — generate a keypair and store it in the vault
        /// instead of prompting for human credentials. The AI agent owns this
        /// identity directly (no delegation from a human).
        #[arg(long)]
        ai: bool,
    },

    /// Show hestia home + vault info
    Info,

    /// Run the MCP server daemon
    Serve {
        /// Bind address (default 127.0.0.1:7711). Loopback-only unless
        /// --allow-remote is passed — the REST surface is unauthenticated, so
        /// off-device access should go through a paired sealed channel.
        #[arg(long, default_value = "127.0.0.1:7711")]
        bind: String,

        /// Allow binding a NON-loopback address (e.g. 0.0.0.0 or a LAN/tailnet
        /// IP). Required to override the default-refuse guard. NOT recommended:
        /// it exposes the full vault/policy/chain REST surface with no auth.
        #[arg(long)]
        allow_remote: bool,

        /// Enable Sovereign callback server (hub signing requests).
        /// Generates an ephemeral keypair; production should load from vault.
        #[arg(long)]
        callback: bool,
    },

    /// Launch the terminal dashboard against a running daemon
    Dashboard {
        /// Daemon URL (default http://127.0.0.1:7711)
        #[arg(long, default_value = "http://127.0.0.1:7711")]
        endpoint: String,
    },

    /// Vault subcommands
    #[command(subcommand)]
    Vault(VaultCmd),

    /// Policy subcommands
    #[command(subcommand)]
    Policy(PolicyCmd),

    /// Delegation subcommands (Track H4 — delegate authority to agents)
    #[command(subcommand)]
    Delegate(DelegateCmd),

    /// Hub connection subcommands (Track H2/H3 — connect to Web4 hubs)
    #[command(subcommand)]
    Hub(HubCmd),
    /// LCT publish subcommands (registry seam — canon genesis step 7)
    #[command(subcommand)]
    Lct(LctCmd),

    /// Device constellation subcommands (mini-hub for your LCTs)
    #[command(subcommand)]
    Constellation(ConstellationCmd),

    /// Profile / presence links (social, professional, contact)
    #[command(subcommand)]
    Profile(ProfileCmd),
}

#[derive(Subcommand, Debug)]
enum ProfileCmd {
    /// Set display name
    Name {
        name: String,
    },

    /// Set bio
    Bio {
        bio: String,
    },

    /// Add a link (platform: github, linkedin, twitter, bluesky, website, email, etc.)
    #[command(alias = "add-link")]
    Add {
        /// Platform name
        platform: String,
        /// URL or handle
        url: String,
        /// Visibility: public | member | trusted | private
        #[arg(long, default_value = "public")]
        visibility: String,
        /// Optional display label
        #[arg(long)]
        label: Option<String>,
    },

    /// List profile links
    #[command(alias = "links")]
    List {
        /// Filter by visibility tier (show links visible at this tier)
        #[arg(long)]
        tier: Option<String>,
    },

    /// Remove a link by ID
    #[command(alias = "rm")]
    Remove {
        /// Link ID (UUID)
        id: String,
    },

    /// Show what a hub or peer would see at a given tier
    Present {
        /// Tier to present as: public | member | trusted | private
        #[arg(default_value = "public")]
        tier: String,
    },

    /// Push the member-tier profile to a connected hub (find_members discovery)
    Push {
        /// Hub URL or connection UUID (must be already connected)
        target: String,
    },
}

#[derive(Subcommand, Debug)]
enum ConstellationCmd {
    /// Add a device to your constellation
    Add {
        /// Device name (e.g. "Legion Desktop", "Phone", "YubiKey")
        name: String,
        /// Device type: desktop | mobile | server | agent | hardware
        #[arg(long, default_value = "desktop")]
        device_type: String,
    },

    /// List devices in the constellation
    List,

    /// Remove a device by LCT ID
    Remove {
        /// Device LCT ID (UUID)
        id: String,
    },

    /// Generate a constellation proof
    Proof,
}

#[derive(Subcommand, Debug)]
enum HubCmd {
    /// Connect to a Web4 hub (discovers via .well-known/web4-hub.json)
    Connect {
        /// Hub base URL (e.g. https://hub.example.com)
        url: String,
    },

    /// List connected hubs
    List,

    /// Show details of a specific hub connection
    Show {
        /// Hub URL or connection UUID
        target: String,
    },

    /// Disconnect from a hub (removes local connection state)
    Disconnect {
        /// Hub URL or connection UUID
        target: String,
    },

    /// Self-add as a member (V2-12): provision a member identity in the vault,
    /// sign a join request, and submit it so the hub pins your pubkey.
    Join {
        /// Hub URL or connection UUID (must be already connected)
        target: String,
        /// Optional display name to register at join
        #[arg(long)]
        name: Option<String>,
    },

    /// Choose which key signs member-tier acts (`profile push`) to this hub.
    /// Default is the sealed vault identity; point it at a raw 32-byte Ed25519
    /// channel key file when the hub pinned your operational channel key (a
    /// non-interactive mesh watcher can't open the sealed vault). Omit
    /// `--channel-key` to reset to the vault identity.
    SetMemberKey {
        /// Hub URL or connection UUID
        target: String,
        /// Path to a raw 32-byte Ed25519 channel key file (e.g.
        /// ~/.web4/<name>/channel_key.bin). Omit to reset to the vault identity.
        #[arg(long)]
        channel_key: Option<String>,
        /// The member LCT id the hub pinned this key FOR (from your join /
        /// mesh env `MY_LCT`). In channel-key mode this id IS the envelope
        /// signer + registry `published_by`, so the connection must record the
        /// pinned pairing, not a locally minted placeholder. Only meaningful
        /// with --channel-key.
        #[arg(long)]
        member_lct: Option<uuid::Uuid>,
    },
}

#[derive(Subcommand, Debug)]
enum PolicyCmd {
    /// Show the active preset and its resolved rules
    Show,

    /// Change the active preset (writes to vault)
    Set {
        /// Preset name: permissive | safety | strict | audit-only
        preset: String,
    },

    /// List all available built-in presets
    List,

    /// Dry-run evaluate a hypothetical action against the active preset
    Test {
        /// Tool name (e.g. "Bash", "Read", "Write")
        tool: String,
        /// Target (file path, URL, or for Bash, the full command)
        target: String,
    },

    /// Override a preset rule (change its decision / enable state) — "specifically"
    Override {
        /// The rule id (see `policy show`)
        rule_id: String,
        /// New decision: allow | warn | deny
        #[arg(long)]
        decision: Option<String>,
        /// Disable the rule (it stops firing)
        #[arg(long)]
        disable: bool,
        /// Re-enable a previously disabled rule
        #[arg(long)]
        enable: bool,
        /// Remove the override entirely (revert to the preset default)
        #[arg(long)]
        clear: bool,
    },

    /// Add or replace a custom rule — by category or specifically
    AddRule {
        /// Human-readable name (the rule id is derived from it)
        #[arg(long)]
        name: String,
        /// Decision: allow | warn | deny
        #[arg(long)]
        decision: String,
        /// Match a tool category (e.g. credential_access, network, file_write)
        #[arg(long)]
        category: Option<String>,
        /// Match a specific tool name (e.g. Bash)
        #[arg(long)]
        tool: Option<String>,
        /// Match a command glob pattern (e.g. "*rm -rf*")
        #[arg(long)]
        command: Option<String>,
        /// Match a target glob pattern (file path / url), repeatable. Combinable
        /// with the other specifiers — all given specifiers must match (AND), e.g.
        /// `--category file_read --target "*/.ssh/*"` = reads of ssh key material.
        #[arg(long = "target")]
        targets: Vec<String>,
        /// Priority (lower = evaluated first)
        #[arg(long, default_value_t = 50)]
        priority: i32,
        /// Scope the rule to a constellation role (#403 role-scoped law), e.g.
        /// role:constellation:mesh-worker. The rule then applies ONLY to sessions
        /// in that role, folded strictest-wins on top of the base policy (it can
        /// only tighten). Omit for a base custom rule that applies to everyone.
        #[arg(long)]
        role: Option<String>,
    },

    /// Remove a custom rule by id
    RmRule {
        /// The custom rule id
        id: String,
        /// Remove from this constellation-role overlay instead of the base
        /// custom rules.
        #[arg(long)]
        role: Option<String>,
    },
}

#[derive(Subcommand, Debug)]
enum DelegateCmd {
    /// Grant authority to an agent
    #[command(alias = "to")]
    Grant {
        /// Agent LCT ID (UUID)
        agent: String,

        /// Roles to grant (e.g. --role administrator --role archivist)
        #[arg(long)]
        role: Vec<String>,

        /// Specific actions to permit (empty = all within granted roles)
        #[arg(long)]
        action: Vec<String>,

        /// Expiration in hours (e.g. --expires 24)
        #[arg(long)]
        expires: Option<u64>,
    },

    /// List active delegations
    List,

    /// Revoke a delegation by ID
    Revoke {
        /// Delegation ID (UUID)
        id: String,
    },
}

#[derive(Subcommand, Debug)]
enum VaultCmd {
    /// List credential names in the vault
    List,

    /// Get a credential value (prints to stdout)
    Get {
        /// Credential name
        name: String,
    },

    /// Add a new credential to the vault
    Add {
        /// Credential name
        name: String,

        /// Scope tags (e.g. --scope publish --scope infer)
        #[arg(long)]
        scope: Vec<String>,

        /// Tags for organization
        #[arg(long)]
        tag: Vec<String>,

        /// Plugins allowed to read this credential
        #[arg(long = "consumer")]
        allowed_consumers: Vec<String>,
    },

    /// Remove a credential from the vault
    #[command(alias = "rm")]
    Remove {
        /// Credential name
        name: String,
    },
}

pub fn run() -> AnyResult<()> {
    let cli = Cli::parse();
    let home = resolve_home(&cli)?;

    match cli.command {
        Command::Init { force, ai } => cmd_init(&home, force, ai),
        Command::Info => cmd_info(&home),
        Command::Serve { bind, allow_remote, callback } => cmd_serve(&home, &bind, allow_remote, callback),
        Command::Dashboard { endpoint } => hestia::tui::run(&endpoint),
        Command::Vault(v) => match v {
            VaultCmd::List => cmd_vault_list(&home),
            VaultCmd::Get { name } => cmd_vault_get(&home, &name),
            VaultCmd::Add {
                name,
                scope,
                tag,
                allowed_consumers,
            } => cmd_vault_add(&home, &name, scope, tag, allowed_consumers),
            VaultCmd::Remove { name } => cmd_vault_remove(&home, &name),
        },
        Command::Policy(p) => match p {
            PolicyCmd::Show => cmd_policy_show(&home),
            PolicyCmd::List => cmd_policy_list(),
            PolicyCmd::Set { preset } => cmd_policy_set(&home, &preset),
            PolicyCmd::Test { tool, target } => cmd_policy_test(&home, &tool, &target),
            PolicyCmd::Override { rule_id, decision, disable, enable, clear } => {
                cmd_policy_override(&home, &rule_id, decision, disable, enable, clear)
            }
            PolicyCmd::AddRule { name, decision, category, tool, command, targets, priority, role } => {
                cmd_policy_add_rule(&home, &name, &decision, category, tool, command, targets, priority, role)
            }
            PolicyCmd::RmRule { id, role } => cmd_policy_rm_rule(&home, &id, role),
        },
        Command::Delegate(d) => match d {
            DelegateCmd::Grant { agent, role, action, expires } => {
                cmd_delegate_grant(&home, &agent, role, action, expires)
            }
            DelegateCmd::List => cmd_delegate_list(&home),
            DelegateCmd::Revoke { id } => cmd_delegate_revoke(&home, &id),
        },
        Command::Lct(l) => match l {
            LctCmd::Publish { dry_run: _, send } => cmd_lct_publish(&home, send),
        },
        Command::Hub(h) => match h {
            HubCmd::Connect { url } => cmd_hub_connect(&home, &url),
            HubCmd::List => cmd_hub_list(&home),
            HubCmd::Show { target } => cmd_hub_show(&home, &target),
            HubCmd::Disconnect { target } => cmd_hub_disconnect(&home, &target),
            HubCmd::Join { target, name } => cmd_hub_join(&home, &target, name),
            HubCmd::SetMemberKey { target, channel_key, member_lct } => {
                cmd_hub_set_member_key(&home, &target, channel_key, member_lct)
            }
        },
        Command::Constellation(c) => match c {
            ConstellationCmd::Add { name, device_type } => cmd_constellation_add(&home, &name, &device_type),
            ConstellationCmd::List => cmd_constellation_list(&home),
            ConstellationCmd::Remove { id } => cmd_constellation_remove(&home, &id),
            ConstellationCmd::Proof => cmd_constellation_proof(&home),
        },
        Command::Profile(p) => match p {
            ProfileCmd::Name { name } => cmd_profile_name(&home, &name),
            ProfileCmd::Bio { bio } => cmd_profile_bio(&home, &bio),
            ProfileCmd::Add { platform, url, visibility, label } => {
                cmd_profile_add(&home, &platform, &url, &visibility, label.as_deref())
            }
            ProfileCmd::List { tier } => cmd_profile_list(&home, tier.as_deref()),
            ProfileCmd::Remove { id } => cmd_profile_remove(&home, &id),
            ProfileCmd::Present { tier } => cmd_profile_present(&home, &tier),
            ProfileCmd::Push { target } => cmd_profile_push(&home, &target),
        },
    }
}

fn resolve_home(cli: &Cli) -> AnyResult<PathBuf> {
    if let Some(h) = &cli.home {
        return Ok(h.clone());
    }
    default_hestia_home().context("could not resolve hestia home directory")
}

/// Resolve a passphrase. Order:
/// 1. `HESTIA_PASSPHRASE` env var (for automation; not recommended for daily use)
/// 2. Prompt the TTY via rpassword
fn prompt_passphrase(prompt: &str) -> AnyResult<String> {
    if let Ok(pp) = std::env::var("HESTIA_PASSPHRASE") {
        if pp.is_empty() {
            anyhow::bail!("HESTIA_PASSPHRASE is set but empty");
        }
        return Ok(pp);
    }
    let pp = rpassword::prompt_password(prompt).context("reading passphrase")?;
    if pp.is_empty() {
        anyhow::bail!("passphrase must not be empty");
    }
    Ok(pp)
}

fn prompt_passphrase_with_confirmation() -> AnyResult<String> {
    // If env var is set, skip confirmation (automation path)
    if let Ok(pp) = std::env::var("HESTIA_PASSPHRASE") {
        if !pp.is_empty() {
            return Ok(pp);
        }
    }
    let first = rpassword::prompt_password("New passphrase: ")
        .context("reading passphrase")?;
    if first.is_empty() {
        anyhow::bail!("passphrase must not be empty");
    }
    let second = rpassword::prompt_password("Confirm: ").context("reading confirmation")?;
    if first != second {
        anyhow::bail!("passphrases do not match");
    }
    Ok(first)
}

/// Resolve a credential value. Order:
/// 1. `HESTIA_SECRET` env var (for automation)
/// 2. Prompt the TTY via rpassword
fn prompt_secret() -> AnyResult<String> {
    if let Ok(s) = std::env::var("HESTIA_SECRET") {
        if s.is_empty() {
            anyhow::bail!("HESTIA_SECRET is set but empty");
        }
        return Ok(s);
    }
    let s = rpassword::prompt_password("Credential value: ").context("reading credential")?;
    if s.is_empty() {
        anyhow::bail!("credential value must not be empty");
    }
    Ok(s)
}

// ---- commands -------------------------------------------------------------

fn cmd_init(home: &std::path::Path, force: bool, ai: bool) -> AnyResult<()> {
    std::fs::create_dir_all(home).with_context(|| format!("creating {}", home.display()))?;
    let path = vault_path(home);
    if path.exists() && !force {
        anyhow::bail!(
            "vault already exists at {}\n\
             use --force to overwrite (DESTRUCTIVE — existing credentials will be lost)",
            path.display()
        );
    }

    if ai {
        println!("Initializing Hestia in AI-autonomous mode at {}", home.display());
    } else {
        println!("Initializing Hestia at {}", home.display());
    }
    let passphrase = prompt_passphrase_with_confirmation()?;

    if force {
        Vault::init_force(path.clone(), passphrase)?;
    } else {
        Vault::init(path.clone(), passphrase)?;
    }

    if ai {
        let mut vault = Vault::open(path.clone(), std::env::var("HESTIA_PASSPHRASE")
            .unwrap_or_default())?;
        let kp = web4_core::crypto::KeyPair::generate();
        let lct_id = uuid::Uuid::new_v4();
        let pub_hex = kp.verifying_key().to_hex();

        vault.add(VaultEntry::new("ai_identity_lct_id", lct_id.to_string())
            .with_tags(vec!["identity".into(), "ai".into()]))?;
        vault.add(VaultEntry::new("ai_identity_pubkey", pub_hex.clone())
            .with_tags(vec!["identity".into(), "ai".into()]))?;

        // Store private key bytes hex-encoded
        let secret_hex: String = kp.secret_key_bytes().iter()
            .map(|b| format!("{:02x}", b))
            .collect();
        vault.add(VaultEntry::new("ai_identity_secret", secret_hex)
            .with_tags(vec!["identity".into(), "ai".into(), "secret".into()]))?;

        println!("✓ AI identity generated:");
        println!("  LCT ID:     {lct_id}");
        println!("  Public key:  {pub_hex}");
    }

    println!("✓ Vault created at {}", path.display());
    Ok(())
}

/// Whether `bind` targets a loopback interface (safe to serve without auth).
/// Non-loopback binds (0.0.0.0, ::, LAN/tailnet IPs) expose the unauthenticated
/// REST surface off-device and are refused unless explicitly allowed.
fn bind_is_loopback(bind: &str) -> bool {
    if let Ok(sa) = bind.parse::<std::net::SocketAddr>() {
        return sa.ip().is_loopback();
    }
    // Non-literal host (e.g. "localhost:7711") — only "localhost" is loopback.
    let host = bind.rsplit_once(':').map(|(h, _)| h).unwrap_or(bind);
    host.trim_start_matches('[').trim_end_matches(']').eq_ignore_ascii_case("localhost")
}

fn cmd_serve(home: &std::path::Path, bind: &str, allow_remote: bool, callback: bool) -> AnyResult<()> {
    // Default-refuse off-device binds: the daemon's REST surface
    // (/api/vault, /api/policy, /api/chain, ...) is unauthenticated, so a
    // non-loopback bind hands it to anything that can route to the port.
    // Off-device access belongs on a paired, sealed channel — not an open bind.
    if !allow_remote && !bind_is_loopback(bind) {
        anyhow::bail!(
            "refusing to bind a non-loopback address ({bind}).\n  \
             The daemon's REST surface is unauthenticated; binding off-device \
             exposes the full vault/policy/chain API to anything that can reach \
             the port (tailnet membership is not authorization).\n  \
             The phone/other devices should join your constellation and talk \
             over a sealed channel, not dial an open REST port.\n  \
             If you really mean it, pass --allow-remote (NOT recommended)."
        );
    }
    if !bind_is_loopback(bind) {
        // allow_remote was set — proceed, but make the exposure loud.
        eprintln!(
            "WARNING: serving the UNAUTHENTICATED REST surface on a non-loopback \
             address ({bind}) via --allow-remote. Anything that can route to this \
             port has full vault/policy/chain access."
        );
    }

    let path = hestia::vault::vault_path(home);
    if !path.exists() {
        anyhow::bail!(
            "no vault at {} — run `hestia init` first",
            path.display()
        );
    }
    let passphrase = prompt_passphrase("Vault passphrase: ")?;
    let vault = hestia::Vault::open(path, passphrase.clone())?;
    println!("Vault unlocked. Starting Hestia MCP server on {bind}...");

    // Write endpoint discovery file so plugins can find us
    let endpoint_file = home.join("endpoint");
    let endpoint_url = format!("http://{}/mcp", bind);
    if let Err(e) = std::fs::write(&endpoint_file, &endpoint_url) {
        tracing::warn!("failed to write endpoint discovery file: {e}");
    }

    let callback_kp = if callback {
        println!("Sovereign callback enabled at /callback");
        Some(web4_core::crypto::KeyPair::generate())
    } else {
        None
    };

    let state = hestia::server::build_state(vault, home, &passphrase)?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("building tokio runtime")?;
    runtime.block_on(hestia::server::serve_with_callback(state, bind, callback_kp))?;

    // Cleanup
    let _ = std::fs::remove_file(&endpoint_file);
    Ok(())
}

fn cmd_info(home: &std::path::Path) -> AnyResult<()> {
    let path = vault_path(home);
    println!("hestia home: {}", home.display());
    println!("vault file:  {}", path.display());
    println!(
        "vault exists: {}",
        if path.exists() { "yes" } else { "no — run `hestia init`" }
    );
    if path.exists() {
        let meta = std::fs::metadata(&path).context("reading vault metadata")?;
        println!("vault size:  {} bytes", meta.len());
    }
    Ok(())
}

fn cmd_vault_list(home: &std::path::Path) -> AnyResult<()> {
    let vault = open_vault(home)?;
    if vault.is_empty() {
        println!("(vault is empty — add credentials with `hestia vault add <name>`)");
        return Ok(());
    }
    for name in vault.list() {
        let entry = vault.get(name).unwrap();
        let scope = if entry.scope.is_empty() {
            "*".to_string()
        } else {
            entry.scope.join(",")
        };
        let consumers = if entry.allowed_consumers.is_empty() {
            "(none)".to_string()
        } else {
            entry.allowed_consumers.join(",")
        };
        println!("{name}  scope=[{scope}]  consumers=[{consumers}]");
    }
    Ok(())
}

fn cmd_vault_get(home: &std::path::Path, name: &str) -> AnyResult<()> {
    let vault = open_vault(home)?;
    let entry = vault
        .get(name)
        .ok_or_else(|| anyhow::anyhow!("credential '{name}' not found"))?;
    // Print only the value (so the CLI can be used in shell pipelines)
    println!("{}", entry.secret);
    Ok(())
}

fn cmd_vault_add(
    home: &std::path::Path,
    name: &str,
    scope: Vec<String>,
    tag: Vec<String>,
    allowed_consumers: Vec<String>,
) -> AnyResult<()> {
    let mut vault = open_vault(home)?;
    let secret = prompt_secret()?;
    let entry = VaultEntry::new(name, secret)
        .with_scope(scope)
        .with_tags(tag)
        .with_consumers(allowed_consumers);
    vault.add(entry)?;
    println!("✓ Added '{name}' to vault");
    Ok(())
}

fn cmd_vault_remove(home: &std::path::Path, name: &str) -> AnyResult<()> {
    let mut vault = open_vault(home)?;
    vault.remove(name)?;
    println!("✓ Removed '{name}' from vault");
    Ok(())
}

#[derive(clap::Subcommand, Debug)]
enum LctCmd {
    /// Build the constellation's LctPublished payload set — sovereign first,
    /// then roles — and print it (default) or send it to the connected hub's
    /// registry (`--send`). Every payload has passed the producer-side mirror
    /// of the hub's fail-closed ingest; refusals are listed with the named
    /// failing check, and any refusal blocks a send.
    Publish {
        /// Print payloads without sending (the default mode; kept explicit so
        /// scripts can say what they mean).
        #[arg(long, default_value_t = true, conflicts_with = "send")]
        dry_run: bool,
        /// Send the payload set to the connected hub's registry
        /// (POST /v1/hubs/:hub_id/lcts/publish), sovereign first.
        #[arg(long)]
        send: bool,
    },
}

fn cmd_lct_publish(home: &std::path::Path, send: bool) -> AnyResult<()> {
    let mut vault = open_vault(home)?;
    let anchor = "lct:web4:hestia:sovereign:phase1-placeholder";
    let sovereign = hestia::sovereign::Sovereign::load_or_mint(&mut vault, anchor);
    let registry =
        hestia::role_registry::load_or_mint_registry(&mut vault, anchor, &sovereign.lct_id());

    // The hub binds `published_by` to the envelope signer (hard 403 on
    // mismatch), so the publisher of record and the signing key must name ONE
    // identity. For a vault-identity member that is the vault's
    // `ai_identity_lct_id`; the HubStore's `our_lct_id` is only a cache of it
    // and can go stale (the 2026-07-13 live dry-run caught it holding the HUB
    // peer's member id) — a diverging entry is repaired here, loudly.
    let mut hubs = hestia::hub::HubStore::load(&vault).unwrap_or_default();
    let vault_identity: Option<uuid::Uuid> = vault
        .get("ai_identity_lct_id")
        .and_then(|e| e.secret.parse().ok());
    let conn_snapshot = hubs.connections.first().cloned();
    let published_by = match &conn_snapshot {
        Some(conn) => {
            let (signer, needs_repair) = hestia::hub::resolve_publish_identity(
                conn.our_lct_id,
                &conn.member_key_source,
                vault_identity,
            )?;
            if needs_repair {
                eprintln!(
                    "[lct publish] REPAIR hubs store our_lct_id for {}: {} → {} \
                     (stale cache; vault ai_identity_lct_id is authoritative)",
                    conn.url, conn.our_lct_id, signer
                );
                hubs.connections[0].our_lct_id = signer;
                hubs.save(&mut vault)?;
            }
            signer
        }
        None => {
            if send {
                anyhow::bail!("not connected to a hub — run `hestia hub connect <url>` first");
            }
            eprintln!("[lct publish] note: no hub connection — published_by is nil in this dry-run");
            uuid::Uuid::nil()
        }
    };

    let set = hestia::lct_publish::collect_publish_set(
        &sovereign,
        &registry,
        published_by,
        chrono::Utc::now(),
    );
    for (label, reason) in &set.refused {
        eprintln!("[lct publish] REFUSED {label}: {reason}");
    }

    if !send {
        println!("{}", serde_json::to_string_pretty(&set.payloads)?);
        eprintln!(
            "[lct publish] {} payload(s), {} refused (dry-run — pass --send to publish)",
            set.payloads.len(),
            set.refused.len()
        );
        return Ok(());
    }

    // Fail-closed on the way out: a refusal means the local mirror of the
    // hub's ingest found a defect. Sending around it (e.g. roles whose
    // sovereign was refused) would land avoidable dangling edges.
    if !set.refused.is_empty() {
        anyhow::bail!(
            "{} payload(s) refused by the local ingest mirror — repair before sending",
            set.refused.len()
        );
    }
    let conn = conn_snapshot.expect("send path always has a connection");
    let keypair = member_signing_keypair(&vault, &conn.member_key_source)?;
    let rest = abs_rest(&conn.url, &conn.rest_endpoint);
    let hub_id = conn.hub_lct_id;

    println!(
        "Publishing {} LCT(s) to {} (hub {hub_id}), sovereign first ...",
        set.payloads.len(),
        conn.url
    );
    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
    let client = HubClient::new();
    for (i, payload) in set.payloads.iter().enumerate() {
        let accepted = rt
            .block_on(client.publish_lct(&rest, hub_id, published_by, &keypair, payload))
            .with_context(|| {
                format!(
                    "publish {}/{} ({}) failed — {} already accepted and not rolled back \
                     (republish overwrites in place: rerun --send once repaired)",
                    i + 1,
                    set.payloads.len(),
                    payload.lct_id,
                    i
                )
            })?;
        println!(
            "  ✓ {} v{} ledger#{} ({})",
            accepted.lct_id, accepted.version, accepted.entry_index, accepted.entry_hash
        );
    }
    // Read back what the registry now serves — verification, not trust.
    match rt.block_on(client.list_lcts(&rest, hub_id)) {
        Ok(list) => {
            let n = list.as_array().map(|a| a.len()).unwrap_or(0);
            println!("Registry now lists {n} entr{}.", if n == 1 { "y" } else { "ies" });
        }
        Err(e) => eprintln!("[lct publish] published, but registry read-back failed: {e:#}"),
    }
    Ok(())
}

fn open_vault(home: &std::path::Path) -> AnyResult<Vault> {
    let path = vault_path(home);
    if !path.exists() {
        anyhow::bail!(
            "no vault at {} — run `hestia init` first",
            path.display()
        );
    }
    let passphrase = prompt_passphrase("Vault passphrase: ")?;
    let vault = Vault::open(path, passphrase)?;
    Ok(vault)
}

// ---- policy commands ------------------------------------------------------

fn cmd_policy_show(home: &std::path::Path) -> AnyResult<()> {
    let vault = open_vault(home)?;
    let state = vault.policy();
    println!("active preset: {}", state.active_preset);

    if let Some(preset) = hestia::policy::get_preset(&state.active_preset) {
        println!("description:   {}", preset.description);
        println!(
            "default:       {}  (enforce: {})",
            preset.config.default_policy.as_str(),
            preset.config.enforce
        );
    } else {
        println!("(preset '{}' is unknown — daemon will fall back to safety)", state.active_preset);
    }

    let resolved = state.resolve().unwrap_or_else(|| {
        hestia::policy::get_preset("safety").unwrap().config
    });
    println!("\nrules ({} total, after overrides):", resolved.rules.len());
    let mut sorted = resolved.rules.clone();
    sorted.sort_by_key(|r| r.priority);
    for r in &sorted {
        println!(
            "  [{:>3}] {:6}  {:32}  {}",
            r.priority,
            r.decision.as_str(),
            r.id,
            r.name
        );
    }

    if !state.overrides.is_empty() {
        println!("\noverrides ({}):", state.overrides.len());
        for (id, ov) in &state.overrides {
            let mut bits = Vec::new();
            if let Some(d) = ov.decision {
                bits.push(format!("decision={}", d.as_str()));
            }
            if let Some(enabled) = ov.enabled {
                bits.push(format!("enabled={enabled}"));
            }
            println!("  {} → {}", id, bits.join(", "));
        }
    }
    if !state.custom_rules.is_empty() {
        println!("\ncustom rules: {}", state.custom_rules.len());
    }
    if !state.role_overlays.is_empty() {
        println!("\nrole overlays (#403 — folded strictest-wins onto the base):");
        let mut roles: Vec<_> = state.role_overlays.iter().collect();
        roles.sort_by(|a, b| a.0.cmp(b.0));
        for (role, rules) in roles {
            println!("  {role}:");
            for r in rules {
                println!(
                    "    [{:>3}] {:6}  {:32}  {}",
                    r.priority,
                    r.decision.as_str(),
                    r.id,
                    r.name
                );
            }
        }
    }
    Ok(())
}

fn cmd_policy_list() -> AnyResult<()> {
    println!("Built-in presets:\n");
    for p in hestia::policy::list_presets() {
        println!(
            "  {:12}  {}\n               {} rule(s), default={}, enforce={}",
            p.name,
            p.description,
            p.config.rules.len(),
            p.config.default_policy.as_str(),
            p.config.enforce
        );
    }
    Ok(())
}

fn cmd_policy_set(home: &std::path::Path, preset: &str) -> AnyResult<()> {
    if !hestia::policy::is_preset_name(preset) {
        anyhow::bail!(
            "unknown preset: '{preset}' (expected one of: {})",
            hestia::policy::PRESET_NAMES.join(", ")
        );
    }
    let mut vault = open_vault(home)?;
    vault.set_active_preset(preset)?;
    println!("✓ active preset set to '{preset}'");
    println!("  (a running daemon won't pick this up until restart)");
    Ok(())
}

fn parse_decision_cli(s: &str) -> AnyResult<hestia::policy::PolicyDecision> {
    use hestia::policy::PolicyDecision::*;
    match s {
        "allow" => Ok(Allow),
        "warn" => Ok(Warn),
        "deny" => Ok(Deny),
        _ => anyhow::bail!("decision must be allow | warn | deny, got '{s}'"),
    }
}

fn cmd_policy_override(
    home: &std::path::Path,
    rule_id: &str,
    decision: Option<String>,
    disable: bool,
    enable: bool,
    clear: bool,
) -> AnyResult<()> {
    let mut vault = open_vault(home)?;
    if clear {
        vault.clear_policy_override(rule_id)?;
        println!("✓ override on '{rule_id}' cleared (reverted to preset default)");
    } else {
        let dec = match decision {
            Some(d) => Some(parse_decision_cli(&d)?),
            None => None,
        };
        let enabled = match (disable, enable) {
            (true, true) => anyhow::bail!("--disable and --enable are mutually exclusive"),
            (true, false) => Some(false),
            (false, true) => Some(true),
            (false, false) => None,
        };
        if dec.is_none() && enabled.is_none() {
            anyhow::bail!("nothing to change: pass --decision, --disable, --enable, or --clear");
        }
        vault.set_policy_override(rule_id, hestia::vault::PolicyOverride { decision: dec, enabled })?;
        println!("✓ override set on '{rule_id}'");
    }
    println!("  (a running daemon won't pick this up until restart)");
    Ok(())
}

/// Validate a `--role` against the published constellation set, fail-fast with
/// the valid values. A typo'd role overlay would be silently dead law (sessions
/// normalize fail-closed to known roles), so the CLI rejects it outright.
fn validate_role_cli(role: &str) -> AnyResult<()> {
    if hestia::reputation::KNOWN_CONSTELLATION_ROLES.contains(&role) {
        return Ok(());
    }
    anyhow::bail!(
        "'{role}' is not a published constellation role (no session could ever \
         select it). Valid roles:\n  {}",
        hestia::reputation::KNOWN_CONSTELLATION_ROLES.join("\n  ")
    )
}

#[allow(clippy::too_many_arguments)]
fn cmd_policy_add_rule(
    home: &std::path::Path,
    name: &str,
    decision: &str,
    category: Option<String>,
    tool: Option<String>,
    command: Option<String>,
    targets: Vec<String>,
    priority: i32,
    role: Option<String>,
) -> AnyResult<()> {
    let dec = parse_decision_cli(decision)?;
    // Specifiers are combinable: every one given must match (AND) — mirrors
    // rule_matches, where each present field is a required condition. E.g.
    // `--category file_read --target "*/.ssh/*"` = only reads of ssh key paths.
    let mut r#match = hestia::policy::PolicyMatch::default();
    if let Some(c) = category {
        r#match.categories = Some(vec![c]);
    }
    if let Some(t) = tool {
        r#match.tools = Some(vec![t]);
    }
    if let Some(cmd) = command {
        r#match.command_patterns = Some(vec![cmd]);
    }
    if !targets.is_empty() {
        r#match.target_patterns = Some(targets);
    }
    if r#match == hestia::policy::PolicyMatch::default() {
        anyhow::bail!("specify at least one of --category, --tool, --command, --target");
    }
    let slug: String = name
        .to_lowercase()
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
        .collect();
    let id = format!("custom-{}", slug.trim_matches('-'));
    let rule = hestia::policy::PolicyRule {
        id: id.clone(),
        name: name.to_string(),
        priority,
        decision: dec,
        reason: None,
        r#match,
    };
    // Validate the role BEFORE prompting for the vault passphrase — the check
    // needs no vault state, and a typo shouldn't cost the user an unlock.
    if let Some(role) = role.as_deref() {
        validate_role_cli(role)?;
    }
    let mut vault = open_vault(home)?;
    match role {
        Some(role) => {
            vault.upsert_role_rule(&role, rule)?;
            println!("✓ rule '{id}' added to role overlay '{role}'");
            println!("  (applies ONLY to sessions in that role; folded strictest-wins onto the base)");
        }
        None => {
            vault.upsert_custom_rule(rule)?;
            println!("✓ custom rule '{id}' added");
        }
    }
    println!("  (a running daemon won't pick this up until restart)");
    Ok(())
}

fn cmd_policy_rm_rule(home: &std::path::Path, id: &str, role: Option<String>) -> AnyResult<()> {
    let mut vault = open_vault(home)?;
    match role {
        // Deliberately NO validate_role_cli here: rm-rule is the only way to
        // clean up an overlay keyed to a stale/unknown role (e.g. hand-edited
        // vault, or a role later removed from the published set).
        Some(role) => {
            if vault.remove_role_rule(&role, id)? {
                println!("✓ rule '{id}' removed from role overlay '{role}'");
            } else {
                println!("no rule with id '{id}' in role overlay '{role}'");
            }
        }
        None => {
            if vault.remove_custom_rule(id)? {
                println!("✓ custom rule '{id}' removed");
            } else {
                println!("no custom rule with id '{id}'");
            }
        }
    }
    println!("  (a running daemon won't pick this up until restart)");
    Ok(())
}

// ---- profile commands -------------------------------------------------------

fn cmd_profile_name(home: &std::path::Path, name: &str) -> AnyResult<()> {
    let mut vault = open_vault(home)?;
    let mut store = ProfileStore::load(&vault)?;
    store.display_name = Some(name.to_string());
    store.save(&mut vault)?;
    println!("Display name set to: {name}");
    Ok(())
}

fn cmd_profile_bio(home: &std::path::Path, bio: &str) -> AnyResult<()> {
    let mut vault = open_vault(home)?;
    let mut store = ProfileStore::load(&vault)?;
    store.bio = Some(bio.to_string());
    store.save(&mut vault)?;
    println!("Bio updated");
    Ok(())
}

fn cmd_profile_add(
    home: &std::path::Path,
    platform: &str,
    url: &str,
    visibility: &str,
    label: Option<&str>,
) -> AnyResult<()> {
    let plat = profile::parse_platform(platform);
    let vis = profile::parse_visibility(visibility)?;

    let mut link = ProfileLink::new(plat, url, vis);
    if let Some(l) = label {
        link = link.with_label(l);
    }

    let mut vault = open_vault(home)?;
    let mut store = ProfileStore::load(&vault)?;
    store.add_link(link.clone());
    store.save(&mut vault)?;

    println!("Link added:");
    println!("  platform:   {platform}");
    println!("  url:        {url}");
    println!("  visibility: {visibility}");
    if let Some(l) = label {
        println!("  label:      {l}");
    }
    Ok(())
}

fn cmd_profile_list(home: &std::path::Path, tier: Option<&str>) -> AnyResult<()> {
    let vault = open_vault(home)?;
    let store = ProfileStore::load(&vault)?;

    if let Some(name) = &store.display_name {
        println!("{name}");
    }
    if let Some(bio) = &store.bio {
        println!("{bio}");
    }
    if store.display_name.is_some() || store.bio.is_some() {
        println!();
    }

    let links = if let Some(t) = tier {
        let vis = profile::parse_visibility(t)?;
        store.links_for_tier(&vis).into_iter().cloned().collect::<Vec<_>>()
    } else {
        store.links.clone()
    };

    if links.is_empty() {
        println!("(no links — use `hestia profile add <platform> <url>`)");
        return Ok(());
    }

    for l in &links {
        let verified = match &l.verification {
            profile::Verification::Claimed => "",
            profile::Verification::SelfVerified => " [verified]",
            profile::Verification::Attested { .. } => " [attested]",
        };
        let label = l.label.as_deref().map(|s| format!(" ({s})")).unwrap_or_default();
        println!("  {} {} [{}]{}{}", l.platform.as_str(), l.url, l.visibility.as_str(), verified, label);
        println!("    id: {}", l.id);
    }
    println!("\n{} link(s)", links.len());
    Ok(())
}

fn cmd_profile_remove(home: &std::path::Path, id: &str) -> AnyResult<()> {
    let link_id = uuid::Uuid::parse_str(id)
        .with_context(|| format!("invalid UUID: {id}"))?;
    let mut vault = open_vault(home)?;
    let mut store = ProfileStore::load(&vault)?;
    if store.remove_link(link_id) {
        store.save(&mut vault)?;
        println!("Link {link_id} removed");
    } else {
        anyhow::bail!("link {link_id} not found");
    }
    Ok(())
}

fn cmd_profile_present(home: &std::path::Path, tier: &str) -> AnyResult<()> {
    let vault = open_vault(home)?;
    let store = ProfileStore::load(&vault)?;
    let vis = profile::parse_visibility(tier)?;
    let pres = store.present(&vis);

    println!("Profile presentation (tier: {tier}):\n");
    if let Some(name) = &pres.display_name {
        println!("  {name}");
    }
    if let Some(bio) = &pres.bio {
        println!("  {bio}");
    }
    if pres.links.is_empty() {
        println!("  (no links visible at this tier)");
    } else {
        println!();
        for l in &pres.links {
            let v = if l.verified { " [verified]" } else { "" };
            let label = l.label.as_deref().map(|s| format!(" — {s}")).unwrap_or_default();
            println!("  {} {}{}{}", l.platform, l.url, v, label);
        }
    }
    Ok(())
}

fn cmd_profile_push(home: &std::path::Path, target: &str) -> AnyResult<()> {
    // One vault handle for the whole command (hub connections + identity key).
    // Mutable: a successful push lets us reconcile the local joined-state below.
    let mut vault = open_vault(home)?;
    // Resolve the hub connection.
    let mut hubs = HubStore::load(&vault)?;
    let conn = if let Ok(id) = uuid::Uuid::parse_str(target) {
        hubs.find_by_id(id)
    } else {
        hubs.find_by_url(target)
    }.ok_or_else(|| anyhow::anyhow!(
        "not connected to {target} — run `hestia hub connect <url>` first"
    ))?;

    // Sign with the key the hub *pinned* for this member. Normally that's the
    // vault identity (`hestia init --ai`); for a member whose non-interactive
    // mesh watcher pinned a raw channel key, it's that key instead — signing
    // with the sealed identity would 401 (BadSignature) against the pinned
    // channel key. The per-connection `member_key_source` records which.
    let key_source = conn.member_key_source.clone();
    let keypair = member_signing_keypair(&vault, &key_source)?;

    let profile = ProfileStore::load(&vault)?;
    let fields = profile.hub_fields();
    if fields.is_empty() {
        anyhow::bail!("profile is empty — add a name/bio/links first (`hestia profile add ...`)");
    }

    let hub_id = conn.hub_lct_id;
    let our_lct = conn.our_lct_id;
    let url = conn.url.clone();
    let rest = abs_rest(&conn.url, &conn.rest_endpoint);

    println!("Pushing {} field(s) to {} ...", fields.len(), url);
    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
    let client = HubClient::new();
    let resp = rt.block_on(client.push_profile(&rest, hub_id, our_lct, &keypair, fields))?;

    println!("Profile pushed:");
    if let Some(idx) = resp.get("entry_index") {
        println!("  ledger entry: {idx}");
    }
    if let Some(kind) = resp.get("event_kind").and_then(|v| v.as_str()) {
        println!("  event:        {kind}");
    }

    // Reconcile local joined-state from this successful member-tier act. The hub
    // only accepts a signed profile update from an *admitted* member, so a
    // successful push is proof of membership — even when we joined async and a
    // Sovereign approved us out-of-band, which never notifies the client. Flip
    // the local `hubs.json` flag so `hub list` / `hub show` stop reporting a
    // stale `pending` / `none joined`. (Sprout report 2026-06-27: joined-state
    // diverges permanently after async approval, with no local reconcile path.)
    if let Some(pos) = hubs.connections.iter()
        .position(|c| c.hub_lct_id == hub_id && c.our_lct_id == our_lct)
    {
        let was_stale = !hubs.connections[pos].hubs_joined.contains(&hub_id);
        hubs.connections[pos].last_seen = Some(chrono::Utc::now());
        if was_stale {
            hubs.connections[pos].hubs_joined.push(hub_id);
        }
        hubs.save(&mut vault)?;
        if was_stale {
            println!("  local state: reconciled — marked hub joined (was stale)");
        }
    }
    Ok(())
}

/// Resolve a possibly-relative rest endpoint against the connection base URL.
fn abs_rest(base_url: &str, rest: &str) -> String {
    if rest.starts_with("http://") || rest.starts_with("https://") {
        rest.to_string()
    } else if rest.is_empty() {
        format!("{}/v1", base_url.trim_end_matches('/'))
    } else {
        format!("{}{}", base_url.trim_end_matches('/'), rest)
    }
}

fn cmd_hub_set_member_key(
    home: &std::path::Path,
    target: &str,
    channel_key: Option<String>,
    member_lct: Option<uuid::Uuid>,
) -> AnyResult<()> {
    use hestia::hub::MemberKeySource;
    let mut vault = open_vault(home)?;
    let mut hubs = HubStore::load(&vault)?;
    let pos = if let Ok(id) = uuid::Uuid::parse_str(target) {
        hubs.connections.iter().position(|c| c.id == id || c.hub_lct_id == id)
    } else {
        hubs.connections.iter().position(|c| c.url == target)
    }.ok_or_else(|| anyhow::anyhow!(
        "not connected to {target} — run `hestia hub connect <url>` first"
    ))?;

    let source = match channel_key {
        Some(path) => {
            // Validate now: the file must be a readable 32-byte seed, so a later
            // `profile push` doesn't fail on a stale/typo'd path. Show the pubkey
            // so the operator can confirm it equals the hub's pinned key.
            let src = MemberKeySource::ChannelKeyFile { path: path.clone() };
            let kp = member_signing_keypair(&vault, &src)?;
            println!("Channel key loads OK — pubkey {}", kp.verifying_key().to_hex());
            src
        }
        None => MemberKeySource::VaultIdentity,
    };

    hubs.connections[pos].member_key_source = source.clone();
    // In channel-key mode the connection's `our_lct_id` IS the envelope signer
    // and the registry's `published_by` (resolve_publish_identity has no vault
    // authority to repair from) — record the id the hub pinned the key FOR.
    if let Some(id) = member_lct {
        if matches!(source, MemberKeySource::VaultIdentity) {
            anyhow::bail!("--member-lct only applies with --channel-key (vault identity is authoritative otherwise)");
        }
        let before = hubs.connections[pos].our_lct_id;
        hubs.connections[pos].our_lct_id = id;
        println!("our_lct_id: {before} → {id} (the member the hub pinned this key for)");
    }
    hubs.save(&mut vault)?;
    let url = &hubs.connections[pos].url;
    match &source {
        MemberKeySource::VaultIdentity =>
            println!("Member key source for {url} → vault identity (ai_identity_secret)."),
        MemberKeySource::ChannelKeyFile { path } => println!(
            "Member key source for {url} → channel key file {path}.\n\
             `hestia profile push` will now sign with it (must equal the hub's pinned key)."),
    }
    Ok(())
}

fn hex_to_32(s: &str) -> Option<[u8; 32]> {
    if s.len() != 64 { return None; }
    let mut out = [0u8; 32];
    for i in 0..32 {
        out[i] = u8::from_str_radix(&s[i*2..i*2+2], 16).ok()?;
    }
    Some(out)
}

/// Expand a leading `~/` (or bare `~`) to `$HOME`. Raw key-file paths are
/// user-supplied and often written with a tilde; `std::fs` won't expand it.
fn expand_tilde(path: &str) -> std::path::PathBuf {
    if let Some(rest) = path.strip_prefix("~/") {
        if let Ok(home) = std::env::var("HOME") {
            return std::path::Path::new(&home).join(rest);
        }
    } else if path == "~" {
        if let Ok(home) = std::env::var("HOME") {
            return std::path::PathBuf::from(home);
        }
    }
    std::path::PathBuf::from(path)
}

/// Resolve the keypair that signs member-tier acts to a hub, per its
/// `member_key_source`. `VaultIdentity` reads `ai_identity_secret` from the
/// sealed vault (default); `ChannelKeyFile` reads a raw 32-byte Ed25519 seed —
/// byte-for-byte the same format the mesh `channel_client` loads, so the CLI and
/// the watcher present the *same* pinned key to the hub.
fn member_signing_keypair(
    vault: &hestia::vault::Vault,
    source: &hestia::hub::MemberKeySource,
) -> AnyResult<web4_core::crypto::KeyPair> {
    use hestia::hub::MemberKeySource;
    match source {
        MemberKeySource::VaultIdentity => {
            let secret_hex = vault.get("ai_identity_secret").map(|e| e.secret.clone())
                .ok_or_else(|| anyhow::anyhow!(
                    "no member identity key in vault — run `hestia init --ai`, or self-add to the hub \
                     so it pins your pubkey (Sovereign-seeded members can't push from here yet)"
                ))?;
            let secret_bytes = hex_to_32(&secret_hex)
                .ok_or_else(|| anyhow::anyhow!("ai_identity_secret is not 32-byte hex"))?;
            Ok(web4_core::crypto::KeyPair::from_secret_bytes(&secret_bytes))
        }
        MemberKeySource::ChannelKeyFile { path } => {
            let p = expand_tilde(path);
            let raw = std::fs::read(&p)
                .with_context(|| format!("reading channel key file {}", p.display()))?;
            let seed: [u8; 32] = raw.as_slice().try_into().map_err(|_| anyhow::anyhow!(
                "channel key file {} must be exactly 32 bytes (got {})", p.display(), raw.len()
            ))?;
            Ok(web4_core::crypto::KeyPair::from_secret_bytes(&seed))
        }
    }
}

// ---- constellation commands -------------------------------------------------

fn cmd_constellation_add(home: &std::path::Path, name: &str, device_type: &str) -> AnyResult<()> {
    let dt = match device_type {
        "desktop" => DeviceType::Desktop,
        "mobile" => DeviceType::Mobile,
        "server" => DeviceType::Server,
        "agent" => DeviceType::Agent,
        "hardware" => DeviceType::Hardware,
        other => anyhow::bail!("unknown device type: {other} (expected: desktop, mobile, server, agent, hardware)"),
    };

    let kp = web4_core::crypto::KeyPair::generate();
    let pubkey_hex = kp.verifying_key().to_hex();

    let mut vault = open_vault(home)?;
    let mut store = ConstellationStore::load(&vault)?;
    if store.owner_lct_id.is_none() {
        store.owner_lct_id = Some(uuid::Uuid::new_v4());
    }
    let member = store.add_device(name, dt, &pubkey_hex, vec![]);
    let lct_id = member.lct_id;
    store.save(&mut vault)?;

    println!("Device added to constellation:");
    println!("  name:    {name}");
    println!("  type:    {device_type}");
    println!("  LCT ID:  {lct_id}");
    println!("  pubkey:  {}", &pubkey_hex[..16]);
    Ok(())
}

fn cmd_constellation_list(home: &std::path::Path) -> AnyResult<()> {
    let vault = open_vault(home)?;
    let store = ConstellationStore::load(&vault)?;

    if store.members.is_empty() {
        println!("(no devices in constellation — use `hestia constellation add <name>`)");
        return Ok(());
    }

    if let Some(owner) = store.owner_lct_id {
        println!("Owner: {owner}");
    }
    println!();
    for m in &store.members {
        println!("{} — {} ({:?})", m.lct_id, m.name, m.device_type);
        println!("  pubkey:    {}...", &m.pubkey_hex[..16]);
        println!("  added:     {}", m.added_at.format("%Y-%m-%d %H:%M"));
        if let Some(seen) = m.last_seen {
            println!("  last seen: {}", seen.format("%Y-%m-%d %H:%M"));
        }
        println!();
    }
    println!("{} device(s)", store.members.len());
    Ok(())
}

fn cmd_constellation_remove(home: &std::path::Path, id: &str) -> AnyResult<()> {
    let lct_id = uuid::Uuid::parse_str(id)
        .with_context(|| format!("invalid UUID: {id}"))?;
    let mut vault = open_vault(home)?;
    let mut store = ConstellationStore::load(&vault)?;
    if store.remove_device(lct_id) {
        store.save(&mut vault)?;
        println!("Device {lct_id} removed from constellation");
    } else {
        anyhow::bail!("device {lct_id} not found in constellation");
    }
    Ok(())
}

fn cmd_constellation_proof(home: &std::path::Path) -> AnyResult<()> {
    let vault = open_vault(home)?;
    let store = ConstellationStore::load(&vault)?;
    let proof = store.proof();
    println!("Constellation proof:");
    println!("  owner:      {}", proof.owner_lct_id);
    println!("  members:    {}", proof.member_count);
    println!("  assurance:  {:?}", proof.assurance_level);
    println!("  issued:     {}", proof.issued_at.format("%Y-%m-%d %H:%M UTC"));
    for id in &proof.members {
        println!("    {id}");
    }
    Ok(())
}

// ---- delegation commands ----------------------------------------------------

fn cmd_delegate_grant(
    home: &std::path::Path,
    agent: &str,
    role_names: Vec<String>,
    actions: Vec<String>,
    expires: Option<u64>,
) -> AnyResult<()> {
    let agent_id = uuid::Uuid::parse_str(agent)
        .with_context(|| format!("invalid agent UUID: {agent}"))?;

    let roles: Vec<_> = role_names.iter()
        .map(|r| delegation::parse_role(r))
        .collect::<Result<_, _>>()?;

    // For now, use a fresh keypair as the delegator.
    // In production, this would come from the vault's LCT identity.
    let delegator_kp = web4_core::crypto::KeyPair::generate();
    let delegator_id = uuid::Uuid::new_v4();

    let mut vault = open_vault(home)?;
    let mut store = DelegationStore::load(&vault)?;
    let deleg = store.create_delegation(
        delegator_id,
        agent_id,
        roles,
        actions,
        expires,
        &delegator_kp,
    );

    let id = deleg.id;
    let exp = deleg.expires_at
        .map(|e| e.format("%Y-%m-%d %H:%M UTC").to_string())
        .unwrap_or_else(|| "never".into());

    store.save(&mut vault)?;
    println!("Delegation created:");
    println!("  id:      {id}");
    println!("  agent:   {agent_id}");
    println!("  expires: {exp}");
    Ok(())
}

fn cmd_delegate_list(home: &std::path::Path) -> AnyResult<()> {
    let vault = open_vault(home)?;
    let store = DelegationStore::load(&vault)?;
    let active = store.active();

    if active.is_empty() {
        println!("(no active delegations)");
        return Ok(());
    }

    for d in active {
        let roles: Vec<String> = d.scope.roles.iter()
            .map(|r| format!("{:?}", r))
            .collect();
        let role_str = if roles.is_empty() { "*".into() } else { roles.join(", ") };
        let exp = d.expires_at
            .map(|e| e.format("%Y-%m-%d %H:%M").to_string())
            .unwrap_or_else(|| "never".into());

        println!("{} → agent={} roles=[{}] expires={}",
            d.id, d.agent_lct_id, role_str, exp);
    }
    println!("\n{} active delegation(s), {} total", store.active().len(), store.delegations.len());
    Ok(())
}

fn cmd_delegate_revoke(home: &std::path::Path, id: &str) -> AnyResult<()> {
    let delegation_id = uuid::Uuid::parse_str(id)
        .with_context(|| format!("invalid delegation UUID: {id}"))?;

    let mut vault = open_vault(home)?;
    let mut store = DelegationStore::load(&vault)?;
    store.revoke(delegation_id)?;
    store.save(&mut vault)?;
    println!("Delegation {delegation_id} revoked");
    Ok(())
}

// ---- hub commands -----------------------------------------------------------

fn cmd_hub_connect(home: &std::path::Path, url: &str) -> AnyResult<()> {
    let mut vault = open_vault(home)?;
    let mut store = HubStore::load(&vault)?;

    if store.find_by_url(url).is_some() {
        anyhow::bail!("already connected to {url}");
    }

    println!("Discovering hub at {url}...");
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all().build()?;

    let client = HubClient::new();
    let info = rt.block_on(client.discover(url))?;

    println!("  hub LCT:      {}", info.hub_lct_id);
    println!("  API versions: {:?}", info.api_versions);
    println!("  REST:         {}", info.endpoints.rest);
    println!("  hubs:         {} available", info.hubs.len());
    for ch in &info.hubs {
        println!("    - {} ({})", ch.name, if ch.public { "public" } else { "private" });
    }

    let our_lct_id = uuid::Uuid::new_v4();
    let api_version = info.api_versions.first()
        .cloned()
        .unwrap_or_else(|| "v1".into());

    let conn = hestia::hub::HubConnection {
        id: uuid::Uuid::new_v4(),
        url: url.to_string(),
        hub_lct_id: info.hub_lct_id,
        our_lct_id,
        connected_at: chrono::Utc::now(),
        last_seen: Some(chrono::Utc::now()),
        api_version,
        // Discovery may advertise a relative rest path (e.g. "/v1"); store it
        // absolute so request builders always have a base.
        rest_endpoint: abs_rest(url, &info.endpoints.rest),
        hubs_joined: vec![],
        member_key_source: Default::default(),
    };

    store.connections.push(conn);
    store.save(&mut vault)?;
    println!("\nConnected to {url} (id: {our_lct_id})");
    Ok(())
}

fn cmd_hub_list(home: &std::path::Path) -> AnyResult<()> {
    let vault = open_vault(home)?;
    let store = HubStore::load(&vault)?;

    if store.connections.is_empty() {
        println!("(no hub connections — use `hestia hub connect <url>` to connect)");
        return Ok(());
    }

    for conn in &store.connections {
        let age = chrono::Utc::now() - conn.connected_at;
        let joined = if conn.hubs_joined.is_empty() {
            "none".into()
        } else {
            format!("{}", conn.hubs_joined.len())
        };
        println!("{} → {} (connected {}d ago, {} hubs joined)",
            conn.id, conn.url, age.num_days(), joined);
    }
    println!("\n{} connection(s)", store.connections.len());
    Ok(())
}

fn cmd_hub_show(home: &std::path::Path, target: &str) -> AnyResult<()> {
    let vault = open_vault(home)?;
    let store = HubStore::load(&vault)?;

    let conn = if let Ok(id) = uuid::Uuid::parse_str(target) {
        store.find_by_id(id)
    } else {
        store.find_by_url(target)
    };

    let conn = conn.ok_or_else(|| anyhow::anyhow!("hub connection not found: {target}"))?;

    println!("id:             {}", conn.id);
    println!("url:            {}", conn.url);
    println!("hub LCT:        {}", conn.hub_lct_id);
    println!("our LCT:        {}", conn.our_lct_id);
    println!("connected:      {}", conn.connected_at.format("%Y-%m-%d %H:%M UTC"));
    println!("last seen:      {}", conn.last_seen
        .map(|t| t.format("%Y-%m-%d %H:%M UTC").to_string())
        .unwrap_or_else(|| "never".into()));
    println!("API version:    {}", conn.api_version);
    println!("REST endpoint:  {}", conn.rest_endpoint);
    println!("hubs joined: {}", if conn.hubs_joined.is_empty() {
        "none".into()
    } else {
        conn.hubs_joined.iter().map(|c| c.to_string()).collect::<Vec<_>>().join(", ")
    });
    Ok(())
}

fn cmd_hub_disconnect(home: &std::path::Path, target: &str) -> AnyResult<()> {
    let mut vault = open_vault(home)?;
    let mut store = HubStore::load(&vault)?;

    let idx = if let Ok(id) = uuid::Uuid::parse_str(target) {
        store.connections.iter().position(|c| c.id == id)
    } else {
        store.connections.iter().position(|c| c.url == target)
    };

    let idx = idx.ok_or_else(|| anyhow::anyhow!("hub connection not found: {target}"))?;
    let removed = store.connections.remove(idx);
    store.save(&mut vault)?;
    println!("Disconnected from {} ({})", removed.url, removed.id);
    Ok(())
}

/// Load the member identity (LCT + keypair) from the vault, creating and
/// persisting one if absent. The pubkey of this key is what a hub pins at
/// self-add, so the same identity must back both `join` and `push`.
fn ensure_member_identity(
    vault: &mut Vault,
) -> AnyResult<(uuid::Uuid, web4_core::crypto::KeyPair)> {
    if let (Some(lct_e), Some(sec_e)) = (vault.get("ai_identity_lct_id"), vault.get("ai_identity_secret")) {
        let lct = uuid::Uuid::parse_str(&lct_e.secret)
            .context("ai_identity_lct_id is not a UUID")?;
        let bytes = hex_to_32(&sec_e.secret)
            .ok_or_else(|| anyhow::anyhow!("ai_identity_secret is not 32-byte hex"))?;
        return Ok((lct, web4_core::crypto::KeyPair::from_secret_bytes(&bytes)));
    }

    // Provision a fresh member identity.
    let kp = web4_core::crypto::KeyPair::generate();
    let lct = uuid::Uuid::new_v4();
    let secret_hex: String = kp.secret_key_bytes().iter().map(|b| format!("{b:02x}")).collect();
    vault.add(VaultEntry::new("ai_identity_lct_id", lct.to_string())
        .with_tags(vec!["identity".into()]))?;
    vault.add(VaultEntry::new("ai_identity_pubkey", kp.verifying_key().to_hex())
        .with_tags(vec!["identity".into()]))?;
    vault.add(VaultEntry::new("ai_identity_secret", secret_hex)
        .with_tags(vec!["identity".into(), "secret".into()]))?;
    Ok((lct, kp))
}

fn cmd_hub_join(home: &std::path::Path, target: &str, name: Option<String>) -> AnyResult<()> {
    let mut vault = open_vault(home)?;
    let mut store = HubStore::load(&vault)?;
    let (conn_idx, hub_id, rest, url) = {
        let pos = if let Ok(id) = uuid::Uuid::parse_str(target) {
            store.connections.iter().position(|c| c.id == id)
        } else {
            store.connections.iter().position(|c| c.url == target)
        }.ok_or_else(|| anyhow::anyhow!(
            "not connected to {target} — run `hestia hub connect <url>` first"
        ))?;
        let c = &store.connections[pos];
        (pos, c.hub_lct_id, abs_rest(&c.url, &c.rest_endpoint), c.url.clone())
    };

    let (member_lct, keypair) = ensure_member_identity(&mut vault)?;

    println!("Self-adding to {url} as {member_lct} ...");
    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
    let client = HubClient::new();
    let outcome = rt.block_on(client.join(&rest, hub_id, member_lct, &keypair, name))?;

    // Point the connection at the joined identity so `push` uses the pinned key.
    store.connections[conn_idx].our_lct_id = member_lct;
    store.save(&mut vault)?;

    match outcome {
        hestia::hub::JoinOutcome::Admitted(resp) => {
            println!("Admitted:");
            if let Some(w) = resp.get("welcome").and_then(|v| v.as_str()) {
                println!("  {w}");
            }
            if let Some(idx) = resp.get("entry_index") {
                println!("  ledger entry: {idx}");
            }
            println!("  member LCT:   {member_lct}");
            println!("\nProfile pushes will now verify. Try: hestia profile push {url}");
        }
        hestia::hub::JoinOutcome::Escalated { reason } => {
            println!("Submitted — pending Sovereign approval (NOT yet a member):");
            println!("  {reason}");
            println!("  member LCT:   {member_lct} (identity saved to vault)");
            println!("\nThis hub's law gates admission. A Sovereign must approve the");
            println!("join before `profile push` will verify. Your identity is provisioned");
            println!("and saved to the vault. Admission is async and the client is not");
            println!("notified, so local state stays 'pending' until you reconcile:");
            println!("  • after approval, re-run `hestia hub join {url}` (harmless to");
            println!("    repeat) to resync local state, or");
            println!("  • `hestia profile push {url}` — it fails until approved and");
            println!("    succeeds once admitted, so it doubles as the admission probe.");
        }
    }
    Ok(())
}

fn cmd_policy_test(
    home: &std::path::Path,
    tool: &str,
    target: &str,
) -> AnyResult<()> {
    use hestia::policy::{PolicyAction, PolicyEngine};

    let vault = open_vault(home)?;
    let cfg = vault
        .policy()
        .resolve()
        .unwrap_or_else(|| hestia::policy::get_preset("safety").unwrap().config);
    let engine = PolicyEngine::new(cfg);

    let category = hestia::policy::classify(tool);
    // For Bash/Shell, the user-supplied "target" IS the full command.
    // We pass the full command as both `target` (so target_patterns
    // like `rm\s+-` match) and as `full_command` (so command_patterns
    // match). For non-shell tools, target is the file path / URL.
    let full_command: Option<&str> = if tool == "Bash" || tool == "Shell" {
        Some(target)
    } else {
        None
    };
    let pa = PolicyAction {
        tool_name: tool,
        category,
        target: Some(target),
        full_command,
    };
    let v = engine.evaluate(&pa);
    println!("decision:  {}", v.decision.as_str());
    println!("reason:    {}", v.reason);
    println!("ruleId:    {}", v.rule_id.as_deref().unwrap_or("(default)"));
    println!("ruleName:  {}", v.rule_name.as_deref().unwrap_or("(default)"));
    println!("enforced:  {}", v.enforced);
    println!("constraints:");
    for c in &v.constraints {
        println!("  - {c}");
    }
    Ok(())
}

#[cfg(test)]
mod serve_guard_tests {
    use super::bind_is_loopback;

    #[test]
    fn loopback_binds_are_allowed() {
        assert!(bind_is_loopback("127.0.0.1:7711"));
        assert!(bind_is_loopback("127.0.0.5:80"));
        assert!(bind_is_loopback("[::1]:7711"));
        assert!(bind_is_loopback("localhost:7711"));
        assert!(bind_is_loopback("LocalHost:7711"));
    }

    #[test]
    fn non_loopback_binds_are_refused() {
        assert!(!bind_is_loopback("0.0.0.0:7711"));
        assert!(!bind_is_loopback("[::]:7711"));
        assert!(!bind_is_loopback("192.168.1.20:7711"));
        assert!(!bind_is_loopback("100.75.141.17:7711")); // tailnet IP
    }
}

#[cfg(test)]
mod member_key_source_tests {
    use super::{expand_tilde, member_signing_keypair};
    use hestia::hub::MemberKeySource;
    use hestia::vault::{Vault, VaultEntry};

    // A fixed 32-byte Ed25519 seed → a deterministic pubkey we can assert on.
    const SEED: [u8; 32] = [7u8; 32];

    // Independently-computed golden vector: the RFC-8032 Ed25519 public key for
    // `SEED`, produced OUTSIDE this crate (python `cryptography`:
    // `Ed25519PrivateKey.from_private_bytes(bytes([7]*32)).public_key()...raw().hex()`).
    // Asserting against this literal — not against `from_secret_bytes(SEED)` — is
    // what makes the parity tests non-tautological: a divergence between
    // web4_core's derivation and the mesh `channel_client`'s (the exact failure
    // that would resurface the profile-push 401) is a divergence from the Ed25519
    // standard, and this constant pins the standard. The real end-to-end proof is
    // Sprout's live fixture (channel_key.bin → e367397c… == the hub's pinned key);
    // its seed is secret, so this test uses a non-secret seed with the same math.
    const EXPECTED_PUBKEY: &str =
        "ea4a6c63e29c520abef5507b132ec5f9954776aebebe7b92421eea691446d22c";

    fn expected_pubkey() -> String {
        EXPECTED_PUBKEY.to_string()
    }

    fn tmp_vault(dir: &std::path::Path) -> Vault {
        Vault::init_force(dir.join("vault.enc"), "test-pass".into()).unwrap()
    }

    #[test]
    fn channel_key_file_loads_same_pubkey_the_mesh_watcher_presents() {
        // The mesh `channel_client` reads a raw 32-byte seed and does
        // `KeyPair::from_secret_bytes`. hestia must derive the SAME pubkey, or
        // `profile push` signs with a different key than the hub pinned → 401.
        let tmp = tempfile::tempdir().unwrap();
        let key_path = tmp.path().join("channel_key.bin");
        std::fs::write(&key_path, SEED).unwrap();
        let vault = tmp_vault(tmp.path());

        let src = MemberKeySource::ChannelKeyFile { path: key_path.to_string_lossy().into() };
        let kp = member_signing_keypair(&vault, &src).unwrap();
        assert_eq!(kp.verifying_key().to_hex(), expected_pubkey());
    }

    #[test]
    fn vault_identity_loads_from_ai_identity_secret() {
        let tmp = tempfile::tempdir().unwrap();
        let mut vault = tmp_vault(tmp.path());
        let seed_hex: String = SEED.iter().map(|b| format!("{b:02x}")).collect();
        vault.upsert(VaultEntry::new("ai_identity_secret", seed_hex)).unwrap();

        let kp = member_signing_keypair(&vault, &MemberKeySource::VaultIdentity).unwrap();
        assert_eq!(kp.verifying_key().to_hex(), expected_pubkey());
    }

    #[test]
    fn channel_key_file_wrong_size_is_rejected() {
        let tmp = tempfile::tempdir().unwrap();
        let key_path = tmp.path().join("short.bin");
        std::fs::write(&key_path, [1u8; 16]).unwrap(); // not 32 bytes
        let vault = tmp_vault(tmp.path());

        let src = MemberKeySource::ChannelKeyFile { path: key_path.to_string_lossy().into() };
        let err = match member_signing_keypair(&vault, &src) {
            Ok(_) => panic!("expected a size error for a 16-byte key file"),
            Err(e) => e.to_string(),
        };
        assert!(err.contains("32 bytes"), "unexpected error: {err}");
    }

    #[test]
    fn expand_tilde_expands_leading_home() {
        std::env::set_var("HOME", "/home/tester");
        assert_eq!(expand_tilde("~/.web4/x/channel_key.bin"),
                   std::path::PathBuf::from("/home/tester/.web4/x/channel_key.bin"));
        assert_eq!(expand_tilde("/abs/path"), std::path::PathBuf::from("/abs/path"));
        assert_eq!(expand_tilde("~"), std::path::PathBuf::from("/home/tester"));
    }
}
