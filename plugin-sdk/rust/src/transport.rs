//! Hestia endpoint discovery.
//!
//! Auto-discovers the Hestia daemon endpoint:
//! 1. Explicit `hestia_endpoint` in config
//! 2. `HESTIA_ENDPOINT` env var
//! 3. `~/.hestia/endpoint` file
//! 4. `http://127.0.0.1:7711` default

use std::env;
use std::fs;
use std::path::PathBuf;

pub const DEFAULT_HESTIA_ENDPOINT: &str = "http://127.0.0.1:7711";

pub fn discover_hestia_endpoint(override_url: Option<&str>) -> String {
    if let Some(url) = override_url {
        if !url.is_empty() {
            return url.to_string();
        }
    }

    if let Ok(env) = env::var("HESTIA_ENDPOINT") {
        if !env.is_empty() {
            return env;
        }
    }

    if let Some(home) = dirs() {
        let p: PathBuf = home.join(".hestia").join("endpoint");
        if let Ok(text) = fs::read_to_string(&p) {
            let trimmed = text.trim();
            if !trimmed.is_empty() {
                return trimmed.to_string();
            }
        }
    }

    DEFAULT_HESTIA_ENDPOINT.to_string()
}

fn dirs() -> Option<PathBuf> {
    // Avoid a dependency on `dirs` for a single home-dir lookup.
    env::var_os("HOME")
        .map(PathBuf::from)
        .or_else(|| env::var_os("USERPROFILE").map(PathBuf::from))
}
