//! The app half of the app/daemon handshake (web4#904 phase 1).
//!
//! The daemon serves `GET /api/version` -> `{version, build_id, api_compat}`, unauthenticated.
//! The app reads it before any other route and classifies the pairing:
//!
//! | daemon answer                         | state                  | routes attempted? |
//! |---------------------------------------|------------------------|-------------------|
//! | same `api_compat`, same version       | `compatible`           | yes               |
//! | same `api_compat`, different version  | `skew`                 | yes (shown)       |
//! | different `api_compat`                | `incompatible`         | no                |
//! | 404 / 405 on `/api/version`           | `no_version_endpoint`  | no                |
//! | 2xx with an unparseable body, or 5xx  | `malformed`            | no                |
//! | no HTTP answer at all                 | `unreachable`          | no (offline)      |
//!
//! Before this, a mismatched pairing surfaced as whatever the first route happened to return
//! (a 404 on a renamed route, "bad response" on a reshaped body), which reads as a broken
//! daemon. A daemon that predates 0.3.0 has no `/api/version`, and it must read as an
//! incompatible daemon, never as "offline" and never as compatible by default.

use std::time::Duration;

use serde::{Deserialize, Serialize};

/// The lockstep release this app was built as (root `VERSION`, mirrored into Cargo.toml).
pub const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
/// The operator-API generation this app speaks. One constant, compiled by both sides.
pub const APP_API_COMPAT: u32 = hestia_wire::OPERATOR_API_COMPAT;

/// The daemon's body, as the daemon's `server::api_version::VersionInfo` serializes it.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct DaemonVersion {
    pub version: String,
    pub build_id: String,
    pub api_compat: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CompatState {
    Compatible,
    Skew,
    Incompatible,
    NoVersionEndpoint,
    Malformed,
    Unreachable,
}

impl CompatState {
    /// May the app send operator routes to this daemon?
    pub fn usable(self) -> bool {
        matches!(self, CompatState::Compatible | CompatState::Skew)
    }
    /// Did the daemon answer HTTP at all? (`online` in the status the UI reads.)
    pub fn answered(self) -> bool {
        !matches!(self, CompatState::Unreachable)
    }
}

/// What the UI may know about the pairing. Serialized as `handshake` in `get_daemon_status`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Handshake {
    pub state: CompatState,
    pub app_version: String,
    pub app_api_compat: u32,
    pub daemon_version: Option<String>,
    pub daemon_build_id: Option<String>,
    pub daemon_api_compat: Option<u32>,
    /// One sentence for the operator: what is wrong and what fixes it.
    pub message: String,
}

/// What the probe saw, before interpretation. Separate so the classification is testable
/// without a socket.
#[derive(Debug, Clone)]
pub enum Probe {
    Unreachable(String),
    Answered { status: u16, body: String },
}

/// Classify a probe against this app's own version and compat generation. Pure.
pub fn classify(probe: &Probe, app_version: &str, app_compat: u32) -> Handshake {
    let mut h = Handshake {
        state: CompatState::Unreachable,
        app_version: app_version.to_string(),
        app_api_compat: app_compat,
        daemon_version: None,
        daemon_build_id: None,
        daemon_api_compat: None,
        message: String::new(),
    };
    match probe {
        Probe::Unreachable(why) => {
            h.message = format!("daemon unreachable: {why}");
        }
        Probe::Answered { status, .. } if *status == 404 || *status == 405 => {
            h.state = CompatState::NoVersionEndpoint;
            h.message = format!(
                "incompatible daemon (no version endpoint): GET /api/version answered {status}, so \
                 the daemon predates hestia 0.3.0. This app is hestia {app_version}; upgrade the \
                 daemon to the same release."
            );
        }
        Probe::Answered { status, body } if (200..300).contains(status) => {
            match serde_json::from_str::<DaemonVersion>(body) {
                Ok(d) => {
                    h.daemon_version = Some(d.version.clone());
                    h.daemon_build_id = Some(d.build_id.clone());
                    h.daemon_api_compat = Some(d.api_compat);
                    if d.api_compat != app_compat {
                        let newer = if d.api_compat > app_compat { "app" } else { "daemon" };
                        h.state = CompatState::Incompatible;
                        h.message = format!(
                            "incompatible daemon: it serves operator API v{} (hestia {}, build {}); \
                             this app speaks v{app_compat} (hestia {app_version}). Upgrade the {newer} \
                             so both are the same release.",
                            d.api_compat, d.version, d.build_id
                        );
                    } else if d.version != app_version {
                        h.state = CompatState::Skew;
                        h.message = format!(
                            "version skew: daemon is hestia {} (build {}), app is hestia {app_version}; \
                             both speak operator API v{app_compat}, so they work together.",
                            d.version, d.build_id
                        );
                    } else {
                        h.state = CompatState::Compatible;
                        h.message = format!("hestia {} (build {})", d.version, d.build_id);
                    }
                }
                Err(e) => {
                    h.state = CompatState::Malformed;
                    h.message = format!(
                        "incompatible daemon: GET /api/version answered {status} but not with \
                         {{version, build_id, api_compat}} ({e})"
                    );
                }
            }
        }
        Probe::Answered { status, .. } => {
            h.state = CompatState::Malformed;
            h.message = format!(
                "daemon error: GET /api/version answered {status}; compatibility unknown, so no \
                 operator route is attempted"
            );
        }
    }
    h
}

/// Probe `daemon_url` once. Bounded: a daemon that accepts the connection and never answers
/// must not hang the UI.
pub async fn probe(daemon_url: &str) -> Probe {
    let client = match reqwest::Client::builder().timeout(Duration::from_secs(5)).build() {
        Ok(c) => c,
        Err(e) => return Probe::Unreachable(format!("http client: {e}")),
    };
    match client.get(format!("{daemon_url}/api/version")).send().await {
        Err(e) => Probe::Unreachable(e.to_string()),
        Ok(resp) => {
            let status = resp.status().as_u16();
            let body = resp.text().await.unwrap_or_default();
            Probe::Answered { status, body }
        }
    }
}

/// Probe and classify against this build.
pub async fn handshake(daemon_url: &str) -> Handshake {
    classify(&probe(daemon_url).await, APP_VERSION, APP_API_COMPAT)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ok(body: serde_json::Value) -> Probe {
        Probe::Answered { status: 200, body: body.to_string() }
    }

    #[test]
    fn same_release_is_compatible() {
        let h = classify(
            &ok(serde_json::json!({"version": "0.3.0", "build_id": "v0.3.0", "api_compat": 1})),
            "0.3.0",
            1,
        );
        assert_eq!(h.state, CompatState::Compatible);
        assert!(h.state.usable());
        assert_eq!(h.daemon_build_id.as_deref(), Some("v0.3.0"));
    }

    #[test]
    fn same_compat_different_version_is_skew_and_still_usable() {
        let h = classify(
            &ok(serde_json::json!({"version": "0.3.1", "build_id": "v0.3.1-4-gabc", "api_compat": 1})),
            "0.3.0",
            1,
        );
        assert_eq!(h.state, CompatState::Skew);
        assert!(h.state.usable());
        assert!(h.message.contains("0.3.1") && h.message.contains("0.3.0"), "{}", h.message);
    }

    #[test]
    fn different_compat_is_incompatible_and_names_who_to_upgrade() {
        let newer_daemon = classify(
            &ok(serde_json::json!({"version": "0.4.0", "build_id": "v0.4.0", "api_compat": 2})),
            "0.3.0",
            1,
        );
        assert_eq!(newer_daemon.state, CompatState::Incompatible);
        assert!(!newer_daemon.state.usable());
        assert!(newer_daemon.message.contains("Upgrade the app"), "{}", newer_daemon.message);

        let older_daemon = classify(
            &ok(serde_json::json!({"version": "0.3.0", "build_id": "v0.3.0", "api_compat": 1})),
            "0.4.0",
            2,
        );
        assert_eq!(older_daemon.state, CompatState::Incompatible);
        assert!(older_daemon.message.contains("Upgrade the daemon"), "{}", older_daemon.message);
    }

    #[test]
    fn a_daemon_without_the_endpoint_is_incompatible_not_offline() {
        for status in [404u16, 405] {
            let h = classify(&Probe::Answered { status, body: String::new() }, "0.3.0", 1);
            assert_eq!(h.state, CompatState::NoVersionEndpoint);
            assert!(!h.state.usable());
            assert!(h.state.answered(), "the daemon answered; it is online");
            assert!(h.message.starts_with("incompatible daemon (no version endpoint)"), "{}", h.message);
        }
    }

    #[test]
    fn an_unparseable_or_failing_answer_is_never_compatible() {
        for probe in [
            ok(serde_json::json!({"version": "0.3.0"})),
            Probe::Answered { status: 200, body: "<html>".into() },
            Probe::Answered { status: 500, body: String::new() },
            Probe::Answered { status: 401, body: String::new() },
        ] {
            let h = classify(&probe, "0.3.0", 1);
            assert_eq!(h.state, CompatState::Malformed, "{probe:?}");
            assert!(!h.state.usable());
        }
    }

    #[test]
    fn no_answer_is_unreachable() {
        let h = classify(&Probe::Unreachable("connection refused".into()), "0.3.0", 1);
        assert_eq!(h.state, CompatState::Unreachable);
        assert!(!h.state.answered());
        assert!(h.message.starts_with("daemon unreachable"), "{}", h.message);
    }

    #[test]
    fn the_state_serializes_as_the_names_the_frontend_matches() {
        let names: Vec<String> = [
            CompatState::Compatible,
            CompatState::Skew,
            CompatState::Incompatible,
            CompatState::NoVersionEndpoint,
            CompatState::Malformed,
            CompatState::Unreachable,
        ]
        .iter()
        .map(|s| serde_json::to_value(s).unwrap().as_str().unwrap().to_string())
        .collect();
        assert_eq!(
            names,
            ["compatible", "skew", "incompatible", "no_version_endpoint", "malformed", "unreachable"]
        );
    }

    #[test]
    fn this_build_speaks_the_shared_compat_generation() {
        assert_eq!(APP_API_COMPAT, hestia_wire::OPERATOR_API_COMPAT);
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../VERSION");
        if let Ok(text) = std::fs::read_to_string(root) {
            assert_eq!(APP_VERSION, text.trim(), "app/src-tauri/Cargo.toml drifted from VERSION");
        }
    }

    /// The probe against a real socket: an old daemon's router has no /api/version and
    /// answers 404 — exercised with a one-shot HTTP responder, not a mock of `classify`.
    #[tokio::test]
    async fn the_probe_reads_a_404_from_a_real_socket_as_no_endpoint() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let mut buf = [0u8; 2048];
            let _ = sock.read(&mut buf).await;
            let _ = sock
                .write_all(b"HTTP/1.1 404 Not Found\r\ncontent-length: 0\r\nconnection: close\r\n\r\n")
                .await;
        });
        let h = handshake(&format!("http://{addr}")).await;
        server.await.unwrap();
        assert_eq!(h.state, CompatState::NoVersionEndpoint, "{}", h.message);
    }

    #[tokio::test]
    async fn the_probe_reads_a_closed_port_as_unreachable() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        drop(listener);
        let h = handshake(&format!("http://{addr}")).await;
        assert_eq!(h.state, CompatState::Unreachable, "{}", h.message);
    }
}
