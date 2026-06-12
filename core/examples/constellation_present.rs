//! End-to-end constellation attestation driver — the member side of the
//! flow defined in forum/legion-constellation-attestation-wire-shape-2026-06-11.md.
//!
//! The `hestia` CLI today covers constellation roster management
//! (`constellation add/list/remove/proof`) but (a) drops device private keys
//! on the floor (only the pubkey is stored, so devices can never co-sign) and
//! (b) exposes no command that drives `HubClient::present_constellation`.
//! This example fills both gaps without touching the CLI surface: device
//! secrets are persisted in the vault (`constellation_device_secret_<lct>`),
//! matching constellation.rs's "loaded from the vault" contract.
//!
//! Modes (vault passphrase via HESTIA_PASSPHRASE):
//!
//!   import-fleet <fleet-dir>     import a fleet-identity keypair + LCT
//!                                (~/.web4/<machine>) as the vault member
//!                                identity, so hub member LCT == fleet LCT
//!   ensure-device <name> <type>  add a co-signing device (keypair generated,
//!                                secret stored in the vault)
//!   join <hub-url> [name]        V2-12 self-add: hub pins our pubkey
//!   present <hub-url>            challenge → co-sign → present; prints the
//!                                hub-granted assurance tier
//!
//! Run with: cargo run --release --example constellation_present -- <mode> ...

use std::path::PathBuf;

use hestia::constellation::{ConstellationAttestation, DeviceType};
use hestia::vault::{default_hestia_home, vault_path};
use hestia::{ConstellationStore, HubClient, Vault, VaultEntry};
use uuid::Uuid;
use web4_core::crypto::KeyPair;

fn hex_to_32(s: &str) -> Option<[u8; 32]> {
    let bytes = hex::decode(s.trim()).ok()?;
    bytes.as_slice().try_into().ok()
}

fn open_vault(home: &std::path::Path) -> anyhow::Result<Vault> {
    let passphrase = std::env::var("HESTIA_PASSPHRASE")
        .map_err(|_| anyhow::anyhow!("set HESTIA_PASSPHRASE (no TTY prompting here)"))?;
    Ok(Vault::open(vault_path(home), passphrase)?)
}

fn member_identity(vault: &Vault) -> anyhow::Result<(Uuid, KeyPair)> {
    let lct = vault
        .get("ai_identity_lct_id")
        .ok_or_else(|| anyhow::anyhow!("no member identity in vault — run import-fleet or `hestia hub join`"))?;
    let sec = vault
        .get("ai_identity_secret")
        .ok_or_else(|| anyhow::anyhow!("vault has lct id but no ai_identity_secret"))?;
    let lct = Uuid::parse_str(&lct.secret)?;
    let bytes = hex_to_32(&sec.secret)
        .ok_or_else(|| anyhow::anyhow!("ai_identity_secret is not 32-byte hex"))?;
    Ok((lct, KeyPair::from_secret_bytes(&bytes)))
}

fn cmd_import_fleet(home: &std::path::Path, fleet_dir: &str) -> anyhow::Result<()> {
    let dir = PathBuf::from(shellexpand_tilde(fleet_dir));
    let lct_json: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(dir.join("lct.json"))?)?;
    let lct_id = lct_json["lct_id"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("lct.json missing lct_id"))?;
    let expected_pub = lct_json["public_key_hex"].as_str().unwrap_or_default();

    let secret = std::fs::read(dir.join("keypair.bin"))?;
    let secret: [u8; 32] = secret
        .as_slice()
        .try_into()
        .map_err(|_| anyhow::anyhow!("keypair.bin is not 32 bytes"))?;
    let kp = KeyPair::from_secret_bytes(&secret);
    let derived_pub = kp.verifying_key().to_hex();
    anyhow::ensure!(
        derived_pub == expected_pub,
        "keypair.bin does not derive lct.json's public_key_hex ({derived_pub} != {expected_pub})"
    );

    let mut vault = open_vault(home)?;
    let secret_hex: String = secret.iter().map(|b| format!("{b:02x}")).collect();
    vault.upsert(VaultEntry::new("ai_identity_lct_id", lct_id.to_string())
        .with_tags(vec!["identity".into()]))?;
    vault.upsert(VaultEntry::new("ai_identity_pubkey", derived_pub.clone())
        .with_tags(vec!["identity".into()]))?;
    vault.upsert(VaultEntry::new("ai_identity_secret", secret_hex)
        .with_tags(vec!["identity".into(), "secret".into()]))?;

    println!("Fleet identity imported as vault member identity:");
    println!("  lct:    {lct_id}");
    println!("  pubkey: {derived_pub}");
    Ok(())
}

fn cmd_ensure_device(home: &std::path::Path, name: &str, dtype: &str) -> anyhow::Result<()> {
    let dt = match dtype {
        "desktop" => DeviceType::Desktop,
        "mobile" => DeviceType::Mobile,
        "server" => DeviceType::Server,
        "agent" => DeviceType::Agent,
        "hardware" => DeviceType::Hardware,
        other => anyhow::bail!("unknown device type: {other}"),
    };

    let mut vault = open_vault(home)?;
    let (member_lct, _) = member_identity(&vault)?;

    let mut store = ConstellationStore::load(home)?;
    // The attestation owner MUST be the hub-pinned member identity (hub
    // verify rule 3 binds owner pubkey to the resolver's pinned key) — a
    // random owner UUID here would 403 at presentation time.
    store.owner_lct_id = Some(member_lct);

    if let Some(existing) = store.members.iter().find(|m| m.name == name) {
        println!("device '{name}' already in constellation ({})", existing.lct_id);
        store.save(home)?;
        return Ok(());
    }

    let kp = KeyPair::generate();
    let pubkey_hex = kp.verifying_key().to_hex();
    let lct_id = store.add_device(name, dt, &pubkey_hex, vec![]).lct_id;
    store.save(home)?;

    let secret_hex: String = kp.secret_key_bytes().iter().map(|b| format!("{b:02x}")).collect();
    vault.upsert(
        VaultEntry::new(format!("constellation_device_secret_{lct_id}"), secret_hex)
            .with_tags(vec!["constellation".into(), "secret".into()]),
    )?;

    println!("Device added with vault-held co-signing key:");
    println!("  name:   {name}");
    println!("  type:   {dtype}");
    println!("  lct:    {lct_id}");
    println!("  pubkey: {}…", &pubkey_hex[..16]);
    Ok(())
}

fn cmd_join(home: &std::path::Path, hub_url: &str, name: Option<String>) -> anyhow::Result<()> {
    let vault = open_vault(home)?;
    let (member_lct, kp) = member_identity(&vault)?;

    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
    let client = HubClient::new();
    let info = rt.block_on(client.discover(hub_url))?;
    let rest = abs_rest(hub_url, &info.endpoints.rest);

    println!("Joining {hub_url} as {member_lct} …");
    let outcome = rt.block_on(client.join(&rest, info.hub_lct_id, member_lct, &kp, name))?;
    println!("{outcome:#?}");
    Ok(())
}

fn cmd_present(home: &std::path::Path, hub_url: &str) -> anyhow::Result<()> {
    let vault = open_vault(home)?;
    let (member_lct, owner_kp) = member_identity(&vault)?;

    let store = ConstellationStore::load(home)?;
    anyhow::ensure!(
        store.owner_lct_id == Some(member_lct),
        "constellation owner ({:?}) != vault member identity ({member_lct}) — run ensure-device first",
        store.owner_lct_id
    );

    // Collect every device whose co-signing secret the vault holds.
    let mut device_keys: Vec<(Uuid, KeyPair)> = Vec::new();
    for m in &store.members {
        if let Some(e) = vault.get(&format!("constellation_device_secret_{}", m.lct_id)) {
            if let Some(bytes) = hex_to_32(&e.secret) {
                device_keys.push((m.lct_id, KeyPair::from_secret_bytes(&bytes)));
            }
        }
    }
    println!(
        "Constellation: {} device(s) on roster, {} able to co-sign",
        store.members.len(),
        device_keys.len()
    );

    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
    let client = HubClient::new();
    let info = rt.block_on(client.discover(hub_url))?;
    let rest = abs_rest(hub_url, &info.endpoints.rest);

    // v1 channel: pair_id is freshly minted client-side; the hub re-derives
    // the session key per request from our pinned pubkey + this pair_id.
    let pair_id = Uuid::new_v4();
    let channel = hestia::hub::HubChannel::from_hub_info(&info, pair_id)?;
    println!("Channel pair_id: {pair_id}");

    let response = rt.block_on(client.present_constellation(
        &rest,
        &channel,
        &owner_kp,
        member_lct,
        |nonce| ConstellationAttestation::create(&store, &owner_kp, nonce, &device_keys),
    ))?;

    println!("Hub response:");
    println!("{}", serde_json::to_string_pretty(&response)?);
    Ok(())
}

fn abs_rest(base_url: &str, rest: &str) -> String {
    if rest.starts_with("http://") || rest.starts_with("https://") {
        rest.to_string()
    } else if rest.is_empty() {
        format!("{}/v1", base_url.trim_end_matches('/'))
    } else {
        format!("{}{}", base_url.trim_end_matches('/'), rest)
    }
}

fn shellexpand_tilde(p: &str) -> String {
    if let Some(rest) = p.strip_prefix("~/") {
        if let Some(home) = std::env::var_os("HOME") {
            return format!("{}/{rest}", home.to_string_lossy());
        }
    }
    p.to_string()
}

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let home = match std::env::var("HESTIA_HOME") {
        Ok(p) => PathBuf::from(p),
        Err(_) => default_hestia_home()?,
    };

    match args.get(1).map(String::as_str) {
        Some("import-fleet") => {
            let dir = args.get(2).ok_or_else(|| anyhow::anyhow!("usage: import-fleet <fleet-dir>"))?;
            cmd_import_fleet(&home, dir)
        }
        Some("ensure-device") => {
            let name = args.get(2).ok_or_else(|| anyhow::anyhow!("usage: ensure-device <name> <type>"))?;
            let dtype = args.get(3).ok_or_else(|| anyhow::anyhow!("usage: ensure-device <name> <type>"))?;
            cmd_ensure_device(&home, name, dtype)
        }
        Some("join") => {
            let url = args.get(2).ok_or_else(|| anyhow::anyhow!("usage: join <hub-url> [name]"))?;
            cmd_join(&home, url, args.get(3).cloned())
        }
        Some("present") => {
            let url = args.get(2).ok_or_else(|| anyhow::anyhow!("usage: present <hub-url>"))?;
            cmd_present(&home, url)
        }
        _ => {
            eprintln!("usage: constellation_present <import-fleet|ensure-device|join|present> …");
            std::process::exit(2);
        }
    }
}
