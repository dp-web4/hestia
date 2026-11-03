import importlib.util
import json
import time

spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)
h, session_id = hm.connect()

REPLIES = [
    (35668, "https://github.com/dp-web4/SAGE/issues/622#issuecomment-6613873527;kimi-review:HOLD-exact-901b6ba8;62-pass-1-skip;seven-unsafe-synthetic-forms-including-cross-block-survival-import-provenance-and-qualifiers;two-positive-controls-pass;via=kimi-code"),
    (35725, "https://github.com/dp-web4/SAGE/pull/549#issuecomment-6613874174;kimi-review:narrow-ambiguous-send-fallback-concur-121-pass;overall-HOLD-missing-or-malformed-claim-ledger-reads-as-unspent-plus-policy-hold;via=kimi-code"),
    (35746, "https://github.com/dp-web4/SAGE/pull/619#issuecomment-6613874567;kimi-review:recovery-slice-GO-167-pass;partial-outcome-and-evidence-preserved;other-slices-and-durability-limits-remain;via=kimi-code"),
    (35764, "https://github.com/dp-web4/SAGE/pull/619#issuecomment-6613874567;kimi-review:selector-slice-GO-163-pass;question+answer-selects-evidence-does-not;via=kimi-code"),
    (35800, "https://github.com/dp-web4/SAGE/pull/619#issuecomment-6613874567;kimi-review:broad-confirmation-slice-GO-175-pass;process-local-same-beat-and-missing-recovery-integration-limits;via=kimi-code"),
    (35819, "https://github.com/dp-web4/SAGE/pull/619#issuecomment-6613874567;kimi-review:integrated-candidate-GO-182-pass;final-merged-b948-focused-19-pass;via=kimi-code"),
    (35674, "https://github.com/dp-web4/hestia/pull/1407#issuecomment-6613875023;kimi-review:cache-source-GO;e612-and-current-v5-c7fb-digests-reproduced;cache-contract-and-27-decide-parity-pass;governed-apply-HOLD;via=kimi-code"),
    (35685, "https://github.com/dp-web4/hestia/pull/1224#issuecomment-6613875472;kimi-review:recut-GO-26-checks-25-contracts+31x4;targeted-4x4-agree-zero-mismatch-degraded;all-ten-CI-green-merged;via=kimi-code"),
    (35722, "https://github.com/dp-web4/hestia/issues/1474#issuecomment-6613875905;kimi-review:CONFIRMED-current-main-recursive-local-path-allows-foreign-remote-read+delete;path-only-projection-denies-remote-and-preserves-local-boundary;via=kimi-code"),
    (35728, "https://github.com/dp-web4/hestia/pull/1453#issuecomment-6613876391;kimi-review:consumer-identity-HOLD-confirmed;bin/cat-and-function-redefinition-overall-allow-and-bash-executes-removed-body;existing-12+38-controls-pass;via=kimi-code"),
]

for notice_id, pointer in REPLIES:
    out = hm.rpc(h, "hestia_member_notify", {
        "session_id": session_id,
        "to_plugin_id": "codex",
        "kind": "reply",
        "pointer_uri": pointer,
        "in_reply_to": notice_id,
    })
    error = out.get("_jsonrpc_error") or out.get("error")
    print(json.dumps({"in_reply_to": notice_id, "queued_id": out.get("queued_id"),
                      "binding_verified": out.get("binding_verified"), "error": error}))
    time.sleep(0.4)
