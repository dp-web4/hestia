#![allow(dead_code, unused_imports)]
#[path = "../../../../app/src-tauri/src/daemon.rs"]
mod daemon;
#[path = "../../../../app/src-tauri/src/handshake.rs"]
mod handshake;
include!(concat!(env!("OUT_DIR"), "/state.rs"));

mod identity_vault {
    pub struct IdentityVault;
    impl IdentityVault {
        pub fn path(&self) -> &std::path::Path { std::path::Path::new("synthetic-vault") }
    }
}
mod operator {
    pub struct OperatorSession {
        pub token: String,
        pub lct_id: String,
        pub vault: std::sync::Arc<crate::identity_vault::IdentityVault>,
    }
    pub struct OperatorStatus {
        pub signed_in: bool,
        pub lct_id: Option<String>,
        pub vault_path: Option<String>,
        pub vault_exists: bool,
        pub migration_available: bool,
    }
    pub async fn authenticate(_: &str, _: std::sync::Arc<crate::identity_vault::IdentityVault>)
        -> Result<OperatorSession, String> {
        Err("test stub: authentication must not be needed in these probes".into())
    }
}

#[cfg(test)]
mod regression {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::{TcpListener, TcpStream};

    async fn read_request(s: &mut TcpStream) -> String {
        let mut b = vec![0; 8192];
        let n = s.read(&mut b).await.unwrap();
        String::from_utf8_lossy(&b[..n]).into_owned()
    }
    async fn answer(s: &mut TcpStream, body: &str) {
        s.write_all(format!("HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", body.len(), body).as_bytes()).await.unwrap();
    }
    fn version(compat: u32) -> String {
        serde_json::json!({"version":"0.3.0", "build_id":"v0.3.0", "api_compat":compat}).to_string()
    }
    fn signed_state(url: &str) -> Arc<AppState> {
        let state = Arc::new(AppState::new());
        state.set_daemon_url(url);
        state.set_operator(operator::OperatorSession {
            token: "synthetic-test-token".into(), lct_id: "synthetic".into(),
            vault: Arc::new(identity_vault::IdentityVault),
        });
        state
    }
    async fn endpoint() -> (TcpListener, String) {
        let s = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", s.local_addr().unwrap());
        (s, url)
    }

    // Desired invariant: compatibility evidence and dispatch refer to the same endpoint.
    #[tokio::test]
    async fn url_switch_must_not_dispatch_to_unprobed_daemon() {
        let (a, a_url) = endpoint().await;
        let (b, b_url) = endpoint().await;
        let state = signed_state(&a_url);
        let running = Arc::clone(&state);
        let call = tokio::spawn(async move {
            daemon::send(&running, reqwest::Method::POST, "/api/scope/grant", Some(serde_json::json!({}))).await
        });
        let (mut probe, _) = a.accept().await.unwrap();
        assert!(read_request(&mut probe).await.starts_with("GET /api/version "));
        state.set_daemon_url(&b_url);
        answer(&mut probe, &version(handshake::APP_API_COMPAT)).await;
        let (mut routed, _) = tokio::time::timeout(Duration::from_secs(2), b.accept()).await.unwrap().unwrap();
        let request = read_request(&mut routed).await;
        answer(&mut routed, "{}").await;
        let outcome = call.await.unwrap();
        eprintln!("B received: {}; outcome={outcome:?}", request.lines().next().unwrap());
        assert!(request.starts_with("GET /api/version "), "unprobed B received an operator mutation and synthetic bearer: {request}");
    }

    // Desired invariant: a replacement daemon is checked before a consequential operation.
    // The cached compatible response below stands for the daemon before replacement.
    #[tokio::test]
    async fn cached_compatibility_does_not_authorize_a_replacement() {
        let (b, url) = endpoint().await;
        let state = signed_state(&url);
        let h = handshake::classify(&handshake::Probe::Answered {
            status: 200, body: version(handshake::APP_API_COMPAT),
        }, handshake::APP_VERSION, handshake::APP_API_COMPAT);
        state.store_handshake(&url, &h);
        let running = Arc::clone(&state);
        let call = tokio::spawn(async move {
            daemon::send(&running, reqwest::Method::POST, "/api/scope/grant", Some(serde_json::json!({}))).await
        });
        let (mut routed, _) = b.accept().await.unwrap();
        let request = read_request(&mut routed).await;
        let body = if request.starts_with("GET /api/version ") { version(handshake::APP_API_COMPAT + 1) } else { "{}".into() };
        answer(&mut routed, &body).await;
        let outcome = call.await.unwrap();
        eprintln!("replacement received: {}; outcome={outcome:?}", request.lines().next().unwrap());
        assert!(request.starts_with("GET /api/version "), "cached compatibility allowed a mutation without querying the replacement");
    }

    #[tokio::test]
    async fn initially_incompatible_daemon_refuses_operator_route() {
        let (b, url) = endpoint().await;
        let state = signed_state(&url);
        let running = Arc::clone(&state);
        let call = tokio::spawn(async move {
            daemon::send(&running, reqwest::Method::POST, "/api/scope/grant", None).await
        });
        let (mut probe, _) = b.accept().await.unwrap();
        assert!(read_request(&mut probe).await.starts_with("GET /api/version "));
        answer(&mut probe, &version(handshake::APP_API_COMPAT + 1)).await;
        assert!(call.await.unwrap().unwrap_err().contains("incompatible daemon"));
        assert!(tokio::time::timeout(Duration::from_millis(50), b.accept()).await.is_err());
    }
}
