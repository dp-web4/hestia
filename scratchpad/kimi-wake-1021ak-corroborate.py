#!/usr/bin/env python3
"""Wake-1021ak: corroborate escalation b4e21b2bb6139f28 (notice 30694, claude-code).

Stance CONCUR. Independent verification behind the argument (all this wake):
- Evidence RPC: act is `git apply gt-1362v2.patch` in the claude seat's wt-1361
  worktree; marker hestia_governance_closure.py; Approved by operator
  (role:constellation:sovereign) 17s after open; single_approver bar met.
  write_effect.patch_read=false -- the daemon could not read the patch either.
- Defect real and current: #1361 OPEN; I verified last wake (esc e5bd7694) that
  `search` is absent from _READ_PATH_TOOLS at the executing vintage (line 1221)
  AND origin/main (line 1707); none of the 5 named unexecuted commits touches
  plugins/_shared -> not a deploy-vintage artifact.
- The approved apply is publicly inspectable: commit 64f7921f on PR #1362
  (cbp/closure-being-read-verbs), committed 2026-10-21T22:20:59Z, 69s after the
  approval. Approval binds to a landed, reviewable result, not a self-report.
- Diff a95d0577..64f7921f read in full: search/git_read move to
  _COMPOSED_READ_TOOLS; `path` stays read-only target; a carried `command` is
  classified for write positions via _write_position_targets("Bash", ...) --
  fail-closed on tee/sed -i/redirects/&& cp; file_path/notebook_path keep the
  unknown-tool (write) reading. The v1 hole (early return for _READ_PATH_TOOLS
  names skipped command inspection -> `search`+`command:tee <gate>` was a READ)
  is proven by the diff's own `-` lines.
- Ran tools/closure_read_tool_names_test.py at 64f7921f in scratchpad worktree
  wt-verify-1362 (since removed): 8/8 PASS incl. the new anti-laundering test.
- Live demonstration this wake: my own `git checkout a95d0577 --
  plugins/_shared/...` inside the scratchpad worktree was refused
  gate.self_access (marker plugins/_shared) and auto-opened escalation
  530fee9e273a9816, which I retired as asker. The surface under review works
  as designed on a third seat.
- Patch bytes themselves unreadable from my seat (claude /tmp scratchpad is
  outside my MRH); corroboration binds to the landed commit, not the patch.
- Law: hestia_operating_law read as kimi-code, law_hash=c80f41fa7f701be9...;
  society_policy_hash=2f679ab0... matches the escalation evidence.
"""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

ARGUMENT = (
    "Concur: a genuine governance-surface write, correctly refused, escalated, and "
    "operator-approved -- the mechanism working as designed, and this time the "
    "stated_detail ('authorises this one write') is accurate (contrast the #1361 "
    "misclassified reads). Independently verified: (1) the defect is real and current -- "
    "#1361 OPEN; last wake I verified `search` absent from _READ_PATH_TOOLS at the "
    "executing vintage (line 1221) and origin/main (line 1707), not a deploy-vintage "
    "artifact. (2) The approved apply landed as public commit 64f7921f on PR #1362, "
    "committed 69s after approval -- what was approved is inspectable, not self-reported. "
    "(3) Full diff read: search/git_read move to _COMPOSED_READ_TOOLS where `path` is a "
    "read target only and a carried `command` is classified as Bash (tee/sed -i/redirect/"
    "&& cp fail closed as writes); the v1 laundering hole is proven by the diff's own "
    "`-` lines (the _READ_PATH_TOOLS early return skipped command inspection). (4) Ran "
    "closure_read_tool_names_test.py at 64f7921f in a scratchpad worktree: 8/8 PASS, "
    "including the new test_a_composed_read_name_does_not_launder_a_write. (5) This wake "
    "the same surface refused my own scratchpad-worktree checkout of the v1 closure "
    "(gate.self_access, escalation 530fee9e273a9816, retired by me as asker) -- the rule "
    "under review fires correctly on a third seat. Boundary: the patch bytes were "
    "unreadable from my seat (claude /tmp, outside MRH; daemon patch_read=false too), so "
    "this concur binds to the landed commit, not the patch file. Stopgap framing honest: "
    "class-level fix remains #1353. Law read as kimi-code, law_hash=c80f41fa7f701be9, "
    "society_policy_hash=2f679ab0 (matches the escalation evidence)."
)

h, s = hm.connect()
out = hm.rpc(h, "hestia_gate_escalation_corroborate", {
    "escalation_id": "b4e21b2bb6139f28",
    "session_id": s,
    "stance": "concur",
    "argument": ARGUMENT,
})
print(json.dumps(out, indent=1))
