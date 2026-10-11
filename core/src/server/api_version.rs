//! `GET /api/version` — the daemon half of the app/daemon handshake (web4#904 phase 1).
//!
//! The app reads this at connect and compares it with its own lockstep version and
//! [`hestia_wire::OPERATOR_API_COMPAT`]. Before this route, neither side read the other's
//! version: a mismatched pairing surfaced as generic route errors (a 404 on a renamed route,
//! a parse error on a reshaped body), indistinguishable from a broken daemon.
//!
//! UNAUTHENTICATED, like `/api/operator/challenge`: the app must be able to tell "this daemon
//! speaks a different API" before it can sign in, because the sign-in handshake itself is an
//! operator route whose shape can change. It reveals only what `hestia --version` prints on
//! the host (the release and its `git describe` build id) plus the compat integer, no state.
//! It takes no lock, so it answers even while the state lock is contended.

use axum::Json;
use serde::{Deserialize, Serialize};

/// The handshake body. Field names are the contract the app parses; adding a field is
/// additive, renaming or removing one is an `OPERATOR_API_COMPAT` bump.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VersionInfo {
    /// The lockstep release (root `VERSION`, mirrored into core/Cargo.toml).
    pub version: String,
    /// `git describe --tags --match 'v*'` of the build, as `hestia --version` reports it.
    pub build_id: String,
    /// See [`hestia_wire::OPERATOR_API_COMPAT`].
    pub api_compat: u32,
}

pub fn version_info() -> VersionInfo {
    VersionInfo {
        version: env!("CARGO_PKG_VERSION").to_string(),
        build_id: env!("HESTIA_GIT_VERSION").to_string(),
        api_compat: hestia_wire::OPERATOR_API_COMPAT,
    }
}

pub async fn api_version() -> Json<VersionInfo> {
    Json(version_info())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::routing::get;

    #[test]
    fn the_body_carries_the_lockstep_version_build_and_compat() {
        let v = version_info();
        assert_eq!(v.version, env!("CARGO_PKG_VERSION"));
        assert_eq!(v.build_id, env!("HESTIA_GIT_VERSION"));
        assert_eq!(v.api_compat, hestia_wire::OPERATOR_API_COMPAT);
        // The release in the binary is the release in VERSION: version_sync.py keeps
        // core/Cargo.toml equal to it, and this pins that the route reads the crate version.
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../VERSION");
        if let Ok(text) = std::fs::read_to_string(&root) {
            assert_eq!(v.version, text.trim(), "core/Cargo.toml drifted from VERSION");
        }
    }

    #[test]
    fn the_wire_shape_is_exactly_three_named_fields() {
        let json = serde_json::to_value(version_info()).unwrap();
        let mut keys: Vec<_> = json.as_object().unwrap().keys().cloned().collect();
        keys.sort();
        assert_eq!(keys, ["api_compat", "build_id", "version"]);
        assert!(json["api_compat"].is_u64());
    }

    #[tokio::test]
    async fn the_route_answers_without_a_session() {
        // Mounted the way http.rs mounts it: on the open router, outside operator_gate.
        let app = axum::Router::new().route("/api/version", get(api_version));
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        let resp = reqwest::get(format!("http://{addr}/api/version")).await.unwrap();
        assert_eq!(resp.status(), reqwest::StatusCode::OK);
        let v: VersionInfo = resp.json().await.unwrap();
        server.abort();
        assert_eq!(v, version_info());
    }
}
