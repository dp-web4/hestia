//! S2a.0 — hestia knows its caller (entity-accounts PRD r6, SAGE #834; hestia #954).
//!
//! Over TCP loopback hestia cannot tell one local uid from another: a member proves itself only
//! by the `plugin_id` it asserts, so any local process can connect as any member. A unix-socket
//! listener closes that at the kernel. On accept, the peer's uid is read with `SO_PEERCRED`
//! (tokio's `UnixStream::peer_cred`, `getpeereid` on macOS), carried on every request of that
//! connection as a [`CallerCred`] extension, and `hestia_connect` checks the claimed member
//! against the operator's uid map ([`CALLER_UID_MAP_FILE`]).
//!
//! HONEST SCOPE of this first slice:
//! - The check binds the CLAIM AT CONNECT. A `session_id` minted over the socket is still a
//!   bearer token afterwards; binding later calls to the minting uid is the next slice.
//! - The TCP listener is unchanged and stays open. Callers move to the socket member by member;
//!   closing TCP to members is a deploy decision once they have.
//! - The uid that runs hestia is the operator's. On Legion today every seat shares that uid
//!   (PRD F3), so a caller at the daemon's uid is reported `peercred:daemon-uid` and NOT narrowed:
//!   the kernel proves the uid, and the uid proves nothing finer. That stays true until seats
//!   have their own uids (S8).

use std::collections::BTreeMap;
use std::path::Path;

use anyhow::{Context, Result};
use serde::Deserialize;
use serde_json::{json, Value};

/// The kernel's account of who is on the other end of a unix-socket connection.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CallerCred {
    pub uid: u32,
    pub gid: u32,
    /// Linux reports it; macOS's `getpeereid` does not.
    pub pid: Option<i32>,
}

/// Operator-written map, `<home>/caller-uids.json`: `{"uids": {"1001": "legion-being"}}`.
/// Each value is the member id (`plugin_id`) that uid may connect as. A uid maps to ONE member.
pub const CALLER_UID_MAP_FILE: &str = "caller-uids.json";

#[derive(Debug, Default, Deserialize)]
struct UidMapFile {
    #[serde(default)]
    uids: BTreeMap<String, String>,
}

/// Read fresh on every connect, so an operator edit takes effect without a restart. A map that
/// is present but unreadable or malformed fails CLOSED: every socket caller other than the
/// daemon's own uid is refused, with the parse error named.
pub fn load_uid_map(home: &Path) -> Result<BTreeMap<u32, String>> {
    let path = home.join(CALLER_UID_MAP_FILE);
    if !path.exists() {
        return Ok(BTreeMap::new());
    }
    let raw = std::fs::read_to_string(&path).with_context(|| format!("reading {}", path.display()))?;
    let file: UidMapFile =
        serde_json::from_str(&raw).with_context(|| format!("parsing {}", path.display()))?;
    let mut out = BTreeMap::new();
    for (k, v) in file.uids {
        let uid: u32 = k
            .parse()
            .with_context(|| format!("{}: uid key {k:?} is not a number", path.display()))?;
        if v.is_empty() {
            anyhow::bail!("{}: uid {uid} maps to an empty member id", path.display());
        }
        out.insert(uid, v);
    }
    Ok(out)
}

#[cfg(unix)]
pub fn daemon_uid() -> u32 {
    // SAFETY: getuid(2) cannot fail and touches no memory.
    unsafe { libc::getuid() }
}

/// No unix listener exists off unix, so no `CallerCred` is ever present and this is never compared.
#[cfg(not(unix))]
pub fn daemon_uid() -> u32 {
    u32::MAX
}

/// The outcome of checking a connect claim against the caller's kernel uid.
#[derive(Debug, PartialEq, Eq)]
pub enum ClaimCheck {
    /// No `CallerCred`: the call came over TCP. Nothing is proven beyond the assertion.
    Asserted,
    /// The uid is mapped to exactly this member.
    PeercredMapped { uid: u32 },
    /// The caller runs as the daemon's own uid and that uid is not mapped: proven uid, unnarrowed.
    PeercredDaemonUid { uid: u32 },
    Refused { code: &'static str, message: String, detail: Value },
}

impl ClaimCheck {
    pub fn caller_json(&self) -> Option<Value> {
        match self {
            ClaimCheck::Asserted => Some(json!({ "basis": "asserted" })),
            ClaimCheck::PeercredMapped { uid } => Some(json!({ "basis": "peercred", "uid": uid })),
            ClaimCheck::PeercredDaemonUid { uid } => {
                Some(json!({ "basis": "peercred:daemon-uid", "uid": uid }))
            }
            ClaimCheck::Refused { .. } => None,
        }
    }
}

/// Decide whether `cred` may connect as `plugin_id`, given the operator's map and the daemon uid.
pub fn check_claim(
    cred: Option<CallerCred>,
    plugin_id: &str,
    map: &Result<BTreeMap<u32, String>>,
    daemon_uid: u32,
) -> ClaimCheck {
    let Some(cred) = cred else { return ClaimCheck::Asserted };
    let map = match map {
        Ok(m) => m,
        Err(e) if cred.uid == daemon_uid => {
            // The operator's own uid is never locked out by its own broken map file; it is the
            // uid that has to fix it. Still unnarrowed, still reported.
            tracing::warn!("caller uid map unreadable, daemon-uid caller admitted: {e:#}");
            return ClaimCheck::PeercredDaemonUid { uid: cred.uid };
        }
        Err(e) => {
            return ClaimCheck::Refused {
                code: "hestia.caller.uid_map_unreadable",
                message: format!(
                    "the caller uid map ({CALLER_UID_MAP_FILE}) cannot be read, so no socket \
                     caller other than the daemon's own uid can be identified: {e:#}"
                ),
                detail: json!({ "uid": cred.uid, "plugin_id": plugin_id }),
            }
        }
    };
    match map.get(&cred.uid) {
        Some(member) if member == plugin_id => ClaimCheck::PeercredMapped { uid: cred.uid },
        Some(member) => ClaimCheck::Refused {
            code: "hestia.caller.mismatch",
            message: format!(
                "uid {} may connect only as {member:?}, not {plugin_id:?} (kernel peer \
                 credential checked against {CALLER_UID_MAP_FILE})",
                cred.uid
            ),
            detail: json!({ "uid": cred.uid, "plugin_id": plugin_id, "mapped_member": member }),
        },
        None if cred.uid == daemon_uid => ClaimCheck::PeercredDaemonUid { uid: cred.uid },
        None => ClaimCheck::Refused {
            code: "hestia.caller.unmapped",
            message: format!(
                "uid {} is not in {CALLER_UID_MAP_FILE}; a socket caller at a uid other than the \
                 daemon's must be mapped to the one member it may connect as",
                cred.uid
            ),
            detail: json!({ "uid": cred.uid, "plugin_id": plugin_id }),
        },
    }
}

/// Serve `app` on a unix socket at `path`, stamping each connection's peer credential onto every
/// request it carries. A stale socket file is removed first; the socket is created `0666` because
/// the kernel, not the file mode, is what identifies the caller (restrict the parent directory to
/// restrict who may dial at all).
#[cfg(unix)]
pub async fn serve_unix(
    app: axum::Router,
    path: std::path::PathBuf,
    shutdown: tokio_util::sync::CancellationToken,
) -> Result<()> {
    use hyper::server::conn::http1::Builder;
    use hyper_util::rt::TokioIo;
    use std::os::unix::fs::{FileTypeExt, PermissionsExt};
    use tower::ServiceExt;

    if let Ok(meta) = std::fs::symlink_metadata(&path) {
        if meta.file_type().is_socket() {
            std::fs::remove_file(&path)
                .with_context(|| format!("removing stale socket {}", path.display()))?;
        } else {
            anyhow::bail!("{} exists and is not a socket; refusing to replace it", path.display());
        }
    }
    let listener = tokio::net::UnixListener::bind(&path)
        .with_context(|| format!("binding unix socket {}", path.display()))?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o666))
        .with_context(|| format!("chmod {}", path.display()))?;
    tracing::info!("Hestia MCP server listening on unix:{}", path.display());

    loop {
        let (stream, _) = tokio::select! {
            _ = shutdown.cancelled() => break,
            r = listener.accept() => match r {
                Ok(s) => s,
                Err(e) => { tracing::warn!("unix accept failed: {e}"); continue; }
            },
        };
        // No credential, no connection: a caller the kernel cannot name is not served here.
        let cred = match stream.peer_cred() {
            Ok(c) => CallerCred { uid: c.uid(), gid: c.gid(), pid: c.pid() },
            Err(e) => {
                tracing::warn!("unix peer credential unavailable, dropping connection: {e}");
                continue;
            }
        };
        let app = app.clone();
        tokio::spawn(async move {
            let svc = hyper::service::service_fn(move |mut req: hyper::Request<hyper::body::Incoming>| {
                req.extensions_mut().insert(cred);
                app.clone().oneshot(req.map(axum::body::Body::new))
            });
            if let Err(e) = Builder::new()
                .serve_connection(TokioIo::new(stream), svc)
                .await
            {
                tracing::debug!("unix connection ended: {e}");
            }
        });
    }
    let _ = std::fs::remove_file(&path);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cred(uid: u32) -> Option<CallerCred> {
        Some(CallerCred { uid, gid: uid, pid: None })
    }
    fn map(pairs: &[(u32, &str)]) -> Result<BTreeMap<u32, String>> {
        Ok(pairs.iter().map(|(u, m)| (*u, m.to_string())).collect())
    }

    #[test]
    fn tcp_caller_is_asserted_only() {
        assert_eq!(check_claim(None, "x", &map(&[]), 1000), ClaimCheck::Asserted);
    }

    #[test]
    fn mapped_uid_connects_only_as_its_member() {
        let m = map(&[(1001, "legion-being")]);
        assert_eq!(
            check_claim(cred(1001), "legion-being", &m, 1000),
            ClaimCheck::PeercredMapped { uid: 1001 }
        );
        match check_claim(cred(1001), "claude-code", &m, 1000) {
            ClaimCheck::Refused { code, .. } => assert_eq!(code, "hestia.caller.mismatch"),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn unmapped_foreign_uid_is_refused_daemon_uid_is_unnarrowed() {
        let m = map(&[]);
        match check_claim(cred(1002), "anyone", &m, 1000) {
            ClaimCheck::Refused { code, .. } => assert_eq!(code, "hestia.caller.unmapped"),
            other => panic!("{other:?}"),
        }
        assert_eq!(
            check_claim(cred(1000), "anyone", &m, 1000),
            ClaimCheck::PeercredDaemonUid { uid: 1000 }
        );
    }

    #[test]
    fn a_mapped_daemon_uid_is_narrowed_like_any_other() {
        let m = map(&[(1000, "claude-code")]);
        match check_claim(cred(1000), "legion-being", &m, 1000) {
            ClaimCheck::Refused { code, .. } => assert_eq!(code, "hestia.caller.mismatch"),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn broken_map_fails_closed_except_for_the_operator_uid() {
        let m: Result<BTreeMap<u32, String>> = Err(anyhow::anyhow!("bad json"));
        match check_claim(cred(1002), "x", &m, 1000) {
            ClaimCheck::Refused { code, .. } => assert_eq!(code, "hestia.caller.uid_map_unreadable"),
            other => panic!("{other:?}"),
        }
        assert_eq!(check_claim(cred(1000), "x", &m, 1000), ClaimCheck::PeercredDaemonUid { uid: 1000 });
    }

    /// The listener stamps the kernel's uid on the request: a raw HTTP/1.1 GET over the socket
    /// reaches a handler that reads `CallerCred`, and the uid it reads is this process's.
    #[cfg(unix)]
    #[tokio::test]
    async fn unix_listener_stamps_the_peer_uid_on_each_request() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let dir = std::env::temp_dir().join(format!("hestia-sock-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let sock = dir.join("h.sock");
        let app = axum::Router::new().route(
            "/who",
            axum::routing::get(|axum::Extension(c): axum::Extension<CallerCred>| async move {
                c.uid.to_string()
            }),
        );
        let stop = tokio_util::sync::CancellationToken::new();
        let task = tokio::spawn(serve_unix(app, sock.clone(), stop.clone()));
        let mut stream = None;
        for _ in 0..100 {
            if let Ok(s) = tokio::net::UnixStream::connect(&sock).await {
                stream = Some(s);
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        let mut s = stream.expect("socket never came up");
        s.write_all(b"GET /who HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n").await.unwrap();
        let mut buf = String::new();
        s.read_to_string(&mut buf).await.unwrap();
        assert!(buf.starts_with("HTTP/1.1 200"), "{buf}");
        assert!(buf.ends_with(&daemon_uid().to_string()), "{buf}");
        stop.cancel();
        task.await.unwrap().unwrap();
        assert!(!sock.exists(), "socket file removed on shutdown");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn unix_listener_refuses_to_replace_a_non_socket() {
        let dir = std::env::temp_dir().join(format!("hestia-sock-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("not-a-socket");
        std::fs::write(&path, b"keep me").unwrap();
        let err = serve_unix(axum::Router::new(), path.clone(), Default::default()).await.unwrap_err();
        assert!(format!("{err:#}").contains("not a socket"), "{err:#}");
        assert_eq!(std::fs::read(&path).unwrap(), b"keep me");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn map_file_parses_and_rejects_bad_keys() {
        let dir = std::env::temp_dir().join(format!("hestia-uidmap-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        assert!(load_uid_map(&dir).unwrap().is_empty());
        std::fs::write(dir.join(CALLER_UID_MAP_FILE), r#"{"uids":{"1001":"legion-being"}}"#).unwrap();
        assert_eq!(load_uid_map(&dir).unwrap().get(&1001).map(String::as_str), Some("legion-being"));
        std::fs::write(dir.join(CALLER_UID_MAP_FILE), r#"{"uids":{"dp":"x"}}"#).unwrap();
        assert!(load_uid_map(&dir).is_err());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
