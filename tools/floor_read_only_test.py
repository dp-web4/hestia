#!/usr/bin/env python3
"""The read-only society floor: every member may READ a root, none may write it.

dp, 2026-10-19: "the governed see the law" — every member gets standing read access to the
governance snapshot (the read-only copy of hestia's source this machine runs). A grant
otherwise carries reach and no mode (#1098 §2, #1345), so the daemon serves read-only floor
entries under their own key, `society_floor_read`, and the gate admits them for read acts only.

Driven through the production composition: a daemon answer -> fetch_policy_snapshot ->
resolve_agent_policy -> evaluate. Nothing here hand-authors a scope entry.

Run: python3 tools/floor_read_only_test.py
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
import hestia_gate_core as core  # noqa: E402
import hestia_gate_mechanism as m  # noqa: E402
import hestia_gate_mechanism_test as mt  # noqa: E402


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


class _Workspace:
    """A fake workspace with the temp-root admission switched off: the workspace is a
    tempdir, and path_in_scope admits anything under a temp root before it consults grants,
    which would make every refusal below pass for the wrong reason."""

    def __enter__(self):
        self.ws = mt._fake_workspace()
        self.old_ws = os.environ.get("HESTIA_WORKSPACE")
        os.environ["HESTIA_WORKSPACE"] = self.ws
        self.old_temp = core._under_temp_root
        core._under_temp_root = lambda *a, **k: False
        self.old_ep, self.old_client = m._discover_endpoint, m._McpHttp
        return self.ws

    def __exit__(self, *exc):
        core._under_temp_root = self.old_temp
        m._discover_endpoint, m._McpHttp = self.old_ep, self.old_client
        if self.old_ws is None:
            os.environ.pop("HESTIA_WORKSPACE", None)
        else:
            os.environ["HESTIA_WORKSPACE"] = self.old_ws
        return False


def _snapshot(ws, floor_read=None, floor=None, member="cbp-being"):
    fake = mt._std_stub(ws, generation=3)
    if floor_read is not None:
        fake.extra["hestia_scope_status"]["society_floor_read"] = floor_read
    if floor is not None:
        fake.extra["hestia_scope_status"]["society_floor"] = floor
    m._discover_endpoint = lambda: "http://fake/mcp"
    m._McpHttp = lambda ep, dl: fake
    snap = m.fetch_policy_snapshot(member, use_cache=False)
    snap["standing_grants"], snap["scope_grants"] = [], []
    return snap


def _policy(snap, member="cbp-being"):
    prof = core.HarnessProfile(member_id=member, identity_path="/nonexistent/identity.json")
    return prof, core.resolve_agent_policy(prof, vault_reader=lambda _m: snap)


def _verdict(prof, pol, ws, tool, path=None, command=None):
    ev = core.NormalizedEvent(tool=tool, paths=[path] if path else [], command=command)
    return core.evaluate(ev, prof, ws, policy=pol)


def _law(ws):
    return ws + "/governance/hestia"


def test_a_read_only_floor_entry_reaches_the_snapshot_as_read_scope_only():
    with _Workspace() as ws:
        snap = _snapshot(ws, floor_read=[{"path": _law(ws), "recursive": True,
                                          "added_by": "operator", "reason": "see the law"}])
        check("read_entry_mapped", any(_law(ws) in e for e in snap.get("in_scope_read", [])),
              str(snap.get("in_scope_read", [])))
        check("read_entry_is_not_reach", not any(_law(ws) in e for e in snap["in_scope"]),
              str(snap["in_scope"]))
        _, pol = _policy(snap)
        check("policy_read_scope", any(_law(ws) in e for e in getattr(pol, "read_scope", ())), str(pol))
        check("policy_scope_has_no_law", not any(_law(ws) in e for e in pol.scope), str(pol))


def test_every_reader_may_read_the_law_and_no_writer_may_write_it():
    with _Workspace() as ws:
        snap = _snapshot(ws, floor_read=[{"path": _law(ws), "recursive": True}])
        prof, pol = _policy(snap)
        f = _law(ws) + "/plugins/_shared/hestia_single_gate.py"
        for tool in ("Read", "read_file", "Grep", "Glob"):
            v = _verdict(prof, pol, ws, tool, path=f)
            check(f"{tool}_reads_the_law", not v.blocks, str(v))
        for tool in ("Write", "Edit", "write_note", "write_file"):
            v = _verdict(prof, pol, ws, tool, path=f)
            check(f"{tool}_refused", v.blocks and v.rule == "mrh.path", str(v))
        v = _verdict(prof, pol, ws, "Bash", command=f"grep -n gate.degraded {f}")
        check("bash_read_reads_the_law", not v.blocks, str(v))
        for cmd in (f"echo x > {f}", f"cp /etc/hostname {f}", f"sed -i s/a/b/ {f}",
                    f"rm {f}"):
            v = _verdict(prof, pol, ws, "Bash", command=cmd)
            check(f"bash_write_refused:{cmd.split()[0]}", v.blocks, str(v))


def test_the_read_only_root_has_a_boundary():
    with _Workspace() as ws:
        snap = _snapshot(ws, floor_read=[{"path": _law(ws), "recursive": True}])
        prof, pol = _policy(snap)
        v = _verdict(prof, pol, ws, "Read", path=ws + "/governance/hestia-other/x.rs")
        check("sibling_prefix_refused", v.blocks and v.rule == "mrh.path", str(v))
        v = _verdict(prof, pol, ws, "Read", path=ws + "/hestia/core/src/lib.rs")
        check("working_tree_refused", v.blocks and v.rule == "mrh.path", str(v))


def test_an_exact_read_only_entry_does_not_reach_its_children():
    with _Workspace() as ws:
        snap = _snapshot(ws, floor_read=[{"path": _law(ws)}])
        prof, pol = _policy(snap)
        v = _verdict(prof, pol, ws, "Read", path=_law(ws) + "/core/src/lib.rs")
        check("exact_entry_child_refused", v.blocks and v.rule == "mrh.path", str(v))


def test_an_older_daemon_admits_nothing_extra():
    with _Workspace() as ws:
        snap = _snapshot(ws)
        check("no_read_scope", snap.get("in_scope_read", []) == [], str(snap))
        prof, pol = _policy(snap)
        v = _verdict(prof, pol, ws, "Read", path=_law(ws) + "/core/src/lib.rs")
        check("law_refused_without_floor", v.blocks and v.rule == "mrh.path", str(v))


def test_a_recursive_reach_floor_entry_now_reaches_its_subtree():
    with _Workspace() as ws:
        shared = ws + "/shared-context/forum"
        snap = _snapshot(ws, floor=[{"path": shared, "recursive": True}])
        prof, pol = _policy(snap)
        v = _verdict(prof, pol, ws, "Write", path=shared + "/note.md")
        check("recursive_floor_admits_child_write", not v.blocks, str(v))
        snap = _snapshot(ws, floor=[{"path": shared}])
        prof, pol = _policy(snap)
        v = _verdict(prof, pol, ws, "Write", path=shared + "/note.md")
        check("exact_floor_still_exact", v.blocks and v.rule == "mrh.path", str(v))


def test_read_only_readers_are_closure_readers():
    import hestia_governance_closure as g
    missing = sorted(core.READ_ONLY_PATH_TOOLS - g._READ_PATH_TOOLS)
    check("scope_readers_are_closure_readers", not missing,
          f"the read-only floor admits these, but the closure classes them as writers: {missing}")


ALL = [
    test_a_read_only_floor_entry_reaches_the_snapshot_as_read_scope_only,
    test_every_reader_may_read_the_law_and_no_writer_may_write_it,
    test_the_read_only_root_has_a_boundary,
    test_an_exact_read_only_entry_does_not_reach_its_children,
    test_an_older_daemon_admits_nothing_extra,
    test_a_recursive_reach_floor_entry_now_reaches_its_subtree,
    test_read_only_readers_are_closure_readers,
]

if __name__ == "__main__":
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except AssertionError as e:
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests")
