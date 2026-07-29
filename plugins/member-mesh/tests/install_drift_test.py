#!/usr/bin/env python3
"""A merged fix that never reaches the hooks dir is not a fix, and the obvious sync breaks members.

WHAT HAPPENED (CBP, 2026-07-29). #108 deleted `hestia-mesh.py`'s `HESTIA_MESH_PLUGIN`
default (`"kimi-code"` — the D1 impersonation default itself) and #109 made the resulting
refusal audible in `session-mesh-inbox.sh`. Hours after #109 merged, all three deployed
copies on the box — `~/.claude/hooks/member-mesh`, `~/.kimi-code/hooks`, `~/.codex/hooks`
— still carried the pre-#108 CLI. Verified by content, not mtime: none contained the
guard string, none contained the DARK banner. The reason was not that someone forgot:
`plugins/member-mesh/` had no installer at all, while `plugins/gemini/` and
`plugins/agent-inventory/` both did. Merged-but-dark was the DEFAULT state.

THE SECOND HALF, WHICH IS THE ONE THIS FILE EXISTS FOR. The obvious remedy — copy the
files — breaks the member it is trying to fix. `~/.kimi-code/config.toml` wires the hook
with no `HESTIA_MESH_PLUGIN` at all. That member's id was correct only because the
deleted default happened to name it. Sync the files there and the CLI refuses (rc=2),
the hook prints DARK, and every session after it is dark until someone reads the banner.

So the pin is NOT, as the #109 review concluded, "a redundancy rather than the only
guard". Pre-sync the default is the only guard; post-sync the pin is the only guard.
They never both hold, so there is no moment at which either is redundant. The ordering
is load-bearing: config first, files second. An installer that lets an operator do it in
the other order has automated the outage.

Properties asserted:

  A. THE HAZARD IS REAL, not inferred from reading the diff. The same hook, same unset
     env, prints mail against a defaulting CLI and prints DARK against the merged one.
     That difference IS the outage, reproduced in a fixture.
  B. --check IS READ-ONLY. It is the half any member can run against its own deployment
     without operator standing, so it must not write — asserted by hashing the tree.
  C. SYNC REFUSES AN UNPINNED MEMBER, exits 2, and leaves the file byte-for-byte alone.
     A refusal that half-wrote would be worse than no installer.
  D. SYNC OF A PINNED MEMBER WORKS, is byte-exact, and keeps the previous copy — the
     deployed file is the only record of what the member was really running.
  E. --check EXITS 1 ON DRIFT AND ON UNPINNED, and 0 only when both are clean. An
     audit that cannot fail is the thing this whole class of bug is made of.

WHAT THE FIRST REAL RUN FOUND (kimi's review of this PR, notice 352, 2026-07-29). The
pin refusal above covers ONE variable, and one variable was not the question. kimi's
deployed hook carried an inline

    OUT=$(HESTIA_ROLE=role:constellation:interactive-dev python3 ... peek)

that the merged copy does not have. The sync dropped it and printed "synced". The
member kept its ID and lost its GRAIN — `hestia-mesh.py`'s own docstring says an absent
`HESTIA_ROLE` normalizes to `role:constellation:member`, a different member-shape than
the one whose acts were being judged. kimi caught it by reading the diff by hand; the
installer said nothing. So:

  F. THE SYNC MUST REFUSE WHAT IT WOULD SILENTLY TAKE AWAY. Any `HESTIA_*` the deployed
     hook assigns and the config command line does not is destroyed by the overwrite.
     Refuse it, name it, write nothing — the same shape as C, generalized off the single
     variable that happened to be noticed first. A guard covering one variable and silent
     about the rest is not a guard, it is a coincidence.
  G. A MEMBER WITH NO ROLE ANYWHERE IS REPORTED. Not a sync hazard — a standing one, and
     live on CBP today: `~/.codex/config.toml` pins `HESTIA_MESH_PLUGIN` and no role, and
     its deployed hook has none either, so codex has been connecting on the daemon's
     default grain the whole time. Nothing was going to say so, because "pinned" was
     printed as if it were the whole answer.
  H. A COMMENTED-OUT HOOK LINE IS NOT A PIN. The original pin check grepped the raw file,
     so a disabled config line read as "pinned" and unlocked the sync that darkens the
     member. Found by generalizing the check, not by anyone hitting it.

Hermetic: a fake HOME, a stub CLI, no daemon, no git, no network.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)                      # plugins/member-mesh
INSTALL = os.path.join(SRC, "install.sh")
INBOX_HOOK = os.path.join(SRC, "session-mesh-inbox.sh")
REAL_CLI = os.path.join(SRC, "hestia-mesh.py")

failures = []


def check(cond, label, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    if not cond:
        failures.append(label)


def tree_hash(root):
    """Hash every path + content under root, so any write at all shows up."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            p = os.path.join(dirpath, name)
            h.update(os.path.relpath(p, root).encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


def member_line(stdout, member):
    """The audit line for one member. Asserting against whole stdout is not enough: the
    trailer says 'DRIFT or UNPINNED member found', so a test looking for 'UNPINNED'
    anywhere passes on a drifted tree with every member pinned. Two of these assertions
    were written that way first and went green against the unfixed script."""
    for line in stdout.splitlines():
        if line.startswith("  ") and line.split()[0:1] == [member]:
            return line
    return ""


def run(args, home):
    return subprocess.run(
        ["sh", INSTALL] + args,
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )


# A stub CLI standing in for the PRE-#108 code: it defaults the member id instead of
# refusing. Written rather than pulled from git history so the test stays hermetic —
# what matters is the one behaviour (a default exists), not the exact old file.
DEFAULTING_CLI = '''#!/usr/bin/env python3
import json, os, sys
PLUGIN = os.environ.get("HESTIA_MESH_PLUGIN", "kimi-code")
print(json.dumps({"total": 1, "notices": [
    {"id": 1, "kind": "reply", "from_plugin": "codex", "pointer_uri": "x://p"}], "peeked": True}))
sys.exit(0)
'''


# A stale deployed hook that carries a member's own inline role — kimi's real pre-sync
# copy, reduced to the one line that matters. This is the edit the sync destroys.
INLINE_ROLE_LINE = (
    'OUT=$(HESTIA_ROLE=role:constellation:interactive-dev '
    'python3 "$(dirname "$0")/hestia-mesh.py" peek 2>/dev/null)\n'
)


def member_home(pin_claude=True, pin_kimi=False, stale=True,
                pin_role=True, inline_role=(), comment_out=()):
    """A fake HOME with claude-code + kimi-code installed; kimi unpinned like the real box.

    pin_role     — put HESTIA_ROLE on the config command line (the only place it survives)
    inline_role  — members whose DEPLOYED hook assigns HESTIA_ROLE itself (stale only)
    comment_out  — members whose config hook line is commented out rather than absent
    """
    home = tempfile.mkdtemp(prefix="mesh-install-home-")
    layout = {
        "claude-code": (os.path.join(home, ".claude", "hooks", "member-mesh"),
                        os.path.join(home, ".claude", "settings.json"), pin_claude),
        "kimi-code": (os.path.join(home, ".kimi-code", "hooks"),
                      os.path.join(home, ".kimi-code", "config.toml"), pin_kimi),
    }
    for member, (hooks, config, pinned) in layout.items():
        os.makedirs(hooks, exist_ok=True)
        for f in ("hestia-mesh.py", "session-mesh-inbox.sh"):
            dest = os.path.join(hooks, f)
            if stale:
                body = "#!/bin/sh\n# stale pre-#108 copy\n"
                if f == "session-mesh-inbox.sh" and member in inline_role:
                    body += INLINE_ROLE_LINE
                with open(dest, "w") as fh:
                    fh.write(body + "exit 0\n")
            else:
                shutil.copy(os.path.join(SRC, f), dest)
            os.chmod(dest, 0o755)
        pin = f"HESTIA_MESH_PLUGIN={member} " if pinned else ""
        role = "HESTIA_ROLE=role:constellation:interactive-dev " if pin_role else ""
        lead = "# " if member in comment_out else ""
        with open(config, "w") as fh:
            fh.write(f'{lead}command = "{pin}{role}{hooks}/session-mesh-inbox.sh"\n')
    return home, layout


print("A. the hazard reproduces in a fixture")
fix = tempfile.mkdtemp(prefix="mesh-hazard-")
shutil.copy(INBOX_HOOK, os.path.join(fix, "session-mesh-inbox.sh"))
with open(os.path.join(fix, "hestia-mesh.py"), "w") as fh:
    fh.write(DEFAULTING_CLI)
os.chmod(os.path.join(fix, "hestia-mesh.py"), 0o755)
env_unset = {k: v for k, v in os.environ.items() if k != "HESTIA_MESH_PLUGIN"}
before = subprocess.run(["sh", os.path.join(fix, "session-mesh-inbox.sh")],
                        capture_output=True, text=True, env=env_unset, timeout=60)
check(before.returncode == 0 and "DARK" not in before.stdout and "pending notice" in before.stdout,
      "A1. pre-#108 CLI + unset identity: mail shown, nothing says the id was guessed",
      repr(before.stdout))

shutil.copy(REAL_CLI, os.path.join(fix, "hestia-mesh.py"))
after = subprocess.run(["sh", os.path.join(fix, "session-mesh-inbox.sh")],
                       capture_output=True, text=True, env=env_unset, timeout=60)
check(after.returncode == 0 and "DARK" in after.stdout,
      "A2. merged CLI + same unset identity: the SAME member goes DARK — file-only sync is the outage",
      repr(after.stdout))
check("HESTIA_MESH_PLUGIN" in after.stdout,
      "A3. and the banner names the variable whose absence caused it", repr(after.stdout))

print("B. --check is read-only")
home, layout = member_home()
h0 = tree_hash(home)
p = run(["--check"], home)
check(tree_hash(home) == h0, "B1. --check wrote nothing to the deployment tree")
check(p.returncode == 1, f"B2. --check exits 1 on a drifted+unpinned tree (got {p.returncode})", p.stdout)
check("DRIFT" in p.stdout, "B3. --check names the drift", p.stdout)
check("UNPINNED" in p.stdout, "B4. --check names the unpinned member", p.stdout)

print("C. sync refuses an unpinned member without writing")
kimi_hook = os.path.join(layout["kimi-code"][0], "session-mesh-inbox.sh")
with open(kimi_hook, "rb") as fh:
    kimi_before = fh.read()
p = run(["kimi-code"], home)
check(p.returncode == 2, f"C1. sync of an unpinned member exits 2 (got {p.returncode})", p.stdout)
check("REFUSED" in p.stdout, "C2. and says so", p.stdout)
with open(kimi_hook, "rb") as fh:
    check(fh.read() == kimi_before, "C3. the refused member's file is byte-for-byte untouched")
check(not os.path.exists(kimi_hook + ".pre-sync.bak"),
      "C4. a refusal leaves no half-done backup behind")

print("D. sync of a pinned member is byte-exact and keeps the old copy")
p = run(["claude-code"], home)
check(p.returncode == 0, f"D1. sync of a pinned member succeeds (got {p.returncode})", p.stdout)
for f in ("hestia-mesh.py", "session-mesh-inbox.sh"):
    dep = os.path.join(layout["claude-code"][0], f)
    with open(dep, "rb") as a, open(os.path.join(SRC, f), "rb") as b:
        check(a.read() == b.read(), f"D2. {f} now byte-identical to the repo")
    check(os.path.exists(dep + ".pre-sync.bak"), f"D3. {f} previous copy preserved")

print("E. --check passes only when everything is current and pinned")
clean, _ = member_home(pin_kimi=True, stale=False)
p = run(["--check"], clean)
check(p.returncode == 0, f"E1. clean+pinned tree exits 0 (got {p.returncode})", p.stdout)
drifted, _ = member_home(pin_kimi=True, stale=True)
p = run(["--check"], drifted)
check(p.returncode == 1, f"E2. pinned but drifted still exits 1 (got {p.returncode})", p.stdout)
unpinned, _ = member_home(pin_kimi=False, stale=False)
p = run(["--check"], unpinned)
check(p.returncode == 1, f"E3. current but unpinned still exits 1 — the hazard is latent, not absent",
      p.stdout)

print("F. sync refuses to silently take away what only the deployed copy carries")
lossy, llay = member_home(pin_kimi=True, pin_role=False, inline_role=("kimi-code",))
kimi_hook = os.path.join(llay["kimi-code"][0], "session-mesh-inbox.sh")
with open(kimi_hook, "rb") as fh:
    lossy_before = fh.read()
p = run(["kimi-code"], lossy)
check(p.returncode == 2, f"F1. sync exits 2 when the overwrite would drop a variable (got {p.returncode})",
      p.stdout)
check("HESTIA_ROLE" in p.stdout,
      "F2. and NAMES the variable — kimi had to read the diff by hand to find it", p.stdout)
with open(kimi_hook, "rb") as fh:
    check(fh.read() == lossy_before, "F3. the refused member's hook is byte-for-byte untouched")
check(not os.path.exists(kimi_hook + ".pre-sync.bak"),
      "F4. and no half-done backup was left behind")
p = run(["--check"], lossy)
check("HESTIA_ROLE" in member_line(p.stdout, "kimi-code"),
      "F5. --check names the pending loss on that member's own line, before anyone syncs",
      repr(member_line(p.stdout, "kimi-code")))

# The negative control: the SAME inline assignment is harmless once the config also
# carries it, because then the overwrite takes nothing away. The refusal is about LOSS,
# not about the mere presence of a hand edit — otherwise it would just block every sync.
kept, klay = member_home(pin_kimi=True, pin_role=True, inline_role=("kimi-code",))
p = run(["kimi-code"], kept)
check(p.returncode == 0,
      f"F6. same inline assignment, but pinned in the config too: sync proceeds (got {p.returncode})",
      p.stdout)
with open(os.path.join(klay["kimi-code"][0], "session-mesh-inbox.sh"), "rb") as a, \
        open(os.path.join(SRC, "session-mesh-inbox.sh"), "rb") as b:
    check(a.read() == b.read(), "F7. and lands byte-identical to the repo")

print("G. a member with no role anywhere is reported, not passed as 'pinned'")
noroleh, _ = member_home(pin_claude=True, pin_kimi=True, stale=False, pin_role=False)
p = run(["--check"], noroleh)
check(p.returncode == 1,
      f"G1. current + pinned but roleless still exits 1 — the grain is off (got {p.returncode})", p.stdout)
check("NO-ROLE" in member_line(p.stdout, "kimi-code"),
      "G2. and says it on the roleless member's own line, not as a tree-wide trailer",
      repr(member_line(p.stdout, "kimi-code")))
withrole, _ = member_home(pin_claude=True, pin_kimi=True, stale=False, pin_role=True)
p = run(["--check"], withrole)
check(p.returncode == 0, f"G3. and a fully declared tree is still clean (got {p.returncode})", p.stdout)

print("H. a commented-out hook line is not a pin")
commented, clay = member_home(pin_kimi=True, comment_out=("kimi-code",))
p = run(["--check"], commented)
check("UNPINNED" in member_line(p.stdout, "kimi-code"),
      "H1. a disabled config line reads as UNPINNED on that member's line, not as a pin",
      repr(member_line(p.stdout, "kimi-code")))
kimi_hook = os.path.join(clay["kimi-code"][0], "session-mesh-inbox.sh")
with open(kimi_hook, "rb") as fh:
    commented_before = fh.read()
p = run(["kimi-code"], commented)
check(p.returncode == 2,
      f"H2. and sync refuses it rather than syncing on a pin nothing executes (got {p.returncode})",
      p.stdout)
with open(kimi_hook, "rb") as fh:
    check(fh.read() == commented_before, "H3. leaving the file untouched")

for d in (fix, home, clean, drifted, unpinned, lossy, kept, noroleh, withrole, commented):
    shutil.rmtree(d, ignore_errors=True)

print()
if failures:
    print(f"failures={len(failures)}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all member-mesh install/drift checks pass")
