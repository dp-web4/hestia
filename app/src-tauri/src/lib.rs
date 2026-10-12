mod commands;
mod daemon;
pub mod handshake;
pub mod identity;
pub mod identity_vault;
pub mod operator;

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::Manager;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RemoteEntry {
    pub name: String,
    pub url: String,
}

/// Subset of AppState that survives restarts. Written to
/// `<app-config-dir>/config.json` on every settings mutation; loaded in
/// `run()`'s setup hook. Mobile builds have no sidecar daemon, so a
/// persisted remote daemon URL is what makes the app usable there at all.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PersistedConfig {
    pub daemon_url: Option<String>,
    pub mode: Option<String>,
}

/// The daemon the app is pointed at, and which selection that is. `generation` moves every
/// time Settings points the app at a different URL, so an operation can capture the endpoint
/// once and prove, after any await, that it is still the one selected. Without it, a version
/// probe answered by daemon A could authorize a request to daemon B (Codex, hestia#1280).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Endpoint {
    pub url: String,
    pub generation: u64,
}

pub struct AppState {
    endpoint: Mutex<Endpoint>,
    mode: Mutex<String>,
    remotes: Mutex<Vec<RemoteEntry>>,
    /// The live operator session, and the endpoint generation its token was minted by.
    /// Deliberately shell-side: neither the token nor the signing key ever crosses the IPC
    /// boundary into the webview. The token is only ever sent to that generation's daemon;
    /// the unlocked vault outlives a URL change and re-authenticates against the new one.
    operator: Mutex<Option<(u64, operator::OperatorSession)>>,
    /// The last `/api/version` handshake: (daemon url, when, result). Keyed by URL, so
    /// pointing the app at another daemon re-probes; see `daemon::ensure_compatible`.
    handshake: Mutex<Option<(String, Instant, handshake::Handshake)>>,
}

/// How long a handshake result stands before the next route re-probes. Short, because the
/// daemon on the other end can be swapped by a deploy while the app stays open.
pub const HANDSHAKE_TTL: Duration = Duration::from_secs(15);

impl AppState {
    pub fn new() -> Self {
        Self {
            endpoint: Mutex::new(Endpoint {
                url: "http://127.0.0.1:7711".to_string(),
                generation: 0,
            }),
            mode: Mutex::new("sovereign".to_string()),
            remotes: Mutex::new(Vec::new()),
            operator: Mutex::new(None),
            handshake: Mutex::new(None),
        }
    }

    pub fn daemon_url(&self) -> String {
        self.endpoint.lock().unwrap().url.clone()
    }

    /// The selected endpoint, captured. Bind every step of one operation to this value.
    pub fn endpoint(&self) -> Endpoint {
        self.endpoint.lock().unwrap().clone()
    }

    /// Is `ep` still the selected endpoint?
    pub fn is_current(&self, ep: &Endpoint) -> bool {
        *self.endpoint.lock().unwrap() == *ep
    }

    /// Point the app at `url`. A different URL is a new generation; re-saving the same URL is not.
    pub fn set_daemon_url(&self, url: &str) {
        let mut ep = self.endpoint.lock().unwrap();
        if ep.url != url {
            ep.url = url.to_string();
            ep.generation += 1;
        }
    }

    pub fn mode(&self) -> String {
        self.mode.lock().unwrap().clone()
    }

    pub fn set_mode(&self, mode: &str) {
        *self.mode.lock().unwrap() = mode.to_string();
    }

    // ---- operator session (shell-side only) ----

    /// The bearer for `ep`, only if the session was minted by that same selection.
    pub fn operator_token_for(&self, ep: &Endpoint) -> Option<String> {
        self.operator
            .lock()
            .unwrap()
            .as_ref()
            .filter(|(generation, _)| *generation == ep.generation)
            .map(|(_, o)| o.token.clone())
    }

    pub fn operator_vault(&self) -> Option<Arc<identity_vault::IdentityVault>> {
        self.operator
            .lock()
            .unwrap()
            .as_ref()
            .map(|(_, o)| Arc::clone(&o.vault))
    }

    /// Publish a session minted against `ep` — unless the selection moved while it was being
    /// minted, in which case it is dropped and `false` comes back. Checked under the endpoint
    /// lock, so a concurrent `set_daemon_url` cannot slip between the check and the write.
    pub fn set_operator_for(&self, ep: &Endpoint, session: operator::OperatorSession) -> bool {
        let selected = self.endpoint.lock().unwrap();
        if *selected != *ep {
            return false;
        }
        *self.operator.lock().unwrap() = Some((ep.generation, session));
        true
    }

    pub fn clear_operator(&self) {
        *self.operator.lock().unwrap() = None;
    }

    /// What the UI may know: signed-in-ness and the LCT. Never the token.
    pub fn operator_status(&self) -> operator::OperatorStatus {
        let guard = self.operator.lock().unwrap();
        match guard.as_ref() {
            Some((_, o)) => operator::OperatorStatus {
                signed_in: true,
                lct_id: Some(o.lct_id.clone()),
                vault_path: Some(o.vault.path().to_string_lossy().to_string()),
                vault_exists: true,
                migration_available: false,
            },
            None => operator::OperatorStatus {
                signed_in: false,
                lct_id: None,
                vault_path: None,
                vault_exists: false,
                migration_available: false,
            },
        }
    }

    // ---- daemon handshake (web4#904) ----

    /// The cached handshake for `url`, if it is younger than [`HANDSHAKE_TTL`].
    pub fn cached_handshake(&self, url: &str) -> Option<handshake::Handshake> {
        let guard = self.handshake.lock().unwrap();
        guard
            .as_ref()
            .filter(|(u, at, _)| u == url && at.elapsed() < HANDSHAKE_TTL)
            .map(|(_, _, h)| h.clone())
    }

    /// Drop the cached handshake, so the next route re-probes. A 401 is the cue: sessions live in
    /// daemon memory, so a session that stopped working is often a daemon that was replaced.
    pub fn forget_handshake(&self) {
        *self.handshake.lock().unwrap() = None;
    }

    /// Remember a handshake. An unreachable result is not cached: the next call re-probes.
    pub fn store_handshake(&self, url: &str, h: &handshake::Handshake) {
        let mut guard = self.handshake.lock().unwrap();
        *guard = if h.state.answered() {
            Some((url.to_string(), Instant::now(), h.clone()))
        } else {
            None
        };
    }

    pub fn remotes(&self) -> Vec<RemoteEntry> {
        self.remotes.lock().unwrap().clone()
    }

    pub fn add_remote(&self, name: &str, url: &str) {
        let mut remotes = self.remotes.lock().unwrap();
        remotes.retain(|r| r.name != name);
        remotes.push(RemoteEntry {
            name: name.to_string(),
            url: url.to_string(),
        });
    }

    pub fn remove_remote(&self, name: &str) {
        self.remotes.lock().unwrap().retain(|r| r.name != name);
    }
}

fn config_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    app.path().app_config_dir().ok().map(|d| d.join("config.json"))
}

pub fn persist_config(app: &tauri::AppHandle, state: &AppState) {
    let Some(path) = config_path(app) else { return };
    let cfg = PersistedConfig {
        daemon_url: Some(state.daemon_url()),
        mode: Some(state.mode()),
    };
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    if let Ok(json) = serde_json::to_string_pretty(&cfg) {
        let _ = std::fs::write(&path, json);
    }
}

fn load_config(app: &tauri::AppHandle, state: &AppState) {
    let Some(path) = config_path(app) else { return };
    let Ok(raw) = std::fs::read_to_string(&path) else { return };
    let Ok(cfg) = serde_json::from_str::<PersistedConfig>(&raw) else { return };
    if let Some(url) = cfg.daemon_url {
        state.set_daemon_url(&url);
    }
    if let Some(mode) = cfg.mode {
        state.set_mode(&mode);
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(AppState::new())
        .setup(|app| {
            let state = app.state::<AppState>();
            load_config(app.handle(), &state);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::operator::operator_status,
            commands::operator::operator_sign_in,
            commands::operator::operator_sign_out,
            commands::trust::get_derivation,
            commands::dashboard::get_dashboard,
            commands::decide::decide_gate_escalation,
            commands::gates::gates_verify,
            commands::gates::gates_ratify,
            commands::gates::gates_forget,
            commands::agents::agents_inventory,
            commands::agents::agent_gate_bypass,
            commands::agents::agent_gate_restore,
            commands::scope::rule_scope_request,
            commands::grants::grant_reach,
            commands::grants::revoke_reach,
            commands::dashboard::get_failures,
            commands::dashboard::get_daemon_status,
            commands::vault::vault_list,
            commands::vault::vault_set,
            commands::vault::vault_delete,
            commands::config::config_seat_list,
            commands::config::config_seat_get,
            commands::config::config_seat_put,
            commands::policy::get_policy,
            commands::policy::set_preset,
            commands::chain::query_chain,
            commands::chain::chain_stats,
            commands::settings::get_config,
            commands::settings::set_mode,
            commands::settings::set_daemon_url,
            commands::remote::add_remote,
            commands::remote::remove_remote,
            commands::remote::list_remotes,
            commands::remote::get_remote_dashboard,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Hestia");
}
