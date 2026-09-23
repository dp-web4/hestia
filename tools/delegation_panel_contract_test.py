#!/usr/bin/env python3
"""Delegated authority, from the agent (agent-lifecycle PRD R5): derived key, closed roles, no delete.

`hestia delegate grant/list/revoke` existed as a CLI writing the vault directly; the dashboard
snapshot already carried `delegations`; no screen rendered them and there was no route. dp,
2026-09-19: "i can't inspect or manage roles or their environments." This is the last half of
that ask. What is pinned is the shape of the authority it hands out:

  * the agent is the one in the URL -- the grant body may not name an agent, and the daemon
    refuses one that does (#1067 by another door);
  * the delegation key is DERIVED from the registry LCT, never typed (#952);
  * roles are a picker over the daemon's closed list, which this test reads out of the Rust
    source and requires the daemon to hand to the page -- a role added to the law without the
    picker goes red, and a free-text role is refused as a typed identity;
  * a retired id is refused, and retiring revokes delegations;
  * revoked delegations stay LISTED, marked -- the history stays readable from the screen that
    made it.

The renderer is pure and is run under node against the daemon's answer shape.

Run: python3 tools/delegation_panel_contract_test.py     (exit 1 on failure)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "core/src/server/dashboard/index.html").read_text()
RS = (ROOT / "core/src/server/http.rs").read_text()
ST = (ROOT / "core/src/server/state.rs").read_text()
FAILS: list[str] = []


def check(name: str, got, want=True) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def block() -> str:
    a = UI.index("  // ── Delegated authority, from the agent")
    return UI[a:UI.index("  let showRetired = false;", a)]


def law_roles() -> list[str]:
    m = re.search(r"pub const DELEGATION_ROLES: &\[&str\] = &\[(.*?)\];", RS, re.S)
    return re.findall(r'"([^"]+)"', m.group(1)) if m else []


def source_contract() -> None:
    blk = block()
    law = law_roles()
    check("the daemon's role list was found", len(law) == 9, True)
    # The page never carries the list itself: it renders what the daemon hands it, so the two
    # cannot drift. Pinned as an absence.
    for r in law:
        check(f"the page does not hard-code the role '{r}'", f"'{r}'" in blk or f'"{r}"' in blk, False)
    check("the picker is built from the daemon's list", "roles.map(r => `<option" in blk)
    check("the grant body names no agent", bool(re.search(r"const body = \{ roles, actions, reason \};", blk)))
    check("the agent comes from the URL only", "/delegations`" in blk and "encodeURIComponent(pluginId)" in blk)
    check("revoke asks for a reason", "prompt(`Revoke delegation" in blk)
    for verb in ("'DELETE'", '"DELETE"'):
        check(f"no {verb} in the panel", verb in blk, False)
    # The daemon's half.
    check("the daemon refuses a typed agent in the body",
          'for k in ["agent", "agent_id", "agent_lct_id", "plugin_id"] {' in RS)
    check("the daemon refuses a free-text role", "is not one of the society roles" in RS)
    check("the daemon derives the key from the registry LCT", "crate::delegation::agent_key_for_lct(&lct.lct_id())" in RS)
    check("a retired id is refused a delegation", 'refuse_if_retired(s, plugin_id, "a delegation")' in RS)
    check("a revoke through the wrong agent's panel is refused", "does not belong to" in RS)
    check("grant is witnessed intent-then-commit", '"delegation_grant_intent"' in RS and '"delegation_granted"' in RS)
    check("the delegator is the operator's own key, never a throwaway",
          "crate::delegation::operator_delegator(&s.vault, &s.home)" in RS)
    check("retiring revokes delegations", "delegations.push(d.id.to_string());" in ST)


def run(expr: str, arg) -> object:
    blk = block()
    pure = blk[blk.index("  function delegationsHtml("):blk.index("  async function delegationGrant(")]
    prog = ("const escapeHtml = s => String(s).replace(/[&<>\"]/g, c => '&#' + c.charCodeAt(0) + ';');\n"
            + pure + f"\nconst A = JSON.parse(process.argv[1]); process.stdout.write(JSON.stringify({expr}));")
    r = subprocess.run(["node", "-e", prog, json.dumps(arg)], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        FAILS.append(f"node failed: {r.stderr.strip()[-300:]}")
        return None
    return json.loads(r.stdout)


def behaviour() -> None:
    law = law_roles()
    out = {"plugin_id": "kimi-code", "agent_key": "0f1e2d3c-0000-0000-0000-000000000000", "roles": law,
           "delegations": [
               {"id": "aaaaaaaa-1111-2222-3333-444444444444", "active": True, "revoked": False,
                "expires_at": "2026-10-01T00:00:00Z", "scope": {"roles": ["Witness"], "actions": ["scope.decide:codex:/w"]}},
               {"id": "bbbbbbbb-1111-2222-3333-444444444444", "active": False, "revoked": True,
                "expires_at": None, "scope": {"roles": [], "actions": []}}]}
    html = run("delegationsHtml(A.plugin_id, A)", out) or ""
    check("an active delegation gets a revoke control", 'data-deleg-revoke="aaaaaaaa-1111-2222-3333-444444444444"' in html)
    check("a REVOKED delegation stays listed and marked, with no revoke control",
          "revoked" in html and 'data-deleg-revoke="bbbbbbbb' not in html and "deleg-off" in html)
    check("the scope is shown", "Witness" in html and "scope.decide:codex:/w" in html)
    check("an unrestricted scope says so rather than showing nothing", "unrestricted" in html)
    check("the picker offers exactly the daemon's roles, in order",
          re.findall(r'<option value="([^"]+)">', html), law)
    check("the derived key is shown, not asked for", "0f1e2d3c" in html and 'id="deleg-agent"' not in html)
    empty = run("delegationsHtml(A.plugin_id, A)", {"plugin_id": "x", "agent_key": "k", "roles": law, "delegations": []}) or ""
    check("no delegations renders as an honest empty, with the form", "No delegations." in empty and 'id="deleg-grant"' in empty)
    garbage = run("delegationsHtml('x', A)", {}) or ""
    check("garbage in: survives, empty picker", "No delegations." in garbage)


def test_delegation_panel_contract() -> None:
    """pytest's entry: the same checks, and a failure it can see."""
    FAILS.clear()
    source_contract()
    if shutil.which("node"):
        behaviour()
    assert not FAILS, "\n".join(FAILS)


def main() -> int:
    try:
        test_delegation_panel_contract()
    except AssertionError:
        pass
    if not shutil.which("node"):
        print("SKIPPED: behaviour -- no node on PATH (the source contract above still ran)")
    for f in FAILS:
        print("FAIL", f)
    print(f"delegation panel contract: {'FAIL' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
