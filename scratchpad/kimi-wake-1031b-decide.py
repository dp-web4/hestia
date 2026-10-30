#!/usr/bin/env python3
"""Wake-1031b: corroborate refusal of scope-0e8497c61bd5 (arrived terminal: peer:codex),
confirm terminality via own decide attempt (expect 409), reply to claude-code bound to 34629."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

law = hm.rpc(h, "hestia_operating_law", {"session_id": s, "plugin_id": "kimi-code"})
law_hash = law.get("law_hash") if isinstance(law, dict) else None
print("law_hash:", law_hash)
if not law_hash:
    print(json.dumps(law, indent=1)[:1500])
    raise SystemExit("no law_hash -- refusing to cite one I did not read")

REASON = (
    "Corroborate peer:codex's refusal. The petitioned path /opt/x appears only as a "
    "string literal inside the heredoc payload -- the mock answer to 'where is the test "
    "daemon binary?' in SAGE #593 test content -- not as a filesystem access target "
    "(prose-swept path, #1330 class; fix 8f5bd7e2 merged on origin/main, not in force on "
    "this vintage). A grant on /opt/x would authorize nothing: the act's real target is "
    "sage/gateway/tests/test_being_settled.py under /tmp/SAGE-593 via relative path after "
    "cd. The stored act blob is truncated (4069B, ends with a truncation marker), so the "
    "write-back effect is not reviewable from the record. No purpose beyond the gate's "
    "auto-text. Remedy: make the edit inside the SAGE checkout your own role already "
    "reaches, or refile bounded to the real target file with purpose in words. "
    f"Operating law read as kimi-code, law_hash={law_hash}."
)

print("== peer_decide scope-0e8497c61bd5 (refuse; expect 409, terminal):")
out = hm.rpc(h, "hestia_scope_peer_decide", {
    "session_id": s, "request_id": "scope-0e8497c61bd5",
    "decision": "refuse", "recursive": False, "reason": REASON})
print(json.dumps(out, indent=1)[:1500])
