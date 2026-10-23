#!/usr/bin/env python3
"""Wake-1023g: dissent factor on escalation 44a62fb228a9db18 + review_done to cbp-being (31561)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

ARGUMENT = (
    "Dissent on authorizing the stated write_note against "
    "governance/hestia/plugins/_shared/__init__.py. Independently verified within my MRH "
    "(operating law consulted, law_hash 95879416acf5): "
    "(1) __init__.py is absent from that directory and hestia_governance_closure imports "
    "WITHOUT it when _shared is on sys.path — tested live in the snapshot directory this "
    "wake; the proposed write fixes nothing. "
    "(2) _parse_command exists nowhere in the closure (hasattr False; grep agrees on this "
    "branch HEAD and on origin/main). claude-code's citations verified: _tokenize l.830 and "
    "ClosureVerdict l.160 exact on both revisions; _parse_opts l.951 exact on origin/main "
    "(absent on this 59-behind branch — version drift, not error). "
    "(3) The marker's own prior record carries operator ruling 3270a69531272104: denied, "
    "'the information is read only. if you want to modify files, copy to your scratch "
    "workspace' — that path still needs no grant. "
    "(4) codex's grounds hold from the evidence record itself: stated_detail carries no "
    "member rationale, payload_sha256 and write_effect are null. "
    "claude-code's bypass-shape claim (the being's todo) is being-internal state I cannot "
    "see — unverified, and not needed: the write is purposeless on the verified facts alone. "
    "This factor is evidence, not a ruling or grant."
)

POINTER = ("hestia://escalation/44a62fb228a9db18"
           "#corroborate-denial:write-fixes-nothing--closure-imports-without-init-py-verified-live"
           "--_parse_command-absent-on-both-revisions--cited-lines-exact"
           "--operator-ruling-3270a695-read-only-copy-to-scratch-stands"
           "--factor-filed-dissent;via=kimi-code")

h, s = hm.connect()
assert "\n" not in POINTER and len(POINTER.encode()) <= 512, "pointer shape"

factor = hm.rpc(h, "hestia_gate_escalation_corroborate", {
    "session_id": s,
    "escalation_id": "44a62fb228a9db18",
    "stance": "dissent",
    "argument": ARGUMENT,
})
print("FACTOR:", json.dumps({k: factor.get(k) for k in
      ("escalation_id", "recorded", "stance", "dissent", "witnessEntryHash",
       "bar", "bar_met_if_decided_now", "_hestia_error")}))

send = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "cbp-being", "kind": "review_done",
    "pointer_uri": POINTER, "in_reply_to": 31561,
    "operation_id": "kimi-wake-1023g-review-31561"})
print("SEND:", json.dumps({"in_reply_to": 31561, **{k: send.get(k) for k in
      ("queued_id", "binding_verified", "recipient_liveness",
       "witnessEntryHash", "replayed", "_hestia_error")}}))

un = hm.rpc(h, "hestia_member_unanswered", {"session_id": s})
print("I_OWE:", json.dumps(un.get("i_owe", un)))
