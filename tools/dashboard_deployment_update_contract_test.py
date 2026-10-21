#!/usr/bin/env python3
from pathlib import Path

http = Path('core/src/server/http.rs').read_text()
ui = Path('core/src/server/dashboard/index.html').read_text()
deploy = Path('deploy/from-main/hestia-deploy.sh').read_text()

checks = {
    'operator route exists': '"/api/operator/deployment/update"' in http,
    'handler accepts no JSON body': 'async fn operator_deployment_update(\n    State(state): State<SharedState>,\n    headers: HeaderMap,' in http,
    'linux trigger is fixed/nonblocking': '["--user", "--no-block", "start", "hestia-deploy.service"]' in http,
    'mac trigger fixed label': 'com.web4.hestia.deploy' in http and 'kickstart' in http,
    'unsupported has no shell fallback': 'no deployment supervisor trigger for' in http,
    'stale UI has update button': 'id="deployment-update"' in ui,
    'UI sends no request body': "apiFetch('/api/operator/deployment/update', { method: 'POST' })" in ui,
    'daemon does not invent future target': 'request_record = format!("{request_id}\\n")' in http,
    'request publication is exclusive': '.create_new(true)' in http and 'another deployment update request is already queued' in http,
    'request is witnessed before publication': http.index('deployment_update_request_intent') < http.index('create_deployment_update_request(&request_path'),
    'future status cannot be active': '.num_seconds()' in http and '.num_seconds()' in Path('core/src/server/dashboard.rs').read_text(),
    'string errors use std Result, not anyhow alias': 'std::result::Result<(std::path::PathBuf, String, Option<String>), String>' in http and 'std::result::Result<(), String>' in http,
    'supervisor claims bounded request': 'deploy-update.request' in deploy and 'deploy-status.tsv' in deploy and 'UPDATE_TARGET="$target"' in deploy,
    'supervisor terminal status composes with lock cleanup': 'trap cleanup_deploy EXIT' in deploy and 'finish_update_status "$rc"' in deploy,
    # The update CHECK (tl-dell 2026-10-21: "check for update means ONLY to check").
    'check route exists': '"/api/operator/deployment/check"' in http,
    'check trigger starts only the check unit': '"hestia-deploy-check.service".into()' in http
        and 'fn deployment_check_trigger_for' in http,
    'check is witnessed before it is triggered': http.index('"deployment_check_requested"') < http.index('deployment_trigger_output(&trigger_for_run)).await {\n        Ok(result) => result,\n        Err(error) => Err(format!("update check trigger'),
    'UI check sends no request body': "apiFetch('/api/operator/deployment/check', { method: 'POST' })" in ui,
    'UI says up to date only from a check': "`● up to date${checked}`" in ui and "deployment current" not in ui,
    'supervisor records its verdict': 'deploy-check.tsv' in deploy and 'write_check_result up-to-date' in deploy
        and 'write_check_result available' in deploy,
    'a check never self-updates the script': '[ "$MODE" != "--check" ] && [ -f "$DEPLOY_ROOT/hestia/deploy/from-main/hestia-deploy.sh" ]' in deploy,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(('ok  ' if ok else 'FAIL') + name)
if failed:
    raise SystemExit('dashboard deployment update contract failed: ' + ', '.join(failed))
print('dashboard deployment update contract: PASS')
