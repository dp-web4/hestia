# Final digest-chain verification for escalation bd5857e71648dc11, using the
# worktree's own tools/hooks_gt.py primitives against the scratch-applied files.
import importlib.util, json, sys

WT = "/home/dp/ai-workspace/hestia/scratchpad/wt-1327-v3"
SCR = "/tmp/kimi-1327-verify"
spec = importlib.util.spec_from_file_location("hooks_gt", WT + "/tools/hooks_gt.py")
hg = importlib.util.module_from_spec(spec); spec.loader.exec_module(hg)

gt = open(SCR + "/hooks-gt/_shared/hestia_gate_core.py", "rb").read()
core = open(SCR + "/plugins/_shared/hestia_gate_core.py", "rb").read()
man = json.load(open(SCR + "/hooks-gt/_shared/manifest.json"))
claimed = next(f["sha256"] for f in man["files"] if f["path"] == "hestia_gate_core.py")

print("header_value(GT)        :", hg.header_value(gt))
print("canonical_digest(GT)    :", hg.canonical_digest(gt))
print("manifest claim          :", claimed)
print("canonical==manifest     :", hg.canonical_digest(gt) == claimed)
print("header==manifest        :", hg.header_value(gt) == claimed)
print("strip_header(GT)==core  :", hg.strip_header(gt) == core)

ok = True
for m in ("_shared", "claude-code", "codex", "gemini", "kimi"):
    body = json.load(open(f"{SCR}/hooks-gt/{m}/manifest.json"))
    recomputed = hg._version(body)
    match = recomputed == body["gt_version"]
    ok &= match
    eng = body.get("engine")
    eng_note = ""
    if eng:
        eng_core = next(f["sha256"] for f in eng["files"] if f["path"] == "hestia_gate_core.py")
        eng_note = f" engine_pin={eng['gt_version'][:12]} eng_core={eng_core[:12]}"
    print(f"gt_version[{m:11s}] recompute-match: {match}  v={body['gt_version'][:12]}{eng_note}")
shared_v = man["gt_version"]
for m in ("claude-code", "codex", "gemini", "kimi"):
    body = json.load(open(f"{SCR}/hooks-gt/{m}/manifest.json"))
    pin_ok = body["engine"]["gt_version"] == shared_v
    core_ok = next(f["sha256"] for f in body["engine"]["files"] if f["path"] == "hestia_gate_core.py") == claimed
    ok &= pin_ok and core_ok
    print(f"{m:11s} engine pins shared {shared_v[:12]}: {pin_ok}; engine core == claimed: {core_ok}")
print("ALL_DIGEST_CHECKS:", "PASS" if ok and hg.canonical_digest(gt) == claimed and hg.strip_header(gt) == core else "FAIL")
