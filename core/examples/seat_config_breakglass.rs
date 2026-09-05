//! Break-glass operator access to vault-backed seat configuration.
//!
//! This exists for one reason: the vault-authored runtime-config cutover must not be able to
//! lock the operator out of the configuration that controls it.
//!
//! NORMAL ONLINE WRITES belong through the operator-gated daemon surface (`PUT
//! /api/config/seat`) so the daemon's in-memory vault, rendered projection and witness chain
//! move together. This example is deliberately an OFFLINE recovery path for the case where the
//! daemon or operator UI cannot start because configuration is bad.
//!
//! No path is guessed here. `HESTIA_HOME` is required explicitly; there is no `~/.hestia`, cwd,
//! checkout, or other familiar-location fallback. `HESTIA_PASSPHRASE` is also required.
//!
//! Usage:
//!
//!   HESTIA_HOME=/... HESTIA_PASSPHRASE=... \
//!     cargo run --manifest-path core/Cargo.toml --example seat_config_breakglass -- list
//!
//!   ... -- get claude-code
//!
//!   # OFFLINE ONLY: stop the daemon first, then explicitly acknowledge the requirement.
//!   ... -- set claude-code config.json --offline-confirmed
//!
//! The JSON file for `set` is exactly `SeatConfig`:
//! `{ "env": {"HESTIA_WORKSPACE":"..."}, "note":"..." }`.

use anyhow::{Context, Result};
use hestia::server::seat_config::{verify_one, SeatConfig, SEAT_CONFIG_NS};
use hestia::vault::{vault_path, Vault};
use std::io::Read;
use std::path::{Path, PathBuf};

fn required_env(name: &str) -> Result<String> {
    std::env::var(name).with_context(|| format!("{name} is required; no path/default fallback is permitted"))
}

fn home() -> Result<PathBuf> {
    let raw = required_env("HESTIA_HOME")?;
    if raw.trim().is_empty() {
        anyhow::bail!("HESTIA_HOME is empty; an explicit bootstrap locator is required");
    }
    Ok(PathBuf::from(raw))
}

fn open_vault(home: &Path) -> Result<Vault> {
    let passphrase = required_env("HESTIA_PASSPHRASE")?;
    Vault::open(vault_path(home), passphrase).context("open Hestia vault")
}

fn read_config(vault: &Vault, member: &str) -> Result<SeatConfig> {
    let bytes = vault
        .get_document(SEAT_CONFIG_NS, member)
        .with_context(|| format!("no vault seat-config document for {member:?}"))?;
    let cfg: SeatConfig = serde_json::from_slice(bytes)
        .with_context(|| format!("seat-config for {member:?} is not valid SeatConfig JSON"))?;
    cfg.validate().map_err(anyhow::Error::msg)?;
    Ok(cfg)
}

fn cmd_list(vault: &Vault, home: &Path) -> Result<()> {
    let mut members: Vec<String> = vault
        .document_index()
        .into_iter()
        .filter(|item| item.namespace == SEAT_CONFIG_NS)
        .map(|item| item.name)
        .collect();
    members.sort();
    members.dedup();

    for member in members {
        match read_config(vault, &member) {
            Ok(cfg) => {
                let verdict = verify_one(home, &member, &cfg);
                println!(
                    "{}\t{}\t{}",
                    member,
                    verdict.status(),
                    cfg.env.keys().cloned().collect::<Vec<_>>().join(",")
                );
            }
            Err(e) => println!("{}\tunreadable\t{}", member, e),
        }
    }
    Ok(())
}

fn cmd_get(vault: &Vault, home: &Path, member: &str) -> Result<()> {
    let cfg = read_config(vault, member)?;
    let verdict = verify_one(home, member, &cfg);
    let out = serde_json::json!({
        "member": member,
        "config": cfg,
        "projection_verdict": verdict,
    });
    println!("{}", serde_json::to_string_pretty(&out)?);
    Ok(())
}

fn read_json_source(source: &str) -> Result<Vec<u8>> {
    if source == "-" {
        let mut bytes = Vec::new();
        std::io::stdin().read_to_end(&mut bytes)?;
        Ok(bytes)
    } else {
        std::fs::read(source).with_context(|| format!("read config JSON from {source:?}"))
    }
}

fn cmd_set(home: &Path, member: &str, source: &str, offline_confirmed: bool) -> Result<()> {
    if !offline_confirmed {
        anyhow::bail!(
            "REFUSED: direct vault mutation is recovery-only. Stop the daemon, then repeat with \
             --offline-confirmed. Normal online edits must use the operator-gated daemon surface."
        );
    }
    if member.trim().is_empty()
        || member.contains('/')
        || member.contains('\\')
        || member.contains("..")
        || member.starts_with('.')
    {
        anyhow::bail!("member id is not a safe seat-config document name");
    }

    let bytes = read_json_source(source)?;
    let cfg: SeatConfig = serde_json::from_slice(&bytes).context("parse SeatConfig JSON")?;
    cfg.validate().map_err(anyhow::Error::msg)?;

    // Re-open only at the write boundary so list/get never accidentally become writers.
    // The flag above records operator intent; the lease below proves the normal daemon writer
    // is actually absent. If Hestia still owns the vault, this refuses before any mutation.
    let mut vault = open_vault(home)?;
    vault
        .hold_writer_lease()
        .context("REFUSED: Hestia vault writer is still active; stop the daemon before break-glass set")?;

    let canonical = serde_json::to_vec(&cfg)?;
    vault
        .put_document(SEAT_CONFIG_NS, member, canonical)
        .context("write seat-config into vault")?;

    // Do NOT render here. Startup/runtime projection is the daemon's job; an offline rescue tool
    // must repair the authority, not create a second renderer whose behaviour can drift.
    println!("updated vault seat-config for {member}; start Hestia to render and verify it");
    Ok(())
}

fn usage() -> ! {
    eprintln!(
        "usage:\n  seat_config_breakglass list\n  seat_config_breakglass get <member>\n  \
         seat_config_breakglass set <member> <json-file|-> --offline-confirmed\n\n\
         requires HESTIA_HOME and HESTIA_PASSPHRASE; no path defaults are used"
    );
    std::process::exit(2)
}

fn main() -> Result<()> {
    let home = home()?;
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.as_slice() {
        [cmd] if cmd == "list" => {
            let vault = open_vault(&home)?;
            cmd_list(&vault, &home)
        }
        [cmd, member] if cmd == "get" => {
            let vault = open_vault(&home)?;
            cmd_get(&vault, &home, member)
        }
        [cmd, member, source, flag] if cmd == "set" && flag == "--offline-confirmed" => {
            cmd_set(&home, member, source, true)
        }
        [cmd, member, source] if cmd == "set" => cmd_set(&home, member, source, false),
        _ => usage(),
    }
}
