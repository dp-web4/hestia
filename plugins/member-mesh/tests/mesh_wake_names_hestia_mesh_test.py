#!/usr/bin/env python3
"""The wake hook names acts the member's gate admits (#1503, Nova's #1504 HOLD).

WHAT HAPPENED (McNugget, 2026-11-07). session-mesh-inbox.sh told every member to act on its notices
with `python3 $DIR/hestia-mesh.py drain` and to "act per KINDS.md". $DIR is the install dir under
$HESTIA_HOME/deploy, which no member grant reaches. So the member that did exactly what the hook said
was refused (mrh.command), and each refusal opened a scope request that fell to the operator: dp,
"the mesh stuff is needing a bunch of grants. i approved some. but it's a friction". The printed line
also lacked HESTIA_MESH_PLUGIN, which the member's own shell does not carry, so even an admitted
drain would have refused with rc=2 (#108).

The fix names `hestia mesh`: the mesh CLI and KINDS.md compiled into the hestia binary
(core/src/mesh_cli.rs; its own tests in core/tests/mesh_subcommand.rs run the real binary). This file
tests the hook and the gate, with a stand-in `hestia` on PATH so the plugin suite needs no Rust build:

  C. The CLI's own `kinds` (the path form, for hosts whose hestia predates `mesh`) prints the
     KINDS.md beside it, with NO identity and NO daemon request.
  D. The hook names `hestia mesh` when this host's hestia answers `hestia mesh kinds`, and the path
     form otherwise. Both carry the identity (and the role when set).
  E. The `hestia mesh` line, run exactly as printed in a shell with no identity, drains as the member
     it names.
  G. The gate admits the `hestia mesh` lines and refuses the old path form.
  H. Nova's control, stated rather than hidden: the gate binds no command word to an executable — not
     `hestia`, not any other — and the daemon's member tools were reachable without any CLI before
     this change. What `hestia mesh` binds is the CODE the hook's instruction runs: the release's
     compiled bytes, not a file under $HESTIA_HOME/deploy that a grant there could rewrite.

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
    """An install dir laid out the way install-members.sh lays it out."""
    d = os.path.join(tmp, "deploy", "hestia", "plugins", "member-mesh")
    os.makedirs(d)
    for name in ("hestia-mesh.py", "session-mesh-inbox.sh", "KINDS.md"):
        shutil.copy2(os.path.join(SRC, name), os.path.join(d, name))
    return d


def stand_in_hestia(bindir, mesh_dir, with_mesh=True):
    """A `hestia` that behaves like the binary's `mesh` subcommand (kinds natively, the rest through the
    CLI with HESTIA_MESH_PROG set), or like an older hestia that has no `mesh`."""
    os.makedirs(bindir, exist_ok=True)
    path = os.path.join(bindir, "hestia")
    with open(path, "w") as f:
        if with_mesh:
            f.write("#!/bin/sh\n[ \"$1\" = mesh ] || exit 2\nshift\n"
                    f"HESTIA_MESH_PROG='hestia mesh' exec python3 '{mesh_dir}/hestia-mesh.py' \"$@\"\n")
        else:
            f.write("#!/bin/sh\necho \"error: unrecognized subcommand '$1'\" >&2\nexit 2\n")
    os.chmod(path, 0o755)


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
    d = install(tmp)
    kinds_text = open(os.path.join(d, "KINDS.md"), encoding="utf-8").read()
    cli = os.path.join(d, "hestia-mesh.py")

    print("--- C. the CLI's own kinds, as nobody ---")
    dz = StubDaemon()
    p = subprocess.run([sys.executable, cli, "kinds"], env=env_with(BASE_PATH, HESTIA_ENDPOINT=dz.endpoint),
                       capture_output=True, text=True, timeout=30)
    check(p.returncode == 0, "C1. `hestia-mesh.py kinds` needs no identity", f"rc={p.returncode} {p.stderr[:200]}")
    check(p.stdout == kinds_text, "C2. it prints the KINDS.md beside it, whole")
    check(dz.requests == 0, "C3. and sends nothing to the daemon", f"requests={dz.requests}")
    p = subprocess.run([sys.executable, cli, "kinds", "one row per RULING"], env=env_with(BASE_PATH),
                       capture_output=True, text=True, timeout=30)
    check(p.returncode == 0 and "a disposition is one row per RULING" in p.stdout
          and "Local member-mesh notice kinds" not in p.stdout,
          "C4. `kinds <term>` prints only the sections that name the term", p.stdout[:200])
    p = subprocess.run([sys.executable, cli, "kinds", "zz-no-such-term-zz"], env=env_with(BASE_PATH),
                       capture_output=True, text=True, timeout=30)
    check(p.returncode == 1 and p.stdout == "" and "zz-no-such-term-zz" in p.stderr,
          "C5. an unmatched term says so and exits 1, never an empty success", f"rc={p.returncode}")
    dz.stop()

    print("--- D. the hook names `hestia mesh` only when this host's hestia has it ---")
    hook = os.path.join(d, "session-mesh-inbox.sh")
    new_bin, old_bin = os.path.join(tmp, "bin-new"), os.path.join(tmp, "bin-old")
    stand_in_hestia(new_bin, d, with_mesh=True)
    stand_in_hestia(old_bin, d, with_mesh=False)
    d1 = StubDaemon(notices=NOTICE)

    def hook_lines(bindir, **extra):
        path = (bindir + os.pathsep + BASE_PATH) if bindir else BASE_PATH
        p = subprocess.run(["sh", hook], env=env_with(path, HESTIA_MESH_PLUGIN="claude-code",
                           HESTIA_ENDPOINT=d1.endpoint, **extra), capture_output=True, text=True, timeout=30)
        return instruction_lines(p.stdout), p.stdout

    lines, out = hook_lines(new_bin)
    check(len(lines) == 2, "D1. the hook prints its two instruction lines", out)
    check("HESTIA_MESH_PLUGIN=claude-code hestia mesh drain" in lines[0]
          and "(hestia mesh kinds [term])" in lines[0],
          "D2. hestia has `mesh`: drain and KINDS are named through it, with the identity on the line", lines[0])
    check(lines[1].startswith("Reply/ack: HESTIA_MESH_PLUGIN=claude-code hestia mesh send "),
          "D3. the ack line names it too", lines[1])
    check(not any(d in l for l in lines), "D4. no instruction line names the install dir", "\n".join(lines))

    for label, bindir in (("an older hestia without `mesh`", old_bin), ("no hestia on PATH", None)):
        lines, out = hook_lines(bindir)
        check(len(lines) == 2 and f"HESTIA_MESH_PLUGIN=claude-code python3 {d}/hestia-mesh.py drain" in lines[0]
              and f"({d}/KINDS.md)" in lines[0],
              f"D5. {label}: the path form, still carrying the identity", "\n".join(lines))

    lines, out = hook_lines(new_bin, HESTIA_ROLE="role:constellation:member")
    check(len(lines) == 2 and "HESTIA_MESH_PLUGIN=claude-code HESTIA_ROLE=role:constellation:member hestia mesh drain"
          in lines[0], "D6. a set role rides on the line too (one grain, PR #66)", "\n".join(lines))
    d1.stop()

    print("--- E. the `hestia mesh` line, run as printed ---")
    d2 = StubDaemon(notices=NOTICE)
    env = env_with(new_bin + os.pathsep + BASE_PATH, HESTIA_MESH_PLUGIN="claude-code", HESTIA_ENDPOINT=d2.endpoint)
    p = subprocess.run(["sh", hook], env=env, capture_output=True, text=True, timeout=30)
    line = instruction_lines(p.stdout)[0].split("then: ", 1)[1]
    run_env = env_with(new_bin + os.pathsep + BASE_PATH, HESTIA_ENDPOINT=d2.endpoint)  # the member's shell: no identity
    p = subprocess.run(["sh", "-c", line], env=run_env, capture_output=True, text=True, timeout=30)
    check(p.returncode == 0, "E1. the printed drain line runs in a shell that has no identity of its own",
          f"rc={p.returncode} {p.stderr[:300]}")
    got = d2.connect_args[-1] if d2.connect_args else {}
    check(got.get("plugin_id") == "claude-code", "E2. and drains as the member the line names", json.dumps(got))
    p = subprocess.run(["sh", "-c", "hestia mesh peek"], env=run_env, capture_output=True, text=True, timeout=30)
    check(p.returncode == 2 and "HESTIA_MESH_PLUGIN=claude-code hestia mesh peek" in p.stderr,
          "E3. without the identity the refusal names the command the member actually ran", p.stderr[:300])
    d2.stop()

    print("--- G. the gate admits the `hestia mesh` lines and refuses the path form ---")
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import floor_read_only_test as t  # noqa: E402

    with t._Workspace() as ws:
        snap = t._snapshot(ws)
        prof, pol = t._policy(snap)
        outside = os.path.join(ws, ".hestia", "deploy", "hestia", "plugins", "member-mesh")
        t._materialize(os.path.join(outside, "hestia-mesh.py"))
        for cmd in ("HESTIA_MESH_PLUGIN=claude-code hestia mesh drain",
                    "HESTIA_MESH_PLUGIN=claude-code hestia mesh send kimi-code ack shared-context/forum/x.md 7",
                    "hestia mesh kinds disposition"):
            v = t._verdict(prof, pol, ws, "Bash", command=cmd, materialize=False)
            check(not v.blocks, f"G1. admitted: {cmd}", str(v))
        v = t._verdict(prof, pol, ws, "Bash", materialize=False,
                       command=f"HESTIA_MESH_PLUGIN=claude-code python3 {outside}/hestia-mesh.py drain")
        check(v.blocks and v.rule == "mrh.command",
              "G2. the old path form is refused — the friction this removes", str(v))

        print("--- H. Nova's control: what the gate binds, and what it never did ---")
        v = t._verdict(prof, pol, ws, "Bash", materialize=False,
                       command="PATH=/tmp/other:$PATH HESTIA_MESH_PLUGIN=claude-code hestia mesh drain")
        check(not v.blocks, "H1. the gate binds no command word to an executable — `hestia` included", str(v))
        for cmd in ("python3 -c 'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:7711/mcp\")'",
                    "curl -s http://127.0.0.1:7711/mcp -d @-"):
            v = t._verdict(prof, pol, ws, "Bash", command=cmd, materialize=False)
            check(not v.blocks, f"H2. the daemon's member tools were reachable with no CLI at all: {cmd[:40]}", str(v))

print("all passed")
