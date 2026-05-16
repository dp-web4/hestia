//! Hestia CLI — `hestia` binary.
//!
//! Phase 1 commands focus on vault management. The MCP server / society
//! state commands come in later sessions.

use anyhow::{Context, Result as AnyResult};
use clap::{Parser, Subcommand};
use std::path::PathBuf;

use hestia_core::vault::{default_hestia_home, vault_path, Vault, VaultEntry};

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
        Command::Dashboard { endpoint } => hestia_core::tui::run(&endpoint),
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
    let path = hestia_core::vault::vault_path(home);
    if !path.exists() {
        anyhow::bail!(
            "no vault at {} — run `hestia init` first",
            path.display()
        );
    }
    let passphrase = prompt_passphrase("Vault passphrase: ")?;
    let vault = hestia_core::Vault::open(path, passphrase)?;
    println!("Vault unlocked. Starting Hestia MCP server on {bind}...");

    // Write endpoint discovery file so plugins can find us
    let endpoint_file = home.join("endpoint");
    let endpoint_url = format!("http://{}/mcp", bind);
    if let Err(e) = std::fs::write(&endpoint_file, &endpoint_url) {
        tracing::warn!("failed to write endpoint discovery file: {e}");
    }

    let state = hestia_core::server::build_state(vault, home)?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("building tokio runtime")?;
    runtime.block_on(hestia_core::server::serve(state, bind))?;

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
