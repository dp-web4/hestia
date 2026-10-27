#!/usr/bin/env python3
"""Witness for escalation c9f1ec190767fadd review (notice 33516).

Read-only against the shared tree and the s1411w worktree. Verifies:
  A. held patch digest matches its filename (the escalated act names that digest);
  B. the operator-approved commit 97a6a1b3 applies exactly the held patch
     (per-file hunk equality, header noise stripped);
  C. hooks-gt hash claims recompute from the committed bytes.
Writes only to /tmp (scratch exports for the dynamic test runs, done separately).
"""
import hashlib
import re
import subprocess
import sys

WT = "/home/dp/ai-workspace/hestia/scratchpad/s1411w"
HELD = "held/2f103a283ec949792ce277245693e244a929edfe69dd20e4efe13694e7a7f248.patch"
BASE = "ce40a647"
TIP = "97a6a1b3"

FILES = [
    "plugins/_shared/hestia_gate_core.py",
    "hooks-gt/_shared/hestia_gate_core.py",
    "hooks-gt/_shared/manifest.json",
    "hooks-gt/claude-code/manifest.json",
    "hooks-gt/codex/manifest.json",
    "hooks-gt/gemini/manifest.json",
    "hooks-gt/kimi/manifest.json",
]


def run(*args):
    return subprocess.run(args, cwd=WT, capture_output=True, text=True).stdout


def normalize(diff_text):
    out = []
    for line in diff_text.splitlines():
        if line.startswith("index "):
            continue
        line = re.sub(r"^(@@ [^@]* @@).*", r"\1", line)
        if line.strip():
            out.append(line)
    return out


def main():
    fails = []

    # A. digest == filename
    raw = open(f"{WT}/{HELD}", "rb").read()
    digest = hashlib.sha256(raw).hexdigest()
    named = HELD.split("/")[-1].split(".")[0]
    print(f"A. held patch sha256 {digest[:12]}… == filename {named[:12]}…: "
          f"{'OK' if digest == named else 'FAIL'}")
    if digest != named:
        fails.append("A")

    patch_text = raw.decode()
    sections = {}
    for sec in patch_text.split("diff --git ")[1:]:
        m = re.match(r"a/(\S+) b/(\S+)", sec)
        if m:
            sections[m.group(1)] = "diff --git " + sec

    # B. committed hunks == held patch hunks, per file
    for f in FILES:
        committed = run("git", "diff", BASE, TIP, "--", f)
        held = sections.get(f, "")
        if not held:
            print(f"B. {f}: FAIL (absent from held patch)")
            fails.append(f"B:{f}")
            continue
        ok = normalize(committed) == normalize(held)
        print(f"B. {f}: {'MATCH' if ok else 'MISMATCH'}")
        if not ok:
            fails.append(f"B:{f}")

    # C. hashes at TIP recompute
    core = run("git", "show", f"{TIP}:hooks-gt/_shared/hestia_gate_core.py")
    h = hashlib.sha256(core.encode()).hexdigest()
    claimed = "83fdf6605c87f540d6bc246cc599487325ef1c741e9a5a6a4b615c57e733738d"
    print(f"C1. hooks-gt core sha256 at {TIP[:8]}: {h[:12]}… "
          f"{'OK' if h == claimed else f'FAIL (claimed {claimed[:12]}…)'}")
    if h != claimed:
        fails.append("C1")

    # header line inside the hooks-gt copy must name the same digest
    head = core.splitlines()[1]
    ok = claimed in head
    print(f"C2. hooks-gt core header names manifest digest: {'OK' if ok else 'FAIL: ' + head}")
    if not ok:
        fails.append("C2")

    # hooks-gt copy == plugins copy + exactly one header line
    plug = run("git", "show", f"{TIP}:plugins/_shared/hestia_gate_core.py")
    # strip shebang+header from hooks-gt copy, shebang from plugins copy
    stripped = "\n".join(core.split("\n")[2:])
    plug_stripped = "\n".join(plug.split("\n")[1:])
    ok = stripped == plug_stripped
    print(f"C3. hooks-gt copy == plugins copy after shebang+header strip: {'OK' if ok else 'FAIL'}")
    if not ok:
        fails.append("C3")

    # gt_version: sha256 over the manifest's own files list, per repo convention.
    # Convention check: recompute as sha256 of concatenated "path:sha256" lines? Try the
    # manifest's stated rule empirically against the PRE-patch manifest first.
    print("C4. gt_version recompute: deferred to hooks_gt.check (separate step)")

    print("VERDICT:", "FAIL " + ",".join(fails) if fails else "ALL STATIC CHECKS PASS")


if __name__ == "__main__":
    sys.exit(main())
