#!/usr/bin/env python3
"""Every member's INSTALLED governance surface is closure — by construction, not by list.

A member's gate does not only live at plugins/<member>/hooks/ in this repo. The installer puts
it somewhere in the member's harness home (expects.json `install.dest`), under the entry name
that harness invokes (`install.gate_probe.entry`), and wires it in through a harness config file
(`install.registration.path`). Those three declarations ARE the member's governance surface on
a running seat. A closure that names them from a hand-kept basename list covers exactly the
members whose naming happened to match the list when it was written, and nothing tells you when
a new member's does not.

So this suite does not name members. It reads every plugins/*/expects.json and, for each one,
asserts that a write to its installed gate entry, its installed witness, and its registration
config is classified "write" — through every write form the classifier keys on: Claude-shaped
Write/Edit, other harnesses' native write tools, and the shell write positions. A member added
tomorrow is covered the moment its manifest lands, or this suite is red.

Two closures are checked, because a running gate sees one and CI sees the other:
  * INSTALLED: the closure module as installed has no plugins/*/expects.json beside it, so its
    registry is empty — what it enforces is the module's own fail-safe floor. That floor must
    already carry every member's install surface.
  * REPO: the closure as loaded beside the manifests.
And one drift pin: the floor's install snapshot must equal what the manifests declare, so a
member whose manifest changes cannot silently diverge from what the installed gate enforces.

check() RAISES so pytest sees each case; the __main__ runner collects (house convention).
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hestia_governance_closure as g  # noqa: E402

PLUGINS = os.path.dirname(HERE)
FAKE_HOME = "/home/surface-probe"
_NEUTRAL_CWD = tempfile.mkdtemp(prefix="mis-neutral-")


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {str(detail)[:900]}")


def manifests():
    out = {}
    for d in sorted(os.listdir(PLUGINS)):
        p = os.path.join(PLUGINS, d, "expects.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                out[d] = json.load(fh)
    return out


def _home(path_str):
    if path_str.startswith("~/"):
        return FAKE_HOME + path_str[1:]
    if path_str.startswith("$HOME/"):
        return FAKE_HOME + path_str[5:]
    return path_str


def surfaces(manifest):
    """{label: absolute installed path} for one member, read from its install declaration."""
    inst = manifest.get("install") or {}
    dest = _home(inst["dest"])
    entry = (inst.get("gate_probe") or {})["entry"]
    files = inst.get("files") or []
    witness = [f for f in files if os.path.basename(f).startswith("witness")]
    reg = (inst.get("registration") or {})["path"]
    out = {"entry": os.path.join(dest, os.path.basename(entry)),
           "registration": os.path.join(FAKE_HOME, *reg)}
    if witness:
        out["witness"] = os.path.join(dest, os.path.basename(witness[0]))
    return out


def write_forms(target):
    """Every write form the classifier keys on, aimed at `target`."""
    d, b = os.path.dirname(target), os.path.basename(target)
    return [
        ("Write", {"file_path": target, "content": "x"}),
        ("Edit", {"file_path": target, "old_string": "a", "new_string": "b"}),
        ("write_file", {"file_path": target, "content": "x"}),       # gemini native
        ("replace", {"file_path": target, "old_string": "a", "new_string": "b"}),  # gemini
        ("WriteFile", {"path": target, "content": "x"}),              # kimi native
        ("StrReplaceFile", {"path": target, "edit": {"old": "a", "new": "b"}}),
        ("Bash", {"command": f"touch {target}"}),
        ("Bash", {"command": f"echo x > {target}"}),
        ("Bash", {"command": f"echo x >> {target}"}),
        ("Bash", {"command": f"cp /etc/hostname {target}"}),
        ("Bash", {"command": f"mv /tmp/mis-src {target}"}),
        ("Bash", {"command": f"install -m 0755 /tmp/mis-src {target}"}),
        ("Bash", {"command": f"echo x | tee {target}"}),
        ("Bash", {"command": f"sed -i s/a/b/ {target}"}),
        ("Bash", {"command": f"cd {d} && touch {b}"}),
    ]


def installed_closure():
    # What the INSTALLED module sees: no manifests beside it.
    return g.load_closure(manifest_reader=lambda: {})


def repo_closure():
    return g.load_closure(plugins_root=PLUGINS)


def _assert_all_writes(closure, tag):
    ms = manifests()
    check(f"{tag}-members-found", len(ms) >= 4, sorted(ms))
    misses = []
    for member, man in ms.items():
        for label, target in surfaces(man).items():
            for tool, ti in write_forms(target):
                v = g.classify(tool, ti, cwd=_NEUTRAL_CWD, closure=closure)
                if v.classification != "write":
                    misses.append((member, label, tool, ti.get("command") or "", v.classification))
    check(f"{tag}-every-member-surface-is-closure", not misses,
          f"{len(misses)} uncovered: {misses[:12]}")


def test_every_member_install_surface_is_closure_installed():
    _assert_all_writes(installed_closure(), "installed")


def test_every_member_install_surface_is_closure_repo():
    _assert_all_writes(repo_closure(), "repo")


def test_every_member_install_surface_is_closure_on_failure():
    # A registry that raises falls back to the fail-safe floor — which must still hold.
    def broken():
        raise RuntimeError("registry unreadable")
    _assert_all_writes(g.load_closure(manifest_reader=broken), "failsafe")


def test_reading_an_install_surface_is_a_read_not_a_write():
    # Over-denying a read manufactures bypasses: reconnaissance stays an allowed, witnessed read.
    c = installed_closure()
    for member, man in manifests().items():
        for label, target in surfaces(man).items():
            for tool, ti in (("Read", {"file_path": target}),
                             ("Bash", {"command": f"cat {target}"}),
                             ("Bash", {"command": f"cp {target} /tmp/mis-copy"})):
                v = g.classify(tool, ti, cwd=_NEUTRAL_CWD, closure=c)
                check(f"{member}-{label}-{tool}-read", v.classification == "read", (ti, v))


def test_a_neighbour_of_the_surface_is_not_closure():
    # The surface is the declared files, not the harness home: a note beside the registration,
    # or a project file named like the entry outside any hooks dir, stays ordinary work.
    c = installed_closure()
    for member, man in manifests().items():
        s = surfaces(man)
        neighbour = os.path.join(os.path.dirname(s["registration"]), "notes.md")
        v = g.classify("Write", {"file_path": neighbour, "content": "x"}, cwd=_NEUTRAL_CWD, closure=c)
        check(f"{member}-registration-neighbour-is-ordinary", v.classification != "write", (neighbour, v))
        stray = os.path.join(FAKE_HOME, "src", "proj", os.path.basename(s["entry"]))
        v = g.classify("Write", {"file_path": stray, "content": "x"}, cwd=_NEUTRAL_CWD, closure=c)
        check(f"{member}-entry-name-outside-hooks-is-ordinary", v.classification != "write", (stray, v))


def test_floor_install_snapshot_matches_the_manifests():
    """Drift pin. The installed module cannot read the manifests, so it carries a snapshot of
    each member's install declaration. That snapshot must equal what the manifests declare —
    adding, renaming or moving a member's gate without updating it is red here."""
    snap = getattr(g, "MEMBER_INSTALL_DECLARATIONS", None)
    check("snapshot-exists", isinstance(snap, dict), "closure module carries no install snapshot")
    declared = {}
    for member, man in manifests().items():
        decl = g._install_declaration(man.get("install"))
        if decl is not None:
            declared[member] = decl
    check("snapshot-equals-manifests", snap == declared,
          f"snapshot {json.dumps(snap, sort_keys=True)} != manifests {json.dumps(declared, sort_keys=True)}")


def test_a_new_member_is_covered_by_its_manifest_alone():
    # A hypothetical member with an entry name, home and registration no list has seen: its
    # manifest is enough for the repo-loaded closure, with no core edit.
    novel = {"install": {"member": "novel", "dest": "~/.novel-harness/gate",
                         "registration": {"path": [".novel-harness", "wiring.yaml"]},
                         "files": ["hooks/on_call.py"],
                         "gate_probe": {"entry": "hooks/on_call.py"}}}
    c = g.load_closure(manifest_reader=lambda: {"novel": novel})
    for label, target in surfaces(novel).items():
        for tool, ti in write_forms(target):
            v = g.classify(tool, ti, cwd=_NEUTRAL_CWD, closure=c)
            check(f"novel-{label}-{tool}", v.classification == "write", (ti, v))


def test_a_degenerate_declaration_does_not_widen_the_closure():
    # A one-segment dest or registration would govern every same-named dir/file anywhere.
    bad = {"install": {"dest": "~/hooks", "registration": {"path": ["settings.json"]},
                       "gate_probe": {"entry": "hooks/x.py"}}}
    c = g.load_closure(manifest_reader=lambda: {"bad": bad})
    for p in ("/srv/app/hooks/readme.md", "/srv/app/settings.json"):
        v = g.classify("Write", {"file_path": p, "content": "x"}, cwd=_NEUTRAL_CWD, closure=c)
        check(f"degenerate-{p}", v.classification == "none", v)


def test_the_verdict_carries_the_resolved_location():
    """The daemon prices a member's gate entry by LOCATION, from the location the gate resolved
    — never from how the act was spelled. So every spelling of a write to an installed entry
    (relative to the cwd, inside a `cd`, through `..`, through a symlinked dir, home-relative)
    carries the same resolved location; a `..` that only looks like the location by prefix
    resolves outside it."""
    c = installed_closure()
    root = tempfile.mkdtemp(prefix="mis-resolved-")
    for member, man in manifests().items():
        inst = man["install"]
        rel_dest = inst["dest"][2:] if inst["dest"].startswith("~/") else inst["dest"].lstrip("/")
        dest = os.path.join(root, member, rel_dest)
        os.makedirs(dest, exist_ok=True)
        base = os.path.basename(inst["gate_probe"]["entry"])
        want = os.path.realpath(os.path.join(dest, base))
        alias = os.path.join(root, member + "-alias")
        os.symlink(dest, alias)
        for label, tool, ti, cwd in (
            ("absolute", "Write", {"file_path": os.path.join(dest, base)}, _NEUTRAL_CWD),
            ("relative-to-cwd", "Write", {"file_path": base}, dest),
            ("dot-relative", "Write", {"file_path": "./" + base}, dest),
            ("cd-then-touch", "Bash", {"command": f"cd {dest} && touch {base}"}, _NEUTRAL_CWD),
            ("dotdot-inside", "Bash", {"command": f"touch {dest}/sub/../{base}"}, _NEUTRAL_CWD),
            ("symlinked-dir", "Bash", {"command": f"echo x > {alias}/{base}"}, _NEUTRAL_CWD),
            ("double-slash", "Write", {"file_path": dest + "//" + base}, _NEUTRAL_CWD),
        ):
            v = g.classify(tool, ti, cwd=cwd, closure=c)
            check(f"{member}-{label}-write", v.classification == "write", (ti, v))
            check(f"{member}-{label}-resolved", v.resolved == want, (ti, v.resolved, want))
        # A `..` that leaves the dest: the resolved location is OUTSIDE it.
        v = g.classify("Bash", {"command": f"touch {dest}/../{os.path.basename(dest)}-old/{base}"},
                       cwd=_NEUTRAL_CWD, closure=c)
        check(f"{member}-lookalike-resolves-outside",
              v.resolved is None or not v.resolved.startswith(dest + os.sep), v)
    # Reads and non-closure acts carry no resolved location.
    v = g.classify("Read", {"file_path": os.path.join(FAKE_HOME, ".gemini", "settings.json")},
                   cwd=_NEUTRAL_CWD, closure=c)
    check("a-read-carries-no-resolved", v.resolved is None, v)


ALL = [
    test_every_member_install_surface_is_closure_installed,
    test_every_member_install_surface_is_closure_repo,
    test_every_member_install_surface_is_closure_on_failure,
    test_reading_an_install_surface_is_a_read_not_a_write,
    test_a_neighbour_of_the_surface_is_not_closure,
    test_floor_install_snapshot_matches_the_manifests,
    test_a_new_member_is_covered_by_its_manifest_alone,
    test_a_degenerate_declaration_does_not_widen_the_closure,
    test_the_verdict_carries_the_resolved_location,
]

if __name__ == "__main__":
    print("member install surface — every member's installed gate, witness and registration")
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except Exception as e:  # noqa: BLE001 — collect
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    print()
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests")
