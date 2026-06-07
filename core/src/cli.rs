//! Hestia CLI — `hestia` binary.
//!
//! Phase 1 commands focus on vault management. The MCP server / society
//! state commands come in later sessions.

use anyhow::{Context, Result as AnyResult};
use clap::{Parser, Subcommand};
use std::path::PathBuf;

use hestia::delegation::{self, DelegationStore};
use hestia::hub::{HubClient, HubStore};
use hestia::vault::{default_hestia_home, vault_path, Vault, VaultEntry};

#[derive(Parser, Debug)]
#[command(
    name = "hestia",
    version,
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
    },

    /// Show hestia home + vault info
    Info,

    /// Run the MCP server daemon
    Serve {
        /// Bind address (default 127.0.0.1:7711)
        #[arg(long, default_value = "127.0.0.1:7711")]
        bind: String,
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
        Command::Init { force } => cmd_init(&home, force),
        Command::Info => cmd_info(&home),
        Command::Serve { bind } => cmd_serve(&home, &bind),
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
        },
        Command::Delegate(d) => match d {
            DelegateCmd::Grant { agent, role, action, expires } => {
                cmd_delegate_grant(&home, &agent, role, action, expires)
            }
            DelegateCmd::List => cmd_delegate_list(&home),
            DelegateCmd::Revoke { id } => cmd_delegate_revoke(&home, &id),
        },
        Command::Hub(h) => match h {
            HubCmd::Connect { url } => cmd_hub_connect(&home, &url),
            HubCmd::List => cmd_hub_list(&home),
            HubCmd::Show { target } => cmd_hub_show(&home, &target),
            HubCmd::Disconnect { target } => cmd_hub_disconnect(&home, &target),
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

fn cmd_init(home: &std::path::Path, force: bool) -> AnyResult<()> {
    std::fs::create_dir_all(home).with_context(|| format!("creating {}", home.display()))?;
    let path = vault_path(home);
    if path.exists() && !force {
        anyhow::bail!(
            "vault already exists at {}\n\
             use --force to overwrite (DESTRUCTIVE — existing credentials will be lost)",
            path.display()
        );
    }

    println!("Initializing Hestia at {}", home.display());
    let passphrase = prompt_passphrase_with_confirmation()?;

    if force {
        Vault::init_force(path.clone(), passphrase)?;
    } else {
        Vault::init(path.clone(), passphrase)?;
    }
    println!("✓ Empty vault created at {}", path.display());
    Ok(())
}

fn cmd_serve(home: &std::path::Path, bind: &str) -> AnyResult<()> {
    let path = hestia::vault::vault_path(home);
    if !path.exists() {
        anyhow::bail!(
            "no vault at {} — run `hestia init` first",
            path.display()
        );
    }
    let passphrase = prompt_passphrase("Vault passphrase: ")?;
    let vault = hestia::Vault::open(path, passphrase)?;
    println!("Vault unlocked. Starting Hestia MCP server on {bind}...");

    // Write endpoint discovery file so plugins can find us
    let endpoint_file = home.join("endpoint");
    let endpoint_url = format!("http://{}/mcp", bind);
    if let Err(e) = std::fs::write(&endpoint_file, &endpoint_url) {
        tracing::warn!("failed to write endpoint discovery file: {e}");
    }

    let state = hestia::server::build_state(vault, home)?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("building tokio runtime")?;
    runtime.block_on(hestia::server::serve(state, bind))?;

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

    let mut store = DelegationStore::load(home)?;
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

    store.save(home)?;
    println!("Delegation created:");
    println!("  id:      {id}");
    println!("  agent:   {agent_id}");
    println!("  expires: {exp}");
    Ok(())
}

fn cmd_delegate_list(home: &std::path::Path) -> AnyResult<()> {
    let store = DelegationStore::load(home)?;
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

    let mut store = DelegationStore::load(home)?;
    store.revoke(delegation_id)?;
    store.save(home)?;
    println!("Delegation {delegation_id} revoked");
    Ok(())
}

// ---- hub commands -----------------------------------------------------------

fn cmd_hub_connect(home: &std::path::Path, url: &str) -> AnyResult<()> {
    let mut store = HubStore::load(home)?;

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
    println!("  chapters:     {} available", info.chapters.len());
    for ch in &info.chapters {
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
        rest_endpoint: info.endpoints.rest,
        chapters_joined: vec![],
    };

    store.connections.push(conn);
    store.save(home)?;
    println!("\nConnected to {url} (id: {our_lct_id})");
    Ok(())
}

fn cmd_hub_list(home: &std::path::Path) -> AnyResult<()> {
    let store = HubStore::load(home)?;

    if store.connections.is_empty() {
        println!("(no hub connections — use `hestia hub connect <url>` to connect)");
        return Ok(());
    }

    for conn in &store.connections {
        let age = chrono::Utc::now() - conn.connected_at;
        let chapters = if conn.chapters_joined.is_empty() {
            "none".into()
        } else {
            format!("{}", conn.chapters_joined.len())
        };
        println!("{} → {} (connected {}d ago, {} chapters joined)",
            conn.id, conn.url, age.num_days(), chapters);
    }
    println!("\n{} connection(s)", store.connections.len());
    Ok(())
}

fn cmd_hub_show(home: &std::path::Path, target: &str) -> AnyResult<()> {
    let store = HubStore::load(home)?;

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
    println!("chapters joined: {}", if conn.chapters_joined.is_empty() {
        "none".into()
    } else {
        conn.chapters_joined.iter().map(|c| c.to_string()).collect::<Vec<_>>().join(", ")
    });
    Ok(())
}

fn cmd_hub_disconnect(home: &std::path::Path, target: &str) -> AnyResult<()> {
    let mut store = HubStore::load(home)?;

    let idx = if let Ok(id) = uuid::Uuid::parse_str(target) {
        store.connections.iter().position(|c| c.id == id)
    } else {
        store.connections.iter().position(|c| c.url == target)
    };

    let idx = idx.ok_or_else(|| anyhow::anyhow!("hub connection not found: {target}"))?;
    let removed = store.connections.remove(idx);
    store.save(home)?;
    println!("Disconnected from {} ({})", removed.url, removed.id);
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
