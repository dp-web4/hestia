#!/usr/bin/env python3
"""Verify escalation cf54d46850bcdfe0 (claude-code git apply of gt-1361.patch in wt-1361).

Checks, read-only:
1. diff origin/main plugins/_shared closure vs wt-1361 copy -- expect ONLY the
   search/git_read addition.
2. Recompute canonical digests per tools/hooks_gt.py (sha256 with header value zeroed):
   - origin/main gt closure must equal f32a4241... (sanity: scheme understood)
   - wt-1361 gt closure must equal the patch's asserted 86d76646...
3. Rebuild the whole GT tree from wt-1361 via hooks_gt.build() and compare every
   manifest gt_version + closure sha256 against the patch's asserted post-images.
4. Confirm wt-1361 hooks-gt copy minus header == wt-1361 plugins copy (redundancy).
"""
import difflib
import hashlib
import importlib.util
import json
import subprocess
import sys

WT = "/tmp/claude-1000/-home-dp-ai-workspace/9261dc9a-1703-4964-9e72-a076bd468aca/scratchpad/wt-1361"
REPO = "/home/dp/ai-workspace/hestia"
PATCH_NEW_CLOSURE = "86d7664624946f36d77935168ac82dcfc8ee5bd5bf025cbe7ed1f4ce31dd5fc1"
PATCH_OLD_CLOSURE = "f32a4241f27f3f89f7d7391d9c02bbe1e1965c0d876c0ffd03377abb6e58687e"
PATCH_GT_VERSIONS = {
    "_shared": "f22f6cb765fc43a0e33224a99dc5e42bd5da33032335504c8c684ca80e7f09d1",
    "claude-code": "d83e8d84654ec6ee30ef3d6275ab821f67ba07fd855f7a420a9f5f12ae221c06",
    "codex": "cce9aace5e851b05f8e7909076258e38b6e1a7f8d30941a957f37ca334e22d30",
    "gemini": "aa88591430eeec75969186687d2b52169cf40b3d9b03ea2b351648027eb80e37",
    "kimi": "96637cb1a5216fce682c471801ac3a17e2c50c9c7e9f6a416f097bf017c62ced",
}

spec = importlib.util.spec_from_file_location("hooks_gt", f"{REPO}/tools/hooks_gt.py")
gt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gt)

fails = []

def check(name, ok, detail=""):
    print(f"[{'OK' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        fails.append(name)

main_plugins = subprocess.run(
    ["git", "-C", REPO, "show", "origin/main:plugins/_shared/hestia_governance_closure.py"],
    capture_output=True, check=True).stdout
wt_plugins = open(f"{WT}/plugins/_shared/hestia_governance_closure.py", "rb").read()
wt_gt = open(f"{WT}/hooks-gt/_shared/hestia_governance_closure.py", "rb").read()
main_gt = subprocess.run(
    ["git", "-C", REPO, "show", "origin/main:hooks-gt/_shared/hestia_governance_closure.py"],
    capture_output=True, check=True).stdout

# 1. diff main vs wt plugins copy
diff = list(difflib.unified_diff(
    main_plugins.decode().splitlines(), wt_plugins.decode().splitlines(), lineterm=""))
adds = [l for l in diff if l.startswith("+") and not l.startswith("+++")]
dels = [l for l in diff if l.startswith("-") and not l.startswith("---")]
print("== diff main -> wt plugins/_shared closure ==")
print("\n".join(diff))
check("diff is purely additive", len(dels) == 0, f"added={len(adds)} deleted={len(dels)}")
check("addition is the search/git_read block",
      any('"search", "git_read"' in l for l in adds) and len(adds) <= 6,
      f"added lines: {adds}")

# 2. canonical digests
check("main gt closure canonical == patch OLD", gt.canonical_digest(main_gt) == PATCH_OLD_CLOSURE,
      gt.canonical_digest(main_gt)[:16])
check("wt gt closure canonical == patch NEW", gt.canonical_digest(wt_gt) == PATCH_NEW_CLOSURE,
      gt.canonical_digest(wt_gt)[:16])

# 3. rebuild GT tree from wt, compare manifests to patch post-image
from pathlib import Path
tree = gt.build(Path(WT))
ok_all = True
for unit, want_ver in PATCH_GT_VERSIONS.items():
    body = json.loads(tree[f"hooks-gt/{unit}/manifest.json"].decode())
    got_ver = body.get("gt_version")
    rows = {r["path"]: r["sha256"] for r in body.get("files", [])}
    eng = body.get("engine") or {}
    eng_files = {r["path"]: r["sha256"] for r in eng.get("files", [])}
    closure_sha = rows.get("hestia_governance_closure.py") or eng_files.get("hestia_governance_closure.py")
    ok = got_ver == want_ver
    if closure_sha is not None:
        ok = ok and closure_sha == PATCH_NEW_CLOSURE
    print(f"  unit {unit}: gt_version {str(got_ver)[:12]} (want {want_ver[:12]}) closure {str(closure_sha)[:12]}")
    ok_all = ok_all and ok
check("rebuilt manifests match patch post-image", ok_all)
hdr = [l for l in tree["hooks-gt/_shared/hestia_governance_closure.py"].decode().splitlines()
       if "hestia-gt-sha256:" in l]
check("rebuilt gt header carries patch NEW hash", hdr and PATCH_NEW_CLOSURE in hdr[0], hdr[:1])

# 4. redundancy: gt copy minus header == plugins copy
check("wt gt copy strip_header == wt plugins copy", gt.strip_header(wt_gt) == wt_plugins)

print("\nRESULT:", "ALL OK" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
