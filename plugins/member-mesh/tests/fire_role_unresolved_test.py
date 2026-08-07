#!/usr/bin/env python3
"""The fire scripts must SAY when they could not resolve the member's role.

Why this test exists (CBP, 2026-08-05, notice 936/939 thread with kimi-code).

`fire-*.sh` resolves `HESTIA_ROLE` from the member's own identity file so a
mesh-fired autonomous session records its acts on the right trust grain. When the
file is unreadable the block falls through silently, and its comment justified the
silence: "it just leaves that member's split visible, which is the honest state."

That was true when it was written. It stopped being true on 2026-08-03, when
`~/.claude/settings.json` grew
`HESTIA_ROLE="${HESTIA_ROLE:-role:constellation:interactive-dev}"` on the hestia
hook registrations. After that the unresolved case is not blank — it is PAINTED as
an attended interactive session. Two changes, each defensible alone; together they
convert a visible gap into a silent misattribution.

And the gap was real, not hypothetical. On CBP the `claude-code` plugin ships no
`instance/identity.seed.json` and no `hooks/hydrate.sh` (codex, gemini and kimi all
ship both), so nothing in the tree ever wrote `~/.claude/hestia-instance/
identity.json`. `/home/dp/.claude/hestia-instance/` does not exist; this session's
environment carries `HESTIA_MESH_PLUGIN` and `HESTIA_MESH_HOST_AGENT` but no
`HESTIA_ROLE`. The resolution branch has never once fired for claude-code, and
every mesh-fired session on that box was recorded as `interactive-dev`.

Four cases per script, and cases B/C are what make case A worth anything — a
warning that fires unconditionally is noise, and a warning from a branch that can
never resolve proves the branch is broken rather than the environment is:

  A  no identity file            -> WARNS, and the CLI sees no role
  B  identity file with a role   -> silent, and the CLI sees THAT role  (positive control)
  C  HESTIA_ROLE already set     -> silent, and the preset is not clobbered
  D  identity file, role missing -> WARNS (readable is not resolved)

Usage: ./fire_role_unresolved_test.py        (runtime ~5s)
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.abspath(os.path.join(HERE, ".."))

# (fire script, stub CLI name, identity dir under $HOME, a sender the script accepts)
MEMBERS = (
    ("fire-claude.sh", "claude", ".claude/hestia-instance", "kimi-code"),
    ("fire-kimi.sh", "kimi", ".kimi-code/hestia-instance", "claude-code"),
    ("fire-codex.sh", "codex", ".codex/hestia-instance", "claude-code"),
)

WARNING = "role unresolved"

PRIMER = """{"notices": [{"id": 1, "kind": "reply", "from_plugin": "%s",
 "to_plugin": "x", "pointer_uri": "shared-context/x.md",
 "queued_at": "2026-08-05T00:00:00Z"}], "unanswered": {}}"""

failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


def fire(script, stub, sender, *, identity=None, preset_role=None):
    """Run the real fire script with a stubbed CLI and a stubbed $HOME.

    Returns (stdout, role_the_CLI_saw). `role_seen` is None when the stub ran with
    no HESTIA_ROLE in its environment, which is the observable that actually
    matters — the hooks read the variable, not the script's intent.
    """
    tmp = tempfile.mkdtemp(prefix="fire-role-test-")
    seen = os.path.join(tmp, "role-seen")
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir)
    with open(os.path.join(bindir, stub), "w") as f:
        # `-` for unset is distinguishable from "" for set-but-empty; the difference
        # decides whether the daemon defaults the grain or takes a declaration.
        f.write('#!/usr/bin/env bash\n'
                f'printf %s "${{HESTIA_ROLE-<unset>}}" > "{seen}"\n'
                # The BASIS travels beside the role and is asserted separately: a
                # provisional declaration without a recorded basis is indistinguishable
                # from a hydrated one, and that indistinguishability is the whole defect.
                f'printf %s "${{HESTIA_ROLE_BASIS-<unset>}}" > "{seen}.basis"\n'
                'exit 0\n')
    os.chmod(os.path.join(bindir, stub), 0o755)

    if identity is not None:
        idir = os.path.join(tmp, os.path.dirname(identity[0]))
        os.makedirs(idir, exist_ok=True)
        with open(os.path.join(tmp, identity[0]), "w") as f:
            json.dump(identity[1], f)

    src = os.path.join(tmp, "notice-test.json")
    with open(src, "w") as f:
        f.write(PRIMER % sender)

    env = dict(os.environ)
    env["HOME"] = tmp
    env["HESTIA_MESH_LOCK_DIR"] = os.path.join(tmp, "locks")
    env["HESTIA_FIRE_LOCK_WAIT"] = "10"
    env["PATH"] = bindir + os.pathsep + env["PATH"]
    env.pop("HESTIA_ROLE", None)
    if preset_role is not None:
        env["HESTIA_ROLE"] = preset_role

    p = subprocess.run([os.path.join(MESH, script), src], env=env,
                       capture_output=True, text=True)
    out = p.stdout + p.stderr
    role_seen = open(seen).read() if os.path.exists(seen) else None
    basis_seen = open(seen + ".basis").read() if os.path.exists(seen + ".basis") else ""
    return out, role_seen, basis_seen


for script, stub, iddir, sender in MEMBERS:
    idpath = os.path.join(iddir, "identity.json")
    declared = "role:constellation:mesh-worker"

    # --- A: nothing to resolve from. The one that was silent on CBP. ----------
    out, seen, basis = fire(script, stub, sender)
    check(f"A {script}: an unresolved role is announced",
          WARNING in out, f"no {WARNING!r} in output:\n{out[-1200:]}")
    check(f"A {script}: the warning names the file it could not read",
          "identity.json" in out, f"output:\n{out[-1200:]}")
    check(f"A {script}: the stub CLI ran (the case is not vacuous)",
          seen is not None,
          "the fire never reached the CLI, so nothing here was actually exercised")
    # SUPERSEDED 2026-08-06. This assertion used to read "no role is invented",
    # `seen in (None, "<unset>", "")`. Its intent was right and is preserved below by a
    # STRONGER mechanism; the absence itself was the weak part.
    #
    # WHY IT CHANGED. Leaving the role blank did not stay blank: the hook registration
    # supplies `interactive-dev`, so "invent nothing" became "let something else paint it
    # attended" — the exact misattribution this file documents. The first repair refused to
    # fire at all, which stopped the mesh; dp, 2026-08-06: "how would effectively disabling
    # mesh notifications be a good thing?" It would not.
    #
    # So the fire now DECLARES what it actually knows — a mesh fire is definitionally a
    # mesh-worker session — and marks HOW it knows via HESTIA_ROLE_BASIS.
    #
    # THE ORIGINAL CONCERN SURVIVES AND IS WHY THE BASIS ASSERTION IS MANDATORY: a declared
    # role could paper over the missing hydration, and a gap nobody can see is a gap nobody
    # fixes. The basis marker is what keeps it visible — provisional must not decay into
    # permanent-but-labelled. Assert the declaration AND its basis, never one alone.
    check(f"A {script}: the fire declares what it knows rather than leaving it to be painted",
          seen == declared, f"CLI saw HESTIA_ROLE={seen!r}, expected {declared!r}")
    check(f"A {script}: and the declaration carries its basis, so the gap stays visible",
          "provisional" in basis.lower() and "declared-by-fire" in basis.lower(),
          f"CLI saw HESTIA_ROLE_BASIS={basis!r} — a provisional role without a recorded "
          "basis is indistinguishable from a hydrated one, which is the papering-over this "
          "assertion replaced 'no role is invented' to prevent")

    # --- B: POSITIVE CONTROL. The branch can resolve, and reaches the CLI. ----
    out, seen, basis = fire(script, stub, sender, identity=(idpath, {"role": declared}))
    check(f"B {script}: a readable role reaches the CLI's environment",
          seen == declared, f"CLI saw HESTIA_ROLE={seen!r}, expected {declared!r} — "
                            "case A's warning would then be proving the branch is broken, "
                            "not that this box lacks an identity file")
    check(f"B {script}: no warning when the role resolved",
          WARNING not in out, f"spurious warning:\n{out[-1200:]}")

    # --- C: an operator override must survive untouched. ---------------------
    out, seen, basis = fire(script, stub, sender, preset_role="role:constellation:reviewer",
                     identity=(idpath, {"role": declared}))
    check(f"C {script}: a preset HESTIA_ROLE is not clobbered by the identity file",
          seen == "role:constellation:reviewer", f"CLI saw HESTIA_ROLE={seen!r}")
    check(f"C {script}: no warning when the role was already set",
          WARNING not in out, f"spurious warning:\n{out[-1200:]}")

    # --- D: readable is not resolved. ----------------------------------------
    out, seen, basis = fire(script, stub, sender, identity=(idpath, {"entity": "x"}))
    check(f"D {script}: a readable identity with no role still warns",
          WARNING in out, f"no {WARNING!r} in output:\n{out[-1200:]}")
    check(f"D {script}: declares provisionally, same as A — readable is not resolved",
          seen == declared, f"CLI saw HESTIA_ROLE={seen!r}, expected {declared!r}")
    check(f"D {script}: and the basis says so",
          "provisional" in basis.lower(),
          f"CLI saw HESTIA_ROLE_BASIS={basis!r}")

print(f"\nfailures={len(failures)}")
for f in failures:
    print(f"  - {f}")
sys.exit(1 if failures else 0)
