#!/usr/bin/env python3
from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    s = p.read_text()
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"{path}: expected one anchor, found {n}: {old[:120]!r}")
    p.write_text(s.replace(old, new, 1))

anchor = '''fn write_deployment_update_file(path: &std::path::Path, contents: &str) -> std::io::Result<()> {\n'''
helper = r'''fn create_deployment_update_request(
    path: &std::path::Path,
    contents: &str,
) -> std::io::Result<()> {
    use std::io::Write;
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)?;
    file.write_all(contents.as_bytes())?;
    file.sync_all()?;
    Ok(())
}

'''
replace_once('core/src/server/http.rs', anchor, helper + anchor)

p = Path('core/src/server/http.rs')
s = p.read_text()
old = '''    let age = chrono::Utc::now()
        .signed_duration_since(updated.with_timezone(&chrono::Utc))
        .num_minutes();
    let active = match fields[0] {
        "running" => (0..=60).contains(&age),
        "requested" | "held" => (0..=420).contains(&age),
        _ => false,
    };
'''
new = '''    let age_secs = chrono::Utc::now()
        .signed_duration_since(updated.with_timezone(&chrono::Utc))
        .num_seconds();
    let active = match fields[0] {
        "running" => (0..=60 * 60).contains(&age_secs),
        "requested" | "held" => (0..=420 * 60).contains(&age_secs),
        _ => false,
    };
'''
if s.count(old) != 1:
    raise SystemExit('http.rs: active status age anchor mismatch')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('core/src/server/dashboard.rs')
s = p.read_text()
old = '''    let age = chrono::Utc::now()
        .signed_duration_since(updated.with_timezone(&chrono::Utc))
        .num_minutes();
'''
new = '''    let age_secs = chrono::Utc::now()
        .signed_duration_since(updated.with_timezone(&chrono::Utc))
        .num_seconds();
'''
if s.count(old) != 1:
    raise SystemExit('dashboard.rs: status age anchor mismatch')
s = s.replace(old, new, 1)
s = s.replace('"requested" if (0..=420).contains(&age)', '"requested" if (0..=420 * 60).contains(&age_secs)', 1)
s = s.replace('"held" if (0..=420).contains(&age)', '"held" if (0..=420 * 60).contains(&age_secs)', 1)
s = s.replace('"running" if (0..=60).contains(&age)', '"running" if (0..=60 * 60).contains(&age_secs)', 1)
s = s.replace('"failed" if (0..=420).contains(&age)', '"failed" if (0..=420 * 60).contains(&age_secs)', 1)
s = s.replace('"succeeded" if (0..=420).contains(&age)', '"succeeded" if (0..=420 * 60).contains(&age_secs)', 1)
p.write_text(s)

p = Path('core/src/server/http.rs')
s = p.read_text()
old = '''    let requested_at = chrono::Utc::now().to_rfc3339();
    let request_record = format!("{request_id}\\n");
    let status_record = format!("requested\\t{request_id}\\t\\t{requested_at}\\n");
    if let Err(error) = write_deployment_update_file(&request_path, &request_record)
        .and_then(|_| write_deployment_update_file(&status_path, &status_record))
    {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({
                "status": "update_unavailable",
                "error": format!("cannot publish deployment update request: {error}"),
            })),
        );
    }

    {
        let mut s = state.lock().await;
        let record = super::operator_auth::attach_operator_provenance(
            serde_json::json!({
                "request_id": request_id,
                "operator": operator,
                "running_build": env!("HESTIA_GIT_VERSION"),
                "authority_build": authority_build,
                "platform": std::env::consts::OS,
                "mechanism": "registered-deployment-supervisor",
            }),
            provenance.as_ref(),
        );
        let _ = s.append_chain("deployment_update_requested", record);
    }

'''
new = '''    // SELF-WITNESS BEFORE SIDE EFFECT. The operator middleware witnesses authorization, but
    // this record binds the specific request id + deployment evidence. If the chain cannot
    // accept it, there is no supervisor request file and therefore no deployment act.
    {
        let mut s = state.lock().await;
        let record = super::operator_auth::attach_operator_provenance(
            serde_json::json!({
                "request_id": request_id,
                "operator": operator,
                "running_build": env!("HESTIA_GIT_VERSION"),
                "authority_build": authority_build,
                "platform": std::env::consts::OS,
                "mechanism": "registered-deployment-supervisor",
            }),
            provenance.as_ref(),
        );
        if let Err(error) = s.append_chain("deployment_update_request_intent", record) {
            return (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(serde_json::json!({
                    "status": "failed",
                    "error": format!("cannot witness deployment update request: {error}"),
                })),
            );
        }
    }

    let requested_at = chrono::Utc::now().to_rfc3339();
    let request_record = format!("{request_id}\\n");
    let status_record = format!("requested\\t{request_id}\\t\\t{requested_at}\\n");
    match create_deployment_update_request(&request_path, &request_record) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            return (
                StatusCode::ACCEPTED,
                Json(serde_json::json!({
                    "status": "requested",
                    "message": "another deployment update request is already queued",
                })),
            );
        }
        Err(error) => {
            let mut s = state.lock().await;
            let _ = s.append_chain(
                "deployment_update_publish_failed",
                super::operator_auth::attach_operator_provenance(
                    serde_json::json!({
                        "request_id": request_id,
                        "operator": operator,
                        "outcome": "not-published",
                        "error": error.to_string(),
                    }),
                    provenance.as_ref(),
                ),
            );
            return (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(serde_json::json!({
                    "status": "update_unavailable",
                    "error": format!("cannot publish deployment update request: {error}"),
                })),
            );
        }
    }
    if let Err(error) = write_deployment_update_file(&status_path, &status_record) {
        let _ = std::fs::remove_file(&request_path);
        let mut s = state.lock().await;
        let _ = s.append_chain(
            "deployment_update_publish_failed",
            super::operator_auth::attach_operator_provenance(
                serde_json::json!({
                    "request_id": request_id,
                    "operator": operator,
                    "outcome": "not-published",
                    "error": error.to_string(),
                }),
                provenance.as_ref(),
            ),
        );
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({
                "status": "failed",
                "error": format!("cannot publish deployment update status: {error}"),
            })),
        );
    }

'''
if s.count(old) != 1:
    raise SystemExit('http.rs: request publication block anchor mismatch')
s = s.replace(old, new, 1)

test_anchor = '''    #[test]
    fn unsupported_platform_has_no_shell_fallback() {
        assert_eq!(deployment_update_trigger_for("windows", None), None);
    }
'''
tests = '''    #[test]
    fn unsupported_platform_has_no_shell_fallback() {
        assert_eq!(deployment_update_trigger_for("windows", None), None);
    }

    #[test]
    fn deployment_update_request_file_is_exclusive() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("deploy-update.request");
        create_deployment_update_request(&path, "first\\n").unwrap();
        let second = create_deployment_update_request(&path, "second\\n")
            .expect_err("a second request must not overwrite the queued request id");
        assert_eq!(second.kind(), std::io::ErrorKind::AlreadyExists);
        assert_eq!(std::fs::read_to_string(path).unwrap(), "first\\n");
    }

    #[test]
    fn active_update_status_rejects_expired_and_future_timestamps() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("deploy-status.tsv");
        let now = chrono::Utc::now();
        std::fs::write(&path, format!("running\\treq-now\\ttarget\\t{}\\n", now.to_rfc3339())).unwrap();
        assert_eq!(active_deployment_update(&path), Some(("running".into(), "req-now".into())));
        std::fs::write(&path, format!("running\\treq-old\\ttarget\\t{}\\n", (now - chrono::Duration::minutes(61)).to_rfc3339())).unwrap();
        assert_eq!(active_deployment_update(&path), None);
        std::fs::write(&path, format!("running\\treq-future\\ttarget\\t{}\\n", (now + chrono::Duration::seconds(30)).to_rfc3339())).unwrap();
        assert_eq!(active_deployment_update(&path), None);
    }
'''
if s.count(test_anchor) != 1:
    raise SystemExit('http.rs: deployment test anchor mismatch')
s = s.replace(test_anchor, tests, 1)
p.write_text(s)

p = Path('core/src/server/dashboard.rs')
s = p.read_text()
anchor = '''    #[test]
    fn deployment_health_separates_daemon_build_from_last_gate_self_report() {
'''
tests = '''    #[test]
    fn deployment_update_status_projects_supervisor_states_without_inventing_success() {
        if !(cfg!(target_os = "linux") || cfg!(target_os = "macos")) {
            return;
        }
        let dir = TempDir::new().unwrap();
        let manifest = dir.path().join("current-build.json");
        std::fs::write(&manifest, r#"{"build_id":"authority-build"}"#).unwrap();
        let status = dir.path().join("deploy-status.tsv");
        let now = chrono::Utc::now();
        for (wire, expected) in [("requested", "requested"), ("held", "held"), ("running", "running"), ("failed", "failed"), ("succeeded", "failed")] {
            std::fs::write(&status, format!("{wire}\\treq-1\\ttarget-build\\t{}\\n", now.to_rfc3339())).unwrap();
            let health = deployment_health_from_path(Some(&manifest));
            assert_eq!(health.state, "stale");
            assert_eq!(health.update_state, expected, "wire state {wire}");
            assert_eq!(health.update_request_id.as_deref(), Some("req-1"));
        }
        std::fs::write(&status, format!("running\\treq-future\\ttarget-build\\t{}\\n", (now + chrono::Duration::seconds(30)).to_rfc3339())).unwrap();
        let future = deployment_health_from_path(Some(&manifest));
        assert_eq!(future.state, "stale");
        assert_eq!(future.update_state, "failed");
        std::fs::write(&manifest, format!(r#"{{"build_id":"{}"}}"#, env!("HESTIA_GIT_VERSION"))).unwrap();
        let health = deployment_health_from_path(Some(&manifest));
        assert_eq!(health.state, "current");
        assert_eq!(health.update_state, "idle");
        assert!(health.update_request_id.is_none());
    }

    #[test]
    fn deployment_health_separates_daemon_build_from_last_gate_self_report() {
'''
if s.count(anchor) != 1:
    raise SystemExit('dashboard.rs: test anchor mismatch')
s = s.replace(anchor, tests, 1)
p.write_text(s)

p = Path('tools/dashboard_deployment_update_contract_test.py')
s = p.read_text()
s = s.replace(
    "'daemon does not invent future target': 'request_record = format!(\"{request_id}\\\\n\")' in http,",
    "'daemon does not invent future target': 'request_record = format!(\"{request_id}\\\\n\")' in http,\n    'request publication is exclusive': '.create_new(true)' in http and 'another deployment update request is already queued' in http,\n    'request is witnessed before publication': http.index('deployment_update_request_intent') < http.index('create_deployment_update_request(&request_path'),\n    'future status cannot be active': '.num_seconds()' in http and '.num_seconds()' in Path('core/src/server/dashboard.rs').read_text(),"
)
p.write_text(s)
