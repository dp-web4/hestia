//! `hestia mesh` runs the mesh CLI compiled into this binary (#1503, Nova's #1504 HOLD).
//!
//! Hermetic: the real binary (`CARGO_BIN_EXE_hestia`), a stub daemon on an ephemeral port that
//! speaks just enough MCP-over-HTTP for `hestia_connect` + `hestia_member_inbox`, and a scrubbed
//! identity environment. Needs `python3` on PATH, as the subcommand does.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::process::Command;
use std::sync::{Arc, Mutex};

fn hestia() -> Command {
    let mut c = Command::new(env!("CARGO_BIN_EXE_hestia"));
    for k in ["HESTIA_MESH_PLUGIN", "HESTIA_MESH_HOST_AGENT", "HESTIA_ROLE", "HESTIA_ENDPOINT"] {
        c.env_remove(k);
    }
    c
}

/// A stub daemon: answers every POST, records each `hestia_connect`'s arguments.
fn stub_daemon() -> (String, Arc<Mutex<Vec<serde_json::Value>>>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let connects = Arc::new(Mutex::new(Vec::new()));
    let seen = connects.clone();
    std::thread::spawn(move || {
        for stream in listener.incoming() {
            let Ok(mut stream) = stream else { continue };
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            let mut len = 0usize;
            loop {
                let mut line = String::new();
                if reader.read_line(&mut line).unwrap_or(0) == 0 { break; }
                let l = line.trim_end();
                if l.is_empty() { break; }
                if let Some(v) = l.to_ascii_lowercase().strip_prefix("content-length:") {
                    len = v.trim().parse().unwrap_or(0);
                }
            }
            let mut body = vec![0u8; len];
            let _ = reader.read_exact(&mut body);
            let req: serde_json::Value = serde_json::from_slice(&body).unwrap_or_default();
            let id = req.get("id").cloned().unwrap_or(serde_json::json!(1));
            let reply = match req.get("method").and_then(|m| m.as_str()) {
                Some("tools/call") => {
                    let name = req["params"]["name"].as_str().unwrap_or("");
                    let payload = if name == "hestia_connect" {
                        seen.lock().unwrap().push(req["params"]["arguments"].clone());
                        serde_json::json!({"sessionId": "stub-session"})
                    } else if name == "hestia_member_inbox" {
                        serde_json::json!({"total": 0, "notices": []})
                    } else {
                        serde_json::json!({})
                    };
                    let rpc = serde_json::json!({"jsonrpc": "2.0", "id": id,
                        "result": {"content": [{"type": "text", "text": payload.to_string()}]}});
                    format!("data: {rpc}\n\n")
                }
                Some("initialize") => format!("data: {}\n\n",
                    serde_json::json!({"jsonrpc": "2.0", "id": id, "result": {}})),
                _ => String::new(),
            };
            let _ = write!(stream,
                "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nmcp-session-id: stub-session\r\n\
                 Content-Length: {}\r\nConnection: close\r\n\r\n{}", reply.len(), reply);
        }
    });
    (format!("http://127.0.0.1:{port}/mcp"), connects)
}

#[test]
fn kinds_prints_the_embedded_kinds_with_no_identity_and_no_daemon() {
    let out = hestia().args(["mesh", "kinds"]).env("HESTIA_ENDPOINT", "http://127.0.0.1:1/mcp").output().unwrap();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    assert_eq!(String::from_utf8(out.stdout).unwrap(), hestia::mesh_cli::EMBEDDED_KINDS);
}

#[test]
fn kinds_with_an_unmatched_term_says_so_and_exits_1() {
    let out = hestia().args(["mesh", "kinds", "zz-no-such-term-zz"]).output().unwrap();
    assert_eq!(out.status.code(), Some(1));
    assert!(out.stdout.is_empty());
    assert!(String::from_utf8_lossy(&out.stderr).contains("zz-no-such-term-zz"));
}

#[test]
fn without_an_identity_the_embedded_cli_refuses_with_rc2_and_names_hestia_mesh() {
    let (ep, connects) = stub_daemon();
    let out = hestia().args(["mesh", "peek"]).env("HESTIA_ENDPOINT", &ep).output().unwrap();
    assert_eq!(out.status.code(), Some(2), "{}", String::from_utf8_lossy(&out.stderr));
    let err = String::from_utf8_lossy(&out.stderr);
    assert!(err.contains("HESTIA_MESH_PLUGIN=claude-code hestia mesh peek"), "{err}");
    assert!(connects.lock().unwrap().is_empty(), "the guard refuses before it connects");
}

#[test]
fn a_stated_identity_is_the_one_on_the_wire_and_the_exit_code_passes_through() {
    let (ep, connects) = stub_daemon();
    let out = hestia().args(["mesh", "peek"]).env("HESTIA_ENDPOINT", &ep)
        .env("HESTIA_MESH_PLUGIN", "claude-code").output().unwrap();
    assert_eq!(out.status.code(), Some(0), "{}", String::from_utf8_lossy(&out.stderr));
    let c = connects.lock().unwrap();
    assert_eq!(c.len(), 1, "{c:?}");
    assert_eq!(c[0]["plugin_id"], "claude-code");
    assert_eq!(c[0]["host_agent"], "claude-code-cli");
}

#[test]
fn a_usage_error_keeps_the_embedded_clis_exit_code() {
    let out = hestia().args(["mesh", "no-such-verb"]).env("HESTIA_MESH_PLUGIN", "claude-code").output().unwrap();
    assert_eq!(out.status.code(), Some(2));
}

#[test]
fn a_missing_interpreter_is_never_got_there_rc1() {
    let out = hestia().args(["mesh", "peek"]).env("HESTIA_MESH_PLUGIN", "claude-code")
        .env("HESTIA_MESH_PYTHON", "/nonexistent/python3").output().unwrap();
    assert_eq!(out.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&out.stderr).contains("cannot run /nonexistent/python3"));
}
