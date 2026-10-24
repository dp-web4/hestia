#!/usr/bin/env python3
"""Grant modes at the gate (hestia #1345 part B): a narrowed grant admits exactly its modes.

Part A (#1370) gave every grant a mode set {r, w, e, d} and, to keep a mode-blind gate fail
closed, served a grant narrowed below all four ONLY in `grants_by_mode`. So until this change
narrowing a grant removed all of its reach (#523). Here the mechanism maps those narrowed rows
into the snapshot's `in_scope_modes`, the core parses them into `AgentPolicy.mode_scope`, and
evaluate() admits a path for an act only when every mode the act needs is in the grant's.

Driven through the production composition: a daemon answer -> fetch_policy_snapshot ->
resolve_agent_policy -> evaluate. Nothing here hand-authors a scope entry.

Held until the governed apply; then moves to tools/ like floor_read_only_test.py did.

Run: python3 tools/grant_modes_gate_test.py
"""
import os
import pathlib
import sys

# The repo root: the nearest ancestor holding plugins/_shared (tools/ or held/build-1345b/).
ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "plugins" / "_shared").is_dir())
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
import hestia_gate_core as core  # noqa: E402
import hestia_gate_mechanism as m  # noqa: E402
import hestia_gate_mechanism_test as mt  # noqa: E402


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


class _Workspace:
    """A fake workspace with the temp-root admission switched off (see floor_read_only_test):
    path_in_scope admits anything under a temp root before it consults grants, which would
    make every refusal below pass for the wrong reason."""

    def __enter__(self):
        self.ws = mt._fake_workspace()
        self.old_ws = os.environ.get("HESTIA_WORKSPACE")
        os.environ["HESTIA_WORKSPACE"] = self.ws
        self.old_temp = core._under_temp_root
        core._under_temp_root = lambda *a, **k: False
        self.old_ep, self.old_client = m._discover_endpoint, m._McpHttp
        os.makedirs(os.path.join(self.ws, "governance", "hestia"), exist_ok=True)
        os.makedirs(os.path.join(self.ws, "shared-context", "forum"), exist_ok=True)
        return self.ws

    def __exit__(self, *exc):
        core._under_temp_root = self.old_temp
        m._discover_endpoint, m._McpHttp = self.old_ep, self.old_client
        if self.old_ws is None:
            os.environ.pop("HESTIA_WORKSPACE", None)
        else:
            os.environ["HESTIA_WORKSPACE"] = self.old_ws
        return False


def _snapshot(ws, by_mode=None, standing=None, floor_read=None, member="cbp-being"):
    fake = mt._std_stub(ws, standing=standing, generation=3)
    if by_mode is not None:
        fake.extra["hestia_scope_status"]["grants_by_mode"] = by_mode
    if floor_read is not None:
        fake.extra["hestia_scope_status"]["society_floor_read"] = floor_read
    m._discover_endpoint = lambda: "http://fake/mcp"
    m._McpHttp = lambda ep, dl: fake
    return m.fetch_policy_snapshot(member, use_cache=False)


def _policy(snap, member="cbp-being"):
    prof = core.HarnessProfile(member_id=member, identity_path="/nonexistent/identity.json")
    return prof, core.resolve_agent_policy(prof, vault_reader=lambda _m: snap)


def _verdict(prof, pol, ws, tool, path=None, command=None, repos=None):
    ev = core.NormalizedEvent(tool=tool, paths=[path] if path else [], command=command,
                              repos=repos or [])
    return core.evaluate(ev, prof, ws, policy=pol)


def _forum(ws):
    return ws + "/shared-context/forum"


def _grant(path, modes, recursive=True, channel="standing"):
    return {"channel": channel, "path": path, "recursive": recursive, "modes": modes,
            "granted_by": "operator", "request_id": None, "expires_at": None}


def _setup(ws, modes, recursive=True):
    snap = _snapshot(ws, by_mode=[_grant(_forum(ws), modes, recursive)])
    return _policy(snap)


def test_narrowed_rows_map_to_in_scope_modes_and_never_to_in_scope():
    with _Workspace() as ws:
        full = _grant(ws + "/governance", "rwed")
        snap = _snapshot(ws, by_mode=[_grant(_forum(ws), "r"), full],
                         standing=[{k: full[k] for k in ("path", "recursive")}])
        modes = snap.get("in_scope_modes", [])
        check("one_narrowed_row", len(modes) == 1 and modes[0]["modes"] == "r", str(modes))
        check("entry_names_the_forum", _forum(ws) in modes[0]["entry"], str(modes))
        check("narrowed_not_in_in_scope", not any(_forum(ws) in e for e in snap["in_scope"]),
              str(snap["in_scope"]))
        check("full_row_not_duplicated", not any(ws + "/governance" in r["entry"] for r in modes),
              str(modes))
        _, pol = _policy(snap)
        check("policy_mode_scope", len(pol.mode_scope) == 1 and pol.mode_scope[0][1] == "r",
              str(pol.mode_scope))


def test_malformed_mode_rows_read_as_no_grant():
    with _Workspace() as ws:
        f = _forum(ws)
        bad = [_grant(f, ""), _grant(f, "x"), _grant(f, "rwedx"), _grant(f, "rz"),
               {"path": f, "recursive": True}, {"modes": "r"}, "not-a-dict",
               _grant("", "r"), {"path": 7, "modes": "r"}, {"path": f, "modes": 3}]
        snap = _snapshot(ws, by_mode=bad)
        check("nothing_mapped", snap.get("in_scope_modes") == [], str(snap.get("in_scope_modes")))
        # and the core drops malformed snapshot rows itself, whoever wrote them
        snap["in_scope_modes"] = [{"entry": "path:" + f + "/**", "modes": "r?"},
                                  {"entry": "*", "modes": "r"}, {"entry": 5, "modes": "r"},
                                  {"entry": "ssh:etc", "modes": "r"}, "x",
                                  {"entry": "path:" + f + "/**", "modes": ""}]
        prof, pol = _policy(snap)
        check("core_drops_all", pol.mode_scope == (), str(pol.mode_scope))
        v = _verdict(prof, pol, ws, "Read", path=f + "/note.md")
        check("still_refused", v.blocks and v.rule == "mrh.path", str(v))


def test_modes_are_canonicalised_not_trusted_in_order():
    with _Workspace() as ws:
        snap = _snapshot(ws, by_mode=[_grant(_forum(ws), "wr")])
        check("canonical", snap["in_scope_modes"][0]["modes"] == "rw", str(snap["in_scope_modes"]))


def test_a_read_only_grant_admits_readers_and_refuses_every_writer():
    with _Workspace() as ws:
        prof, pol = _setup(ws, "r")
        f = _forum(ws) + "/thread.md"
        for tool in ("Read", "read_file", "Grep", "Glob", "search", "git_read"):
            v = _verdict(prof, pol, ws, tool, path=f)
            check(f"{tool}_admitted", not v.blocks, str(v))
        for tool in ("Write", "write_file", "write_note", "Edit", "MultiEdit", "git_restore",
                     "git_clean"):
            v = _verdict(prof, pol, ws, tool, path=f)
            check(f"{tool}_refused", v.blocks and v.rule == "mrh.path", str(v))
            check(f"{tool}_names_the_mode", "narrowed to r" in v.reason, v.reason)
        v = _verdict(prof, pol, ws, "Bash", command=f"grep -n x {f} | head -n 3")
        check("bash_read_admitted", not v.blocks, str(v))
        for cmd in (f"echo x > {f}", f"cp /etc/hostname {f}", f"sed -i s/a/b/ {f}", f"rm {f}",
                    f"tee {f}", f"python3 {f}", f"bash {f}", f"sort -o{f} {f}", f"uniq {f} {f}2"):
            v = _verdict(prof, pol, ws, "Bash", command=cmd)
            check(f"bash_refused:{cmd[:30]}", v.blocks, str(v))


def test_a_read_write_grant_admits_writes_and_refuses_delete():
    with _Workspace() as ws:
        prof, pol = _setup(ws, "rw")
        f = _forum(ws) + "/thread.md"
        for tool in ("Read", "Write", "Edit", "write_note", "git_restore"):
            v = _verdict(prof, pol, ws, tool, path=f)
            check(f"{tool}_admitted", not v.blocks, str(v))
        v = _verdict(prof, pol, ws, "git_clean", path=f)
        check("git_clean_refused", v.blocks and v.rule == "mrh.path", str(v))
        check("git_clean_names_missing_d", "needs d (missing d)" in v.reason, v.reason)
        # a shell write is not attributed per path yet: full grants only
        v = _verdict(prof, pol, ws, "Bash", command=f"echo x > {f}")
        check("bash_write_still_full_only", v.blocks, str(v))


def test_a_write_only_grant_appends_but_cannot_read():
    with _Workspace() as ws:
        prof, pol = _setup(ws, "w")
        f = _forum(ws) + "/dropbox.md"
        for tool in ("Write", "write_note"):
            v = _verdict(prof, pol, ws, tool, path=f)
            check(f"{tool}_admitted", not v.blocks, str(v))
        for tool in ("Read", "read_file", "Grep", "Edit", "search"):
            v = _verdict(prof, pol, ws, tool, path=f)
            check(f"{tool}_refused", v.blocks and v.rule == "mrh.path", str(v))
        v = _verdict(prof, pol, ws, "Bash", command=f"cat {f}")
        check("bash_read_refused", v.blocks, str(v))


def test_a_delete_only_grant_admits_only_delete():
    with _Workspace() as ws:
        prof, pol = _setup(ws, "d")
        f = _forum(ws) + "/stale.md"
        check("git_clean_admitted", not _verdict(prof, pol, ws, "git_clean", path=f).blocks)
        for tool in ("Read", "Write", "write_note"):
            check(f"{tool}_refused", _verdict(prof, pol, ws, tool, path=f).blocks)


def test_a_tool_with_no_nameable_mode_needs_a_full_grant():
    with _Workspace() as ws:
        prof, pol = _setup(ws, "rwe")
        f = _forum(ws) + "/thread.md"
        for tool in ("mystery_tool", "Task", "run", "channel_send"):
            v = _verdict(prof, pol, ws, tool, path=f)
            check(f"{tool}_refused", v.blocks and v.rule == "mrh.path", str(v))
        v = _verdict(prof, pol, ws, "mystery_tool", path=f)
        check("says_why", "no mode the gate can name" in v.reason, v.reason)


def test_a_narrowed_grant_has_the_same_boundary_as_any_grant():
    with _Workspace() as ws:
        prof, pol = _setup(ws, "rw")
        v = _verdict(prof, pol, ws, "Read", path=ws + "/shared-context/forum-other/x.md")
        check("sibling_prefix_refused", v.blocks and v.rule == "mrh.path", str(v))
        v = _verdict(prof, pol, ws, "Read", path=ws + "/shared-context/x.md")
        check("parent_refused", v.blocks and v.rule == "mrh.path", str(v))
        prof, pol = _setup(ws, "rw", recursive=False)
        v = _verdict(prof, pol, ws, "Read", path=_forum(ws) + "/thread.md")
        check("exact_grant_child_refused", v.blocks and v.rule == "mrh.path", str(v))


def test_a_narrowed_grant_never_admits_a_repo_named_call():
    """event.repos is judged on the name against full grants only."""
    with _Workspace() as ws:
        snap = _snapshot(ws, by_mode=[_grant(ws + "/hestia", "r")])
        prof, pol = _policy(snap)
        v = _verdict(prof, pol, ws, "mcp__github__get_file", repos=["hestia"])
        check("repo_call_refused", v.blocks and v.rule == "mrh.repo", str(v))


def test_full_grants_are_unchanged():
    with _Workspace() as ws:
        full = {"path": _forum(ws), "recursive": True}
        snap = _snapshot(ws, by_mode=[_grant(_forum(ws), "rwed")], standing=[full])
        prof, pol = _policy(snap)
        f = _forum(ws) + "/thread.md"
        for tool in ("Read", "Write", "git_clean", "mystery_tool"):
            check(f"{tool}_admitted", not _verdict(prof, pol, ws, tool, path=f).blocks)
        check("bash_write_admitted", not _verdict(prof, pol, ws, "Bash", command=f"echo x > {f}").blocks)


def test_a_read_crossing_the_floor_and_a_narrowed_grant_is_one_act():
    with _Workspace() as ws:
        law = ws + "/governance/hestia"
        snap = _snapshot(ws, by_mode=[_grant(_forum(ws), "r")],
                         floor_read=[{"path": law, "recursive": True}])
        prof, pol = _policy(snap)
        v = _verdict(prof, pol, ws, "Bash", command=f"cat {law}/a.rs {_forum(ws)}/b.md")
        check("cross_read_admitted", not v.blocks, str(v))
        v = _verdict(prof, pol, ws, "Bash", command=f"cat {law}/a.rs {ws}/hestia/c.rs")
        check("cross_read_outside_refused", v.blocks, str(v))


def test_scope_roots_with_modes_reports_what_the_gate_honours():
    with _Workspace() as ws:
        full = {"path": ws + "/governance/x", "recursive": True}
        snap = _snapshot(ws, by_mode=[_grant(_forum(ws), "rw"), _grant(ws + "/governance/x", "rwed")],
                         standing=[full])
        _, pol = _policy(snap)
        roots = {r: (rec, md) for r, rec, md in core.scope_roots_with_modes(pol, ws)}
        check("narrowed_listed", roots.get(os.path.realpath(_forum(ws))) == (True, "rw"), str(roots))
        check("full_listed", roots.get(os.path.realpath(ws + "/governance/x")) == (True, "rwed"), str(roots))


def test_readers_mapped_to_r_are_closure_readers():
    """A tool the gate admits on an r grant must not be one the closure treats as a writer."""
    import hestia_governance_closure as g
    readers = {t for t, md in core.PATH_TOOL_MODES.items() if md == "r"}
    missing = sorted(readers - g._READ_PATH_TOOLS - g._COMPOSED_READ_TOOLS)
    check("r_tools_are_closure_readers", not missing, f"mapped to r but a closure writer: {missing}")


ALL = [
    test_narrowed_rows_map_to_in_scope_modes_and_never_to_in_scope,
    test_malformed_mode_rows_read_as_no_grant,
    test_modes_are_canonicalised_not_trusted_in_order,
    test_a_read_only_grant_admits_readers_and_refuses_every_writer,
    test_a_read_write_grant_admits_writes_and_refuses_delete,
    test_a_write_only_grant_appends_but_cannot_read,
    test_a_delete_only_grant_admits_only_delete,
    test_a_tool_with_no_nameable_mode_needs_a_full_grant,
    test_a_narrowed_grant_has_the_same_boundary_as_any_grant,
    test_a_narrowed_grant_never_admits_a_repo_named_call,
    test_full_grants_are_unchanged,
    test_a_read_crossing_the_floor_and_a_narrowed_grant_is_one_act,
    test_scope_roots_with_modes_reports_what_the_gate_honours,
    test_readers_mapped_to_r_are_closure_readers,
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
        except Exception as e:
            failed.append(t.__name__)
            print("ERROR", t.__name__, "::", type(e).__name__, e)
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests")
