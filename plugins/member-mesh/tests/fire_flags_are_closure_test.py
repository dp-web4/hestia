#!/usr/bin/env python3
"""A member cannot arm the mesh's fire flags: $HESTIA_HOME/mesh-fire.d is governance closure (#1374).

Nova's release gate on #1374: "demonstrate no auto-firing when a mesh-fire.d/<member> flag is writable by a governed
member ... a file's mere presence should not convey operator authority unless owner/mode and trusted directory are
checked." install-watchers.sh checks owner, mode and symlinks (install_watchers_test.test_fire_needs_operator_authority),
but every governed member runs as the operator's UID, so those checks cannot tell the operator's flag from a member's.
The gate can: LITERAL_FLOOR carries ("mesh-fire.d",) as a dir marker, so creating, changing, linking or removing
anything in or under it is a closure write, refused and escalated to a human.

Every arm below is a way a member could set a flag; each must classify as a closure WRITE. Controls: reading the dir
stays a read, and a look-alike segment ("mesh-fire.d.bak", "mesh-fire") is not matched (whole-segment equality).
Pinned to LITERAL_FLOOR and a neutral cwd, as tools/governance_closure_arms_test.py does.
"""
import os
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_REPO, "plugins", "_shared"))
import hestia_governance_closure as g  # noqa: E402

FLOOR = g.LITERAL_FLOOR
_CWD = tempfile.mkdtemp(prefix="fire-flags-closure-")
HH = "/home/someone/.hestia"
FLAG = HH + "/mesh-fire.d/claude-code"


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


def bash(cmd):
    v = g.classify("Bash", {"command": cmd}, cwd=_CWD, closure=FLOOR)
    return v.classification, v.resource


def test_the_floor_carries_the_marker():
    check("marker", ("mesh-fire.d",) in FLOOR.dir_markers, f"dir_markers={FLOOR.dir_markers}")
    check("match flag", FLOOR.match(FLAG) == "mesh-fire.d", f"got {FLOOR.match(FLAG)!r}")
    check("match dir", FLOOR.match(HH + "/mesh-fire.d") == "mesh-fire.d", f"got {FLOOR.match(HH + '/mesh-fire.d')!r}")


def test_every_way_to_set_a_flag_is_a_closure_write():
    arms = {
        "touch": f"touch {FLAG}",
        "mkdir": f"mkdir -p {HH}/mesh-fire.d",
        "redirect": f"echo fire > {FLAG}",
        "tee": f"echo fire | tee {FLAG}",
        "cp": f"cp /tmp/x {FLAG}",
        "symlink": f"ln -s /tmp/x {FLAG}",
        "chmod": f"chmod 600 {FLAG}",
        "rm (disarm is also an operator act)": f"rm {FLAG}",
    }
    for name, cmd in arms.items():
        c, res = bash(cmd)
        check(name, c == "write", f"{cmd!r} classified {c!r} (resource {res!r})")
    for tool, inp in (("Write", {"file_path": FLAG, "content": "fire"}),
                      ("Edit", {"file_path": FLAG, "old_string": "a", "new_string": "b"})):
        v = g.classify(tool, inp, cwd=_CWD, closure=FLOOR)
        check(tool, v.classification == "write", f"{tool} on the flag classified {v.classification!r}")


def test_controls_reading_and_look_alikes():
    c, _ = bash(f"ls -la {HH}/mesh-fire.d")
    check("read stays read", c == "read", f"ls classified {c!r}")
    for p in (HH + "/mesh-fire.d.bak/claude-code", HH + "/mesh-fire/claude-code"):
        check("look-alike " + p, FLOOR.match(p) is None, f"matched {FLOOR.match(p)!r}")


ALL = [
    test_the_floor_carries_the_marker,
    test_every_way_to_set_a_flag_is_a_closure_write,
    test_controls_reading_and_look_alikes,
]

FAILS = []


def teardown_module(module=None):
    assert not FAILS, FAILS


if __name__ == "__main__":
    for fn in ALL:
        try:
            fn()
            print(f"ok    {fn.__name__}")
        except AssertionError as e:
            FAILS.append(fn.__name__)
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(ALL) - len(FAILS)}/{len(ALL)} passed")
    sys.exit(1 if FAILS else 0)
