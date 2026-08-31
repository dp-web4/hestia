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
    'string errors use std Result, not anyhow alias': 'std::result::Result<(std::path::PathBuf, String), String>' in http and 'std::result::Result<(), String>' in http,
    'supervisor claims bounded request': 'deploy-update.request' in deploy and 'deploy-status.tsv' in deploy and 'UPDATE_TARGET="$target"' in deploy,
    'supervisor terminal status composes with lock cleanup': 'trap cleanup_deploy EXIT' in deploy and 'finish_update_status "$rc"' in deploy,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(('ok  ' if ok else 'FAIL') + name)
if failed:
    raise SystemExit('dashboard deployment update contract failed: ' + ', '.join(failed))
print('dashboard deployment update contract: PASS')
