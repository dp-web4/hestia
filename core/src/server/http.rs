//! HTTP transport for the Hestia MCP server.
//!
//! Mounts two surfaces on the same listener:
//!   /mcp/*           — the MCP StreamableHttp surface (plugin path)
//!   /                — embedded HTML dashboard (operator path)
//!   /api/dashboard   — JSON snapshot consumed by the dashboard + TUI

use anyhow::{Context, Result};
use axum::{
    extract::State,
    http::header,
    response::{Html, IntoResponse, Json},
    routing::get,
};
use rmcp::transport::streamable_http_server::{
    session::local::LocalSessionManager, StreamableHttpServerConfig, StreamableHttpService,
};
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;

use super::handler::HestiaServer;
use super::state::SharedState;

pub const DEFAULT_BIND: &str = "127.0.0.1:7711";

const DASHBOARD_HTML: &str = include_str!("dashboard/index.html");

pub async fn serve(state: SharedState, bind: &str) -> Result<()> {
    let addr: SocketAddr = bind
        .parse()
        .with_context(|| format!("parsing bind address '{}'", bind))?;

    let server_clone = HestiaServer::new(state.clone());

    let mut config = StreamableHttpServerConfig::default();
    config.sse_keep_alive = Some(Duration::from_secs(15));
    config.stateful_mode = true;
    config.json_response = true;

    let service = StreamableHttpService::new(
        move || Ok(server_clone.clone()),
        Arc::new(LocalSessionManager::default()),
        config,
    );

    let app = axum::Router::new()
        .route("/", get(dashboard_html))
        .route("/api/dashboard", get(dashboard_json))
        .with_state(state)
        .nest_service("/mcp", service);

    let listener = TcpListener::bind(&addr)
        .await
        .with_context(|| format!("binding {}", addr))?;

    tracing::info!("Hestia MCP server listening on http://{}", addr);
    tracing::info!("Dashboard at http://{}/", addr);

    // Run until ctrl-c
    let shutdown_token = CancellationToken::new();
    let shutdown_clone = shutdown_token.clone();
    tokio::spawn(async move {
        let _ = tokio::signal::ctrl_c().await;
        tracing::info!("shutdown signal received");
        shutdown_clone.cancel();
    });

    axum::serve(listener, app)
        .with_graceful_shutdown(async move { shutdown_token.cancelled().await })
        .await
        .context("axum::serve failed")?;

    Ok(())
}

async fn dashboard_html() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        Html(DASHBOARD_HTML),
    )
}

async fn dashboard_json(State(state): State<SharedState>) -> impl IntoResponse {
    let s = state.lock().await;
    let snapshot = s.dashboard_snapshot(50);
    drop(s);
    Json(snapshot)
}
