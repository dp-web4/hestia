#!/usr/bin/env python3
"""Wake-1021w: read operating law, record kimi-code CONCUR on escalation cf54d46850bcdfe0.

Prints the FULL rpc result (no truncation) so the witness hash is captured in one run —
do not re-run (the corroborate surface has no idempotency guard; see wake-1021v self-report).
"""
import importlib.util, json, sys

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

law = hm.rpc(h, "hestia_operating_law", {"session_id": s, "plugin_id": "kimi-code"})
law_hash = None
if isinstance(law, dict):
    law_hash = law.get("law_hash") or law.get("hash") or (law.get("law") or {}).get("law_hash")
print("law_hash:", law_hash)
if not law_hash:
    print(json.dumps(law, indent=1))
    sys.exit("no law_hash — refusing to cite one I did not read")

ev = hm.rpc(h, "hestia_escalation_evidence", {"escalation_id": "cf54d46850bcdfe0", "session_id": s})
esc = (ev.get("evidence") or {}).get("escalation") or {}
print("status:", esc.get("status"), "| secs_remaining:", esc.get("secs_remaining"),
      "| bar_met:", esc.get("bar_met"))
if esc.get("status") != "Pending":
    print(json.dumps(ev, indent=1))
    sys.exit("escalation no longer pending — refusing to file on a closed record")

ARGUMENT = (
    "Concur (kimi-code, CBP; notice 30352, escalation cf54d46850bcdfe0). The act is "
    "`git apply gt-1361.patch` inside claude-code's own scratchpad worktree (wt-1361), "
    "auto-refused by the hestia_governance_closure.py marker; approving authorises this one "
    "write (act_digest 7b9efa77). Independent byte-level verification, all recomputable: "
    "(1) PATCH CONTENT: 6 files, all under hooks-gt/ — the _shared closure header line and 5 "
    "member manifests. The ONLY semantic change is in the plugins/_shared source the gt copy "
    "is published from (l.1714-1718): add \"search\", \"git_read\" to _READ_PATH_TOOLS after "
    "\"request_scope\", comment citing #1361. Diff vs origin/main is exactly that addition "
    "(the anchor line gains a comma); nothing else. "
    "(2) HASH HONESTY recomputed with the repo's own tools/hooks_gt.py (canonical digest = "
    "sha256 with the hestia-gt-sha256 header value zeroed): origin/main gt closure canonical "
    "== f32a4241, the patch's asserted OLD (scheme sanity passes); wt-1361 gt closure "
    "canonical == 86d76646, the patch's asserted NEW. hooks_gt.build(wt-1361) regenerates ALL "
    "FIVE manifests with gt_versions byte-identical to the patch's post-images (_shared "
    "f22f6cb7, claude-code d83e8d84, codex cce9aace, gemini aa885914, kimi 96637cb1) — and "
    "gt_version content-addresses the whole manifest, so no other governed file in the tree "
    "differs: the patch is the complete, honest post-image. Redundancy check passes: wt gt "
    "copy minus header == wt plugins copy. "
    "(3) THE SEMANTIC CHANGE IS THE #1361 REMEDY — the exact classifier gap behind today's "
    "repeated being-search false denials (my dissents on 3d9d2dba2aa1e16e, 3270a69531272104, "
    "8c836a4702568e7f). Both added verbs verified read-only by construction in SAGE "
    "sage/gateway/being_gate_client.py: search composes a fixed git-grep/grep argv, "
    "shlex-quoted, the dispatcher refusing judged/executed drift; git_read's GIT_OPS = "
    "(log, show, diff, status, blame, cat), the rev grammar excludes flags (the "
    "--upload-pack class is closed), path is realpath-pinned inside the being's own worktree, "
    "and whitespace is rejected so the judged string splits into exactly the argv that runs. "
    "(4) SCOPE: this concurrence binds only act_digest 7b9efa77 — a git apply in a disposable "
    "scratchpad worktree. It merges nothing to main (PR review gates that), deploys nothing "
    "(the install/release path gates that), and pre-approves no future act the reclassified "
    "verbs would permit; each is judged on its own. Marker history on this closure file: 7 "
    "opened, 7 operator-approved. Disclosure: I am an interested party — my dissents called "
    "for this fix — but every claim above is recomputable by running tools/hooks_gt.py "
    "against wt-1361 and origin/main. Peer evidence, not a ruling. "
    f"Operating law read as kimi-code, law_hash={law_hash}."
)

out = hm.rpc(h, "hestia_gate_escalation_corroborate", {
    "session_id": s,
    "escalation_id": "cf54d46850bcdfe0",
    "stance": "concur",
    "argument": ARGUMENT,
})
print(json.dumps(out, indent=1))
