#!/usr/bin/env python3
"""Govern -> vault contract (2026-09-25). The operator can see and remove credentials from a
running box. Nothing else could: the CLI is locked out by the daemon's writer lease. Neither
operator surface, nor an agent, can delete or write the daemon's own entries.

Source-level, in the house idiom (runtime_config_operator_surface_test.py): each check names
the construct it pins. The Rust tests prove the handlers refuse and witness. They cannot see
that the dashboard pane exists, that the list never renders a value, that the app hides delete
on a daemon entry, or that nobody has since added a reveal. Those are properties of what is
ABSENT from a surface, and a unit test of present behaviour never checks them.
"""
from pathlib import Path

vault_rs = Path('core/src/vault/mod.rs').read_text(encoding='utf-8')
http = Path('core/src/server/http.rs').read_text(encoding='utf-8')
handler = Path('core/src/server/handler.rs').read_text(encoding='utf-8')
ui = Path('core/src/server/dashboard/index.html').read_text(encoding='utf-8')
app_page = Path('app/src/pages/Vault.tsx').read_text(encoding='utf-8')

def between(text, a, b):
    i = text.index(a)
    return text[i:text.index(b, i)]

gated = http[http.index('let operator_surface = axum::Router::new()'):http.index('operator_gate,\n        ))')]
pane_js = between(ui, '// ---- VAULT pane', '// ---- RUNTIME CONFIG pane')
pane_html = between(ui, 'id="govern-vault"', '</section>')
delete_fn = between(http, 'async fn vault_delete(', '\n}\n')
add_fn = between(http, 'async fn vault_add(', '\n}\n')
mcp_set = between(handler, 'async fn tool_vault_set(', 'let session_id_arg')

checks = {
    # --- one classifier, used by every running write surface
    'one system-entry classifier': 'pub fn system_entry_role(name: &str) -> Option<&\'static str>' in vault_rs,
    'identity, device keys and hub config are classified': all(n in vault_rs for n in (
        '"ai_identity_secret"', '"ai_identity_pubkey"', '"ai_identity_lct_id"', '"hub_urls"',
        '"constellation_device_key:"')),
    # --- operator HTTP: gated, refuses daemon entries, witnesses, honest status codes
    'vault routes are operator-gated': '.route("/api/vault", get(vault_list).post(vault_add))' in gated
        and '.route("/api/vault/:name", delete(vault_delete))' in gated,
    'delete refuses a daemon entry before touching the vault': delete_fn.index('system_entry_role') < delete_fn.index('s.vault.remove'),
    'delete is witnessed': '"vault_entry_removed"' in delete_fn,
    'delete of a missing name is 404': 'StatusCode::NOT_FOUND' in delete_fn,
    'add refuses a daemon name': 'system_entry_role(name)' in add_fn and 'StatusCode::CONFLICT' in add_fn,
    'add is witnessed without the value': '"vault_entry_added"' in add_fn
        and '"value"' not in add_fn[add_fn.index('"vault_entry_added"'):add_fn.index('"vault_entry_added"') + 300],
    'list marks daemon entries': '"system": crate::vault::system_entry_role(name)' in http,
    # --- agent MCP: the upsert cannot reach a daemon entry
    'MCP vault_set refuses daemon names first': 'system_entry_role(&name)' in mcp_set
        and 'hestia.vault_name_reserved' in mcp_set,
    # --- dashboard: Govern -> vault, same wrapper, no value anywhere, no delete on daemon rows
    'dashboard has the govern chip': 'data-gov="vault"' in ui,
    'dashboard pane is registered': "vault:  { el: 'govern-vault',  mount: () => vaultLoad() }" in ui,
    'dashboard lists through apiFetch': "apiFetch('/api/vault')" in pane_js,
    'dashboard never renders or requests a value': '.secret' not in pane_js and 'e.value' not in pane_js
        and "apiFetch('/api/vault/' + encodeURIComponent(name), { method: 'DELETE' })" in pane_js
        and pane_js.count("apiFetch('/api/vault/'") == 1,
    'dashboard offers no delete on a daemon row': "${e.system ? '' : '<button type=\"button\" class=\"grant-revoke vault-del\">delete</button>'}" in pane_js,
    'dashboard delete requires typing the name': 'typed.trim() !== name' in pane_js,
    'dashboard value input is a password field': 'id="vault-new-value" type="password"' in pane_html,
    # --- app: same API, no delete on a daemon row, confirmation
    'app hides delete on a daemon entry': '{entry.system ? (' in app_page,
    'app delete requires typing the name': 'typed.trim() !== name' in app_page,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(('ok  ' if ok else 'FAIL') + name)
if failed:
    raise SystemExit('vault operator surface contract failed: ' + ', '.join(failed))
print('vault operator surface contract: PASS')
