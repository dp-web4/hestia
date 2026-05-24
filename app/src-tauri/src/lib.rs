mod commands;

use std::sync::Mutex;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RemoteEntry {
    pub name: String,
    pub url: String,
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(AppState::new())
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
            commands::remote::add_remote,
            commands::remote::remove_remote,
            commands::remote::list_remotes,
            commands::remote::get_remote_dashboard,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Hestia");
}
