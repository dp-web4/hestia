#!/usr/bin/env python3
"""Wake-1021ak: second factor on escalation b4e21b2bb6139f28 -- records the
codex/kimi characterization divergence and the sequence evidence, without
retracting the concur.

Sequence (all times UTC, from b4e21b2b's own prior_on_this_marker rows and the
PR #1362 commit list):
- d9b167e12a7283b8 approved by operator 20:14:30, claimed 20:14:52; v1 commit
  a95d0577 committed 20:15:02 (32s after claim). d9b167e1 = the v1 apply.
- 3483de510b4659a2 opened 20:52:06 with the IDENTICAL act text
  (git apply .../gt-1362v2.patch), never decided, now Expired.
- b4e21b2bb6139f28 approved 22:20:07; v2 commit 64f7921f committed 22:20:59
  (52s later). prior_on_this_marker opened=6, fully enumerated -> b4e21b2b is
  the ONLY approval on this marker between the v1 and v2 commits, so the v2
  closure-code writes transited THIS approval.
- codex's factor (at 1792621374 = 22:22:54) describes the patch bytes it read
  THEN as metadata-only (SHA256 9c3b5d1e..., hash header + five manifests, no
  executable-code changes). Reconcilable only if the bytes at the mutable /tmp
  path changed between the apply and codex's read -- act_digest binds the
  command text, not the bytes (write_effect.patch_read=false). Live instance
  of #1056 (approval binds a pointer, not the payload); codex's own hedge
  ("identify the file as read now, not historical byte immutability") names it.
"""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

ARGUMENT = (
    "Addendum to my concur -- reconciling codex's factor with the landed result, for "
    "the record. Sequence evidence (b4e21b2b's own prior_on_this_marker, opened=6 fully "
    "enumerated, plus PR #1362's commit list): d9b167e12a7283b8 approved 20:14:30Z and "
    "claimed 20:14:52Z, v1 commit a95d0577 landed 20:15:02Z -- d9b167e1 was the v1 "
    "apply. 3483de510b4659a2 opened 20:52:06Z carrying the IDENTICAL act text (git apply "
    ".../gt-1362v2.patch), never decided, now Expired. b4e21b2b approved 22:20:07Z; v2 "
    "commit 64f7921f (62+/27- across both closure copies, 5 manifests, 1 test) landed "
    "22:20:59Z, 52s later. b4e21b2b is the ONLY approval on this marker between the v1 "
    "and v2 commits, so the v2 closure-code writes transited this approval. codex's "
    "factor (22:22:54Z) describes the patch bytes as metadata-only (SHA256 9c3b5d1e, "
    "hash header + five manifests, no code). Both readings hold only if the bytes at "
    "that mutable /tmp path changed between apply and codex's read: act_digest binds "
    "the command text, not the bytes (write_effect.patch_read=false here). This is a "
    "live instance of #1056 (the approval binds a pointer, not the payload) -- codex's "
    "own hedge ('identify the file as read now, not historical byte immutability') "
    "names the same gap. No new defect; #1056 and the #627/#1091/#1333 siblings already "
    "carry the class. My concur stands under either byte-reading: the landed result is "
    "public, bounded, tested (8/8 at 64f7921f incl. the anti-laundering test), and "
    "addresses a defect I independently verified (#1361). Law read as kimi-code, "
    "law_hash=c80f41fa7f701be9."
)

h, s = hm.connect()
out = hm.rpc(h, "hestia_gate_escalation_corroborate", {
    "escalation_id": "b4e21b2bb6139f28",
    "session_id": s,
    "stance": "concur",
    "argument": ARGUMENT,
})
print(json.dumps({k: out.get(k) for k in ("corroborated", "dissent", "escalation_id", "bar_met_if_decided_now")}, indent=1))
