#!/usr/bin/env python3
"""hestia #1398, the write half: a NARROWED floor entry serves the modes it holds, where no grant
of the member's own reaches.

Measured 2026-10-25 on cbp-being: dp put `shared-context/forum` on the society floor as `rw`; the
daemon served it read-only (`society_floor_read`), its `w` was never served, and a live rwed grant
had to be given to get the being writing. Here the gate reads the daemon's `floor_by_mode` (every
floor entry with its modes) into `in_scope_floor_modes` / `floor_mode_scope`, and admits an act
through the nearest floor entry covering its path when that entry holds every mode the act needs,
but only where no grant of the member's own covers the path (dp 10-23 on #1386: the floor fills
only beyond the member's own grants). An own narrower grant is never widened by the floor; an act
that can reach below the path it names still answers to the member's narrowed grants beneath it.

Driven through the production composition: a daemon answer -> fetch_policy_snapshot ->
resolve_agent_policy -> evaluate. Nothing here hand-authors a scope entry.

Built on part C (#1394) and the read half (#1406). Run: python3 held/build-1398w/floor_write_gate_test.py
"""
import os
import pathlib
import sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "plugins" / "_shared").is_dir())
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
sys.path.insert(0, str(ROOT / "tools"))
import hestia_gate_core as core  # noqa: E402
import hestia_gate_mechanism as m  # noqa: E402
import hestia_gate_mechanism_test as mt  # noqa: E402
import floor_read_only_test as fr  # noqa: E402  (the fixture: _Workspace, _policy, _verdict)


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


def _snapshot(ws, floor_by_mode=None, grants_by_mode=None, floor_read=None, member="cbp-being"):
    fake = mt._std_stub(ws, generation=3)
    if floor_by_mode is not None:
        fake.extra["hestia_scope_status"]["floor_by_mode"] = floor_by_mode
    if grants_by_mode is not None:
        fake.extra["hestia_scope_status"]["grants_by_mode"] = grants_by_mode
    if floor_read is not None:
        fake.extra["hestia_scope_status"]["society_floor_read"] = floor_read
    m._discover_endpoint = lambda: "http://fake/mcp"
    m._McpHttp = lambda ep, dl: fake
    snap = m.fetch_policy_snapshot(member, use_cache=False)
    snap["standing_grants"], snap["scope_grants"] = [], []
    return snap


def _forum(ws):
    return ws + "/shared-context/forum"


def _rw(path, recursive=True):
    return {"path": path, "recursive": recursive, "modes": "rw", "added_by": "operator",
            "reason": "the forum is writable by every member"}


def test_the_narrowed_floor_row_reaches_the_policy_as_floor_mode_scope_only():
    with fr._Workspace() as ws:
        snap = _snapshot(ws, floor_by_mode=[_rw(_forum(ws))])
        rows = snap.get("in_scope_floor_modes", [])
        check("row_mapped", any(_forum(ws) in r["entry"] and r["modes"] == "rw" for r in rows), str(rows))
        check("row_is_not_reach", not any(_forum(ws) in e for e in snap["in_scope"]), str(snap["in_scope"]))
        check("row_is_not_read_floor", not any(_forum(ws) in e for e in snap.get("in_scope_read", [])), str(snap))
        _, pol = fr._policy(snap)
        check("policy_floor_mode_scope", any(_forum(ws) in e and md == "rw"
                                             for e, md in getattr(pol, "floor_mode_scope", ())), str(pol))
        check("policy_scope_has_no_forum", not any(_forum(ws) in e for e in pol.scope), str(pol))


def test_an_rw_floor_admits_writes_and_edits_and_refuses_a_delete():
    with fr._Workspace() as ws:
        snap = _snapshot(ws, floor_by_mode=[_rw(_forum(ws))])
        prof, pol = fr._policy(snap)
        f = _forum(ws) + "/cbp-note-2026-10-27.md"
        for tool in ("Write", "write_file", "Edit", "write_note", "Read", "Grep"):
            v = fr._verdict(prof, pol, ws, tool, path=f)
            check(f"{tool}_admitted_through_rw_floor", not v.blocks, str(v))
        v = fr._verdict(prof, pol, ws, "git_clean", path=f)
        check("delete_refused", v.blocks and v.rule == "mrh.path", str(v))
        check("delete_refusal_names_the_floor", "society floor reaches here with rw" in v.reason, v.reason)
        # The shell: a read line crosses the floor; a write line needs a full grant, as in part B.
        v = fr._verdict(prof, pol, ws, "Bash", command=f"cat {f}")
        check("bash_read_admitted", not v.blocks, str(v))
        for cmd in (f"echo x > {f}", f"sed -i s/a/b/ {f}", f"rm {f}"):
            v = fr._verdict(prof, pol, ws, "Bash", command=cmd)
            check(f"bash_write_refused:{cmd.split()[0]}", v.blocks, str(v))


def test_the_floor_fills_only_where_no_own_grant_reaches():
    """#1386: an own `r` grant on forum/sub decides forum/sub; the rw floor still serves the rest."""
    with fr._Workspace() as ws:
        sub = _forum(ws) + "/sub"
        snap = _snapshot(ws, floor_by_mode=[_rw(_forum(ws))],
                         grants_by_mode=[{"path": sub, "recursive": True, "modes": "r",
                                          "channel": "standing", "granted_by": "operator"}])
        prof, pol = fr._policy(snap)
        v = fr._verdict(prof, pol, ws, "Write", path=sub + "/y.md")
        check("own_r_decides_its_subtree", v.blocks and v.rule == "mrh.path", str(v))
        check("refusal_does_not_cite_the_floor", "society floor reaches" not in v.reason, v.reason)
        v = fr._verdict(prof, pol, ws, "Read", path=sub + "/y.md")
        check("own_r_still_reads", not v.blocks, str(v))
        v = fr._verdict(prof, pol, ws, "Write", path=_forum(ws) + "/z.md")
        check("floor_serves_beyond_the_own_grant", not v.blocks, str(v))
        # A shell read under the own grant is judged by that grant (r: fine), through the walk.
        v = fr._verdict(prof, pol, ws, "Bash", command=f"cat {sub}/y.md")
        check("bash_read_under_own_r", not v.blocks, str(v))


def test_an_own_grant_above_the_floor_entry_is_not_widened_by_it():
    with fr._Workspace() as ws:
        pub = _forum(ws) + "/pub"
        snap = _snapshot(ws, floor_by_mode=[_rw(pub)],
                         grants_by_mode=[{"path": _forum(ws), "recursive": True, "modes": "r",
                                          "channel": "standing", "granted_by": "operator"}])
        prof, pol = fr._policy(snap)
        v = fr._verdict(prof, pol, ws, "Write", path=pub + "/a.md")
        check("own_r_above_decides", v.blocks and v.rule == "mrh.path", str(v))
        v = fr._verdict(prof, pol, ws, "Read", path=pub + "/a.md")
        check("read_still_admitted", not v.blocks, str(v))


def test_an_act_that_reaches_below_answers_to_the_own_narrowed_child():
    """A Grep on the forum through the rw floor, with an own w-only grant on forum/sub: the act
    needs r below, the child holds w, so the parent's floor does not carry it in (part C v2)."""
    with fr._Workspace() as ws:
        sub = _forum(ws) + "/sub"
        snap = _snapshot(ws, floor_by_mode=[_rw(_forum(ws))],
                         grants_by_mode=[{"path": sub, "recursive": True, "modes": "w",
                                          "channel": "standing", "granted_by": "operator"}])
        prof, pol = fr._policy(snap)
        os.makedirs(sub, exist_ok=True)
        v = fr._verdict(prof, pol, ws, "Grep", path=_forum(ws), materialize=False)
        check("grep_capped_by_the_child", v.blocks and "narrowed to w" in v.reason, str(v))
        v = fr._verdict(prof, pol, ws, "Read", path=_forum(ws) + "/x.md")
        check("single_target_read_beside_the_child_admitted", not v.blocks, str(v))
        v = fr._verdict(prof, pol, ws, "Bash", command=f"cat {sub}/f.txt")
        check("bash_read_under_own_w_refused", v.blocks, str(v))
        v = fr._verdict(prof, pol, ws, "Bash", command=f"grep -rn x {_forum(ws)}")
        check("bash_recursive_read_capped_by_the_child", v.blocks, str(v))


def test_an_exact_floor_entry_does_not_reach_its_children():
    with fr._Workspace() as ws:
        snap = _snapshot(ws, floor_by_mode=[_rw(_forum(ws), recursive=False)])
        prof, pol = fr._policy(snap)
        v = fr._verdict(prof, pol, ws, "Write", path=_forum(ws) + "/x.md")
        check("exact_entry_child_refused", v.blocks and v.rule == "mrh.path", str(v))


def test_malformed_and_all_mode_rows_admit_nothing():
    """An all-modes row is reach only when the daemon serves it as such (`society_floor`), never
    from this list; a row with a letter outside rwed, or empty, is dropped whole."""
    with fr._Workspace() as ws:
        for bad in ({"path": _forum(ws), "recursive": True, "modes": "rwed"},
                    {"path": _forum(ws), "recursive": True, "modes": "rx"},
                    {"path": _forum(ws), "recursive": True, "modes": ""},
                    {"path": _forum(ws), "recursive": True},
                    "not-a-row"):
            snap = _snapshot(ws, floor_by_mode=[bad])
            check(f"dropped:{bad!r:.40}", snap.get("in_scope_floor_modes", []) == [], str(snap))
            prof, pol = fr._policy(snap)
            v = fr._verdict(prof, pol, ws, "Write", path=_forum(ws) + "/x.md")
            check(f"refused:{bad!r:.40}", v.blocks and v.rule == "mrh.path", str(v))


def test_an_older_daemon_admits_nothing_extra():
    with fr._Workspace() as ws:
        snap = _snapshot(ws)
        check("no_floor_mode_scope", snap.get("in_scope_floor_modes", []) == [], str(snap))
        prof, pol = fr._policy(snap)
        v = fr._verdict(prof, pol, ws, "Write", path=_forum(ws) + "/x.md")
        check("refused_without_floor", v.blocks and v.rule == "mrh.path", str(v))


def test_the_read_floor_and_the_write_half_agree_on_a_read_only_entry():
    """An `r` floor entry arrives both as `society_floor_read` and in `floor_by_mode`; the two
    paths give the same verdicts (reads admitted, writes refused)."""
    with fr._Workspace() as ws:
        law = ws + "/governance/hestia"
        snap = _snapshot(ws, floor_read=[{"path": law, "recursive": True}],
                         floor_by_mode=[{"path": law, "recursive": True, "modes": "r"}])
        prof, pol = fr._policy(snap)
        f = law + "/plugins/_shared/hestia_single_gate.py"
        for tool in ("Read", "Grep", "search"):
            v = fr._verdict(prof, pol, ws, tool, path=f)
            check(f"{tool}_reads_the_law", not v.blocks, str(v))
        for tool in ("Write", "Edit", "write_note"):
            v = fr._verdict(prof, pol, ws, tool, path=f)
            check(f"{tool}_refused", v.blocks and v.rule == "mrh.path", str(v))


ALL = [
    test_the_narrowed_floor_row_reaches_the_policy_as_floor_mode_scope_only,
    test_an_rw_floor_admits_writes_and_edits_and_refuses_a_delete,
    test_the_floor_fills_only_where_no_own_grant_reaches,
    test_an_own_grant_above_the_floor_entry_is_not_widened_by_it,
    test_an_act_that_reaches_below_answers_to_the_own_narrowed_child,
    test_an_exact_floor_entry_does_not_reach_its_children,
    test_malformed_and_all_mode_rows_admit_nothing,
    test_an_older_daemon_admits_nothing_extra,
    test_the_read_floor_and_the_write_half_agree_on_a_read_only_entry,
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
