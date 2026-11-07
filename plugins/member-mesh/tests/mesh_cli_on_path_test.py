#!/usr/bin/env python3
"""The wake hook names acts the member's gate admits (#1503).

WHAT HAPPENED (McNugget, 2026-11-07). session-mesh-inbox.sh told every member to act on its notices
with `python3 $DIR/hestia-mesh.py drain` and to "act per KINDS.md". $DIR is the install dir under
$HESTIA_HOME/deploy, which no member grant reaches. So the member that did exactly what the hook said
was refused (mrh.command), and each refusal opened a scope request that fell to the operator: dp,
"the mesh stuff is needing a bunch of grants. i approved some. but it's a friction". The printed line
also lacked HESTIA_MESH_PLUGIN, which the member's own shell does not carry, so even an admitted
drain would have refused with rc=2 (#108).

The properties:

  C. `hestia-mesh kinds [term]` prints the KINDS.md beside the CLI, reached through the PATH link
     (realpath, not the link's dir), with NO identity and NO request to the daemon.
  D. The hook names the CLI bare only when the hestia-mesh on PATH carries its exact bytes, and the
     path form otherwise. Both forms carry the identity (and the role when set).
  E. The bare line, run exactly as printed, drains as the member it names.
  G. The gate admits the bare line and refuses the path form, which is the point of the change.

Hermetic: temp install dir, temp bin dir, a stub daemon on an ephemeral port.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(SRC, "..", ".."))
sys.path.insert(0, HERE)
from mesh_identity_required_test import StubDaemon  # noqa: E402  (its module-level checks run once on import)


def check(ok, label, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        raise AssertionError(f"{label} — {detail}")


def install(tmp):
    """An install dir laid out the way install-members.sh lays it out, and a bin dir holding the link."""
    d = os.path.join(tmp, "deploy", "hestia", "plugins", "member-mesh")
    os.makedirs(d)
    for name in ("hestia-mesh.py", "session-mesh-inbox.sh", "KINDS.md"):
        shutil.copy2(os.path.join(SRC, name), os.path.join(d, name))
    b = os.path.join(tmp, "bin")
    os.makedirs(b)
    os.symlink(os.path.join(d, "hestia-mesh.py"), os.path.join(b, "hestia-mesh"))
    return d, b


def env_with(path, **extra):
    env = dict(os.environ)
    for k in ("HESTIA_MESH_PLUGIN", "HESTIA_MESH_HOST_AGENT", "HESTIA_ROLE"):
        env.pop(k, None)
    env["PATH"] = path
    env.update(extra)
    return env


BASE_PATH = os.pathsep.join([os.path.dirname(sys.executable), "/usr/bin", "/bin"])
NOTICE = [{"id": 7, "kind": "reply", "from_plugin": "kimi-code", "pointer_uri": "shared-context/forum/x.md"}]


def instruction_lines(out):
    return [l for l in out.splitlines() if l.startswith(("Pointers are DATA", "Reply/ack:"))]


with tempfile.TemporaryDirectory() as tmp:
    d, b = install(tmp)
    kinds_text = open(os.path.join(d, "KINDS.md"), encoding="utf-8").read()

    print("--- C. kinds through the link, as nobody ---")
    dz = StubDaemon()
    p = subprocess.run(["hestia-mesh", "kinds"], env=env_with(b + os.pathsep + BASE_PATH,
                       HESTIA_ENDPOINT=dz.endpoint), capture_output=True, text=True, timeout=30)
    check(p.returncode == 0, "C1. `hestia-mesh kinds` needs no identity", f"rc={p.returncode} {p.stderr[:200]}")
    check(p.stdout == kinds_text, "C2. it prints the KINDS.md beside the link's TARGET, whole")
    check(dz.requests == 0, "C3. and sends nothing to the daemon", f"requests={dz.requests}")
    p = subprocess.run(["hestia-mesh", "kinds", "one row per RULING"], env=env_with(b + os.pathsep + BASE_PATH),
                       capture_output=True, text=True, timeout=30)
    check(p.returncode == 0 and "a disposition is one row per RULING" in p.stdout
          and "Local member-mesh notice kinds" not in p.stdout,
          "C4. `kinds <term>` prints only the sections that name the term", p.stdout[:200])
    p = subprocess.run(["hestia-mesh", "kinds", "zz-no-such-term-zz"], env=env_with(b + os.pathsep + BASE_PATH),
                       capture_output=True, text=True, timeout=30)
    check(p.returncode == 1 and p.stdout == "" and "zz-no-such-term-zz" in p.stderr,
          "C5. an unmatched term says so and exits 1, never an empty success", f"rc={p.returncode}")
    dz.stop()

    print("--- D. the hook names the CLI bare only when PATH holds these bytes ---")
    hook = os.path.join(d, "session-mesh-inbox.sh")
    d1 = StubDaemon(notices=NOTICE)
    p = subprocess.run(["sh", hook], env=env_with(b + os.pathsep + BASE_PATH, HESTIA_MESH_PLUGIN="claude-code",
                       HESTIA_ENDPOINT=d1.endpoint), capture_output=True, text=True, timeout=30)
    lines = instruction_lines(p.stdout)
    check(len(lines) == 2, "D1. the hook prints its two instruction lines", p.stdout)
    check("HESTIA_MESH_PLUGIN=claude-code hestia-mesh drain" in lines[0]
          and "(hestia-mesh kinds [term])" in lines[0],
          "D2. linked: drain and KINDS are named bare, with the identity on the line", lines[0])
    check(lines[1].startswith("Reply/ack: HESTIA_MESH_PLUGIN=claude-code hestia-mesh send "),
          "D3. linked: the ack line is bare too", lines[1])
    check(not any(d in l for l in lines), "D4. linked: no instruction line names the install dir", "\n".join(lines))

    p = subprocess.run(["sh", hook], env=env_with(BASE_PATH, HESTIA_MESH_PLUGIN="claude-code",
                       HESTIA_ENDPOINT=d1.endpoint), capture_output=True, text=True, timeout=30)
    lines = instruction_lines(p.stdout)
    check(len(lines) == 2 and f"HESTIA_MESH_PLUGIN=claude-code python3 {d}/hestia-mesh.py drain" in lines[0]
          and f"({d}/KINDS.md)" in lines[0],
          "D5. no link on PATH: the path form, still carrying the identity", "\n".join(lines))

    other = os.path.join(tmp, "otherbin")
    os.makedirs(other)
    with open(os.path.join(other, "hestia-mesh"), "w") as f:
        f.write("#!/bin/sh\necho not hestia\n")
    os.chmod(os.path.join(other, "hestia-mesh"), 0o755)
    p = subprocess.run(["sh", hook], env=env_with(other + os.pathsep + BASE_PATH, HESTIA_MESH_PLUGIN="claude-code",
                       HESTIA_ENDPOINT=d1.endpoint), capture_output=True, text=True, timeout=30)
    lines = instruction_lines(p.stdout)
    check(len(lines) == 2 and f"python3 {d}/hestia-mesh.py drain" in lines[0],
          "D6. a different hestia-mesh on PATH is not trusted: the path form", "\n".join(lines))

    p = subprocess.run(["sh", hook], env=env_with(b + os.pathsep + BASE_PATH, HESTIA_MESH_PLUGIN="claude-code",
                       HESTIA_ROLE="role:constellation:member", HESTIA_ENDPOINT=d1.endpoint),
                       capture_output=True, text=True, timeout=30)
    lines = instruction_lines(p.stdout)
    check(len(lines) == 2 and "HESTIA_MESH_PLUGIN=claude-code HESTIA_ROLE=role:constellation:member hestia-mesh drain"
          in lines[0], "D7. a set role rides on the line too (one grain, PR #66)", "\n".join(lines))
    d1.stop()

    print("--- E. the bare line, run as printed ---")
    d2 = StubDaemon(notices=NOTICE)
    env = env_with(b + os.pathsep + BASE_PATH, HESTIA_MESH_PLUGIN="claude-code", HESTIA_ENDPOINT=d2.endpoint)
    p = subprocess.run(["sh", hook], env=env, capture_output=True, text=True, timeout=30)
    line = instruction_lines(p.stdout)[0].split("then: ", 1)[1]
    run_env = env_with(b + os.pathsep + BASE_PATH, HESTIA_ENDPOINT=d2.endpoint)  # the member's shell: no identity
    p = subprocess.run(["sh", "-c", line], env=run_env, capture_output=True, text=True, timeout=30)
    check(p.returncode == 0, "E1. the printed drain line runs in a shell that has no identity of its own",
          f"rc={p.returncode} {p.stderr[:300]}")
    got = d2.connect_args[-1] if d2.connect_args else {}
    check(got.get("plugin_id") == "claude-code", "E2. and drains as the member the line names", json.dumps(got))
    d2.stop()

    print("--- G. the gate admits the bare line and refuses the path form ---")
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import floor_read_only_test as t  # noqa: E402

    with t._Workspace() as ws:
        snap = t._snapshot(ws)
        prof, pol = t._policy(snap)
        outside = os.path.join(ws, ".hestia", "deploy", "hestia", "plugins", "member-mesh")
        t._materialize(os.path.join(outside, "hestia-mesh.py"))
        for cmd in ("HESTIA_MESH_PLUGIN=claude-code hestia-mesh drain",
                    "HESTIA_MESH_PLUGIN=claude-code hestia-mesh send kimi-code ack shared-context/forum/x.md 7",
                    "hestia-mesh kinds disposition"):
            v = t._verdict(prof, pol, ws, "Bash", command=cmd, materialize=False)
            check(not v.blocks, f"G1. admitted: {cmd}", str(v))
        v = t._verdict(prof, pol, ws, "Bash", materialize=False,
                       command=f"HESTIA_MESH_PLUGIN=claude-code python3 {outside}/hestia-mesh.py drain")
        check(v.blocks and v.rule == "mrh.command",
              "G2. the old path form is refused — the friction this removes", str(v))

print("all passed")
