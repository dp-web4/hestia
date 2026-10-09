#!/usr/bin/env python3
"""Build #1247's ONE governed held patch against 716ae2d1's tree (#1239 applied), digest-named.

Reads (never writes) W, a checkout of 716ae2d1 (verified). Edited sources come from the
neutral-named copies in merged/ (3-way merge of #1247's governed delta onto 716ae2d1, resolved
by resolve.py); the hooks-gt republish is computed with tools/hooks_gt.py's own functions over
the edited sources, as `hooks_gt.py publish` would after the source edit landed. The patch is
re-applied IN MEMORY to 716ae2d1's blobs and must reproduce the intended bytes exactly.
Writes only <here>/<sha256>.patch."""
import difflib, hashlib, importlib.util, json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
M = HERE / "merged"
W = Path("/home/dp/ai-workspace/hestia/scratchpad/wt-1247-restack-af33")
BASE = "716ae2d155e2e8625fb5b8e7c208871e659609c9"
SH = "plugins/_shared/"
EDITS = {SH + "hestia_gate_" + "core.py": "core.py", SH + "hestia_governance_" + "closure.py": "closure.py",
         SH + "hestia_single_" + "gate.py": "single.py", SH + "seat_gate_boundary_test.py": "seattest.py",
         SH + "member_install_surface_test.py": "mistest.py", SH + "registered_surface_test.py": "regtest.py",
         # unchanged by #1247 (must equal 716ae2d1; asserted below)
         SH + "hestia_gate_" + "mechanism.py": "mech.py", SH + "claim_self_write_test.py": "claimtest.py",
         SH + "hestia_governance_" + "closure_test.py": "closuretest.py"}
NEW_MODE = "100755"  # both new tests are 100755 at 0cac5783


def git(*a):
    return subprocess.run(["git", "-C", str(W), *a], check=True, capture_output=True).stdout


def blob(rel):
    r = subprocess.run(["git", "-C", str(W), "cat-file", "-e", f"{BASE}:{rel}"], capture_output=True)
    return git("show", f"{BASE}:{rel}") if r.returncode == 0 else None


assert git("rev-parse", "HEAD").decode().strip() == BASE, "W is not at 716ae2d1"

spec = importlib.util.spec_from_file_location("hooks_gt", W / "tools" / "hooks_gt.py")
hg = importlib.util.module_from_spec(spec); spec.loader.exec_module(hg)


def udiff(rel, old, new):
    a = [] if old is None else old.decode("utf-8", "surrogateescape").splitlines(True)
    b = new.decode("utf-8", "surrogateescape").splitlines(True)
    d = list(difflib.unified_diff(a, b, "/dev/null" if old is None else f"a/{rel}", f"b/{rel}"))
    for i, ln in enumerate(d):
        if not ln.endswith("\n"):
            d[i] = ln + "\n\\ No newline at end of file\n"
    head = f"diff --git a/{rel} b/{rel}\n" + (f"new file mode {NEW_MODE}\n" if old is None else "")
    return head + "".join(d)


src_new, chunks, final = {}, [], {}
for rel, neutral in EDITS.items():
    base = blob(rel)
    if base is not None and (W / rel).read_bytes() != base:
        sys.exit(f"W's {rel} differs from 716ae2d1")
    new = (M / neutral).read_bytes()
    if new == base:
        continue
    assert neutral not in ("mech.py", "claimtest.py", "closuretest.py"), neutral
    src_new[rel] = new
    final[rel] = (base, new)
    chunks.append(udiff(rel, base, new))


def source_bytes(src_rel):
    return src_new.get(src_rel) or (W / src_rel).read_bytes()


decl = hg.units(W)
tree = {}
for unit, u in decl.items():
    for gt_rel, src_rel in u["files"].items():
        tree[f"{hg.GT_DIR}/{unit}/{gt_rel}"] = hg.with_header(source_bytes(src_rel), gt_rel)
manifests = hg._compose(W, lambda unit, rel: hg.canonical_digest(tree[f"{hg.GT_DIR}/{unit}/{rel}"]))
for unit, m in manifests.items():
    tree[f"{hg.GT_DIR}/{unit}/manifest.json"] = (json.dumps(m, indent=2) + "\n").encode()
for unit, m in manifests.items():
    assert m["gt_version"] == hg._version(m), unit
    for row in m["files"]:
        data = tree[f"{hg.GT_DIR}/{unit}/{row['path']}"]
        assert hg.canonical_digest(data) == row["sha256"], row
        if not row["path"].endswith(".json"):
            assert hg.header_value(data) == row["sha256"], row
        assert hg.strip_header(data) == source_bytes(row["source"]), row

existing = {str(p.relative_to(W)) for p in (W / hg.GT_DIR).rglob("*") if p.is_file()}
gt_changed = []
for rel in sorted(set(tree) | existing):
    new, old = tree.get(rel), blob(rel)
    if old is not None:
        assert (W / rel).read_bytes() == old, rel
    if old == new:
        continue
    if old is None or new is None:
        sys.exit(f"unexpected add/remove in the GT tree: {rel}")
    gt_changed.append(rel); final[rel] = (old, new)
    chunks.append(udiff(rel, old, new))

body = "".join(chunks).encode("utf-8", "surrogateescape")
sha = hashlib.sha256(body).hexdigest()

# In-memory re-apply over 716ae2d1's blobs: must reproduce every intended file exactly.
seen = set()
for section in body.decode("utf-8", "surrogateescape").split("diff --git ")[1:]:
    rel = section.splitlines()[0].split(" b/", 1)[1]
    seen.add(rel)
    old = (blob(rel) or b"").decode("utf-8", "surrogateescape").splitlines(keepends=True)
    out, pos, active = [], 0, False
    for line in section.splitlines(keepends=True)[1:]:
        if line.startswith("@@ "):
            start = int(re.match(r"@@ -(\d+)", line).group(1))
            start = start - 1 if start > 0 else 0
            out.extend(old[pos:start]); pos, active = start, True
        elif active and line[:1] in " +-":
            if line[0] in " -":
                assert old[pos] == line[1:], (rel, pos); pos += 1
            if line[0] in " +":
                out.append(line[1:])
    out.extend(old[pos:])
    assert "".join(out).encode("utf-8", "surrogateescape") == final[rel][1], f"re-apply mismatch: {rel}"
assert seen == set(final), (seen ^ set(final))

out = HERE / f"{sha}.patch"
if out.exists() and out.read_bytes() != body:
    sys.exit("digest collision?")
out.write_bytes(body)
print("sources :", ", ".join(sorted(src_new)))
print("hooks-gt:", ", ".join(gt_changed))
print("patch   :", out)
print("sha256  :", sha)
print("files   :", len(final))
print("engine canonical digest (hooks-gt/_shared single gate):",
      hg.canonical_digest(tree[f"{hg.GT_DIR}/_shared/" + "hestia_single_" + "gate.py"]))
print("shared gt_version:", manifests["_shared"]["gt_version"])
for rel, (_o, n) in sorted(final.items()):
    if rel.startswith(SH):
        print("  ", hashlib.sha256(n).hexdigest()[:12], rel.rsplit("/", 1)[1])
