#!/usr/bin/env python3
"""#944 phase 0 contract: the operator can VIEW and EDIT vault-authored seat config from both
operator surfaces, over one API, and nothing on this surface can DELETE the authoritative
document. Source-level, in the house idiom (dashboard_deployment_update_contract_test.py):
each check names the construct it pins, so a refactor that drops one fails by name.

Why a source contract and not only the Rust tests: the Rust tests prove the daemon's two
GETs behave; they cannot see that the dashboard pane exists, that the app's commands are
registered, or that nobody has since added `delete(config_...)` to the router — the
"no DELETE in phase 0" rule is about what is ABSENT, and absence is what a unit test of
present behaviour never checks.
"""
from pathlib import Path

http = Path('core/src/server/http.rs').read_text(encoding='utf-8')
auth = Path('core/src/server/operator_auth.rs').read_text(encoding='utf-8')
ui = Path('core/src/server/dashboard/index.html').read_text(encoding='utf-8')
app_cmds = Path('app/src-tauri/src/commands/config.rs').read_text(encoding='utf-8')
app_lib = Path('app/src-tauri/src/lib.rs').read_text(encoding='utf-8')
app_ts = Path('app/src/lib/tauri.ts').read_text(encoding='utf-8')
app_ui = Path('app/src/components/RuntimeConfig.tsx').read_text(encoding='utf-8')
vault_page = Path('app/src/pages/Vault.tsx').read_text(encoding='utf-8')

gated = http[http.index('let operator_surface = axum::Router::new()'):http.index('operator_gate,\n        ))')]

checks = {
    # --- one API contract, both GETs behind the operator gate, PUT unchanged
    'list route is operator-gated': '.route("/api/config/seat", put(config_put_seat).get(config_list_seats))' in gated,
    'inspect route is operator-gated': '.route("/api/config/seat/:plugin_id", get(config_get_seat))' in gated,
    'NO DELETE on seat config (phase 0)': 'delete(config_' not in http and '"/api/config/seat/:plugin_id", delete' not in http,
    'list never serialises a value': '"keys": cfg.env.keys().cloned().collect::<Vec<_>>()' in http
        and 'fn seat_config_summary' in http and '"env"' not in http[http.index('fn seat_config_summary'):http.index('async fn config_list_seats')],
    'a GET never renders or repairs': 'render_to_disk' not in http[http.index('fn seat_config_summary'):http.index('async fn scope_grant')]
        and 'render_and_verify_seat_configs' not in http[http.index('fn seat_config_summary'):http.index('async fn scope_grant')],
    'inspect is witnessed by member and keys, not values': '"config_seat_inspected"' in http
        and '"keys": cfg.env.keys().cloned().collect::<Vec<_>>()' in http[http.index('"config_seat_inspected"') - 400:http.index('"config_seat_inspected"') + 400],
    'inspect id is validated as one plain name': 'if !seat_id_is_a_plain_name(&member)' in http,
    # the act row NAMES its authorization (GateWitness pointer + provenance), never a generic claim
    'inspect row is stamped with the gate witness': 'stamp_gate(' in http[http.index('"config_seat_inspected"'):http.index('"config_seat_inspected"') + 300]
        and 'gate: Option<axum::Extension<super::operator_auth::GateWitness>>' in http[http.index('async fn config_get_seat'):http.index('async fn config_get_seat') + 300],
    'inspect row carries no generic decided_by claim': '"decided_by"' not in http[http.index('"config_seat_inspected"'):http.index('"config_seat_inspected"') + 300],
    # --- the shared set (dp 2026-09-05): one reserved document every seat inherits, same API
    'shared set is a reserved document, not a seat': 'pub const SHARED_MEMBER: &str = "_shared";' in Path('core/src/server/seat_config.rs').read_text(encoding='utf-8')
        and '!is_shared(&item.name)' in Path('core/src/server/seat_config.rs').read_text(encoding='utf-8'),
    'a seat may not restate a shared key': 'keys_owned_by_shared' in http and 'belong to the shared set' in http,
    'a shared write re-renders every seat as an author pass': 'ConfigPass::Author' in http and 'sc::members_to_check(&s.vault, &home, &connected)' in http[http.index('async fn config_put_seat'):http.index('async fn scope_grant')],
    'the worker still detects (verify before render)': 'render_and_verify_seat_configs_as(s, members, ConfigPass::Detect)' in Path('core/src/server/handler.rs').read_text(encoding='utf-8'),
    'list names shared keys apart, never values': '"shared": shared,' in http and '"inherited":' in http,
    'dashboard shows the shared row and inherited lines': 'data-member="_shared"' in ui and "id=\"cfg-inherited\"" in ui,
    'app shows the shared row and inherited lines': 'open("_shared", shared.configured)' in app_ui and 'cfg-env-inherited' in app_ui,
    # --- stakes: above the read flood, below the credential tier
    'inspect stakes are high-reversible': 'path.starts_with("/api/config/seat/")' in auth and 'return Stakes::HighReversible;' in auth[auth.index('path.starts_with("/api/config/seat/")'):auth.index('path.starts_with("/api/config/seat/")') + 200],
    # --- no ambient exposure
    'dashboard read model does not carry seat config': 'seat_config' not in Path('core/src/server/dashboard.rs').read_text(encoding='utf-8'),
    # --- dashboard: Govern -> Runtime config, same wrapper
    'dashboard has the govern chip': 'data-gov="config"' in ui,
    'dashboard pane is registered': "config: { el: 'govern-config', mount: () => cfgLoadList() }" in ui,
    'dashboard uses apiFetch for list': "apiFetch('/api/config/seat')" in ui,
    'dashboard uses apiFetch for inspect': "apiFetch('/api/config/seat/' + encodeURIComponent(member))" in ui,
    'dashboard saves through the #921 PUT': "method: 'PUT', headers: { 'content-type': 'application/json' }" in ui[ui.index('async function cfgSave'):ui.index('function wireRuntimeConfig')],
    'dashboard has no delete for seat config': 'DELETE' not in ui[ui.index('RUNTIME CONFIG pane'):ui.index('function wireRuntimeConfig')],
    # --- app: same three verbs over the authed daemon transport, registered, no delete
    'app commands go through daemon::get/send': 'daemon::get(&state, "/api/config/seat")' in app_cmds and 'reqwest::Method::PUT' in app_cmds,
    'app has no delete command': 'DELETE' not in app_cmds and 'config_seat_delete' not in app_lib,
    'app commands are registered once each': all(app_lib.count(f'commands::config::{c},') == 1 for c in ('config_seat_list', 'config_seat_get', 'config_seat_put')),
    'app ts wrappers exist': all(f in app_ts for f in ('configSeatList', 'configSeatGet', 'configSeatPut')),
    'app Vault page mounts the section': '<RuntimeConfig />' in vault_page,
    'app editor saves through PUT and re-inspects': 'configSeatPut(selected, env, note)' in app_ui and 'configSeatGet(selected)' in app_ui,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(('ok  ' if ok else 'FAIL') + name)
if failed:
    raise SystemExit('runtime config operator surface contract failed: ' + ', '.join(failed))
print('runtime config operator surface contract: PASS')
