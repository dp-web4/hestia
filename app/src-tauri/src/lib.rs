mod commands;

use std::path::PathBuf;
use std::sync::Mutex;

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

pub struct AppState {
    daemon_url: Mutex<String>,
    mode: Mutex<String>,
    remotes: Mutex<Vec<RemoteEntry>>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            daemon_url: Mutex::new("http://127.0.0.1:7711".to_string()),
            mode: Mutex::new("sovereign".to_string()),
            remotes: Mutex::new(Vec::new()),
        }
    }

    pub fn daemon_url(&self) -> String {
        self.daemon_url.lock().unwrap().clone()
    }

    pub fn set_daemon_url(&self, url: &str) {
        *self.daemon_url.lock().unwrap() = url.to_string();
    }

    pub fn mode(&self) -> String {
        self.mode.lock().unwrap().clone()
    }

    pub fn set_mode(&self, mode: &str) {
        *self.mode.lock().unwrap() = mode.to_string();
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
            commands::dashboard::get_dashboard,
            commands::dashboard::get_failures,
            commands::dashboard::get_daemon_status,
            commands::vault::vault_list,
            commands::vault::vault_set,
            commands::vault::vault_delete,
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
