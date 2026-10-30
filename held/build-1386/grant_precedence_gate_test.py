#!/usr/bin/env python3
"""The nearest explicit grant decides (hestia #1386, part C).

dp, 2026-10-24: "if explicit grant, use explicit grant; else traverse to ../ and repeat". Part B
admitted a path through any covering grant (a union), so a narrowed grant beneath a broader one
was ignored. Here the deepest grant node covering a path decides it, with its modes; grants on
one node union. Driven through the production composition (daemon answer -> snapshot -> policy
-> evaluate), reusing part B's harness.

Run: python3 held/build-1386/grant_precedence_gate_test.py
"""
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
# Part B's harness, moved to tools/ when part B was activated (#1397).
sys.path.insert(0, str(HERE.parents[1] / "tools"))
import grant_modes_gate_test as g  # noqa: E402

core, m, mt, check = g.core, g.m, g.mt, g.check


def _full(path, recursive=True):
    return {"path": path, "recursive": recursive}


def _world(ws):
    for d in ("proj/sub", "proj/other"):
        os.makedirs(os.path.join(ws, d), exist_ok=True)
    return ws + "/proj"


def _pol(ws, narrowed=(), full=()):
    rows = [g._grant(p, md, rec) for p, md, rec in narrowed]
    rows += [g._grant(f["path"], "rwed", f["recursive"]) for f in full]
    snap = g._snapshot(ws, by_mode=rows, standing=list(full))
    return g._policy(snap)


def _blocks(prof, pol, ws, tool, path=None, command=None):
    return g._verdict(prof, pol, ws, tool, path=path, command=command).blocks


def test_a_narrowed_child_caps_a_full_parent():
    with g._Workspace() as ws:
        proj = _world(ws)
        prof, pol = _pol(ws, narrowed=[(proj + "/sub", "r", True)], full=[_full(proj)])
        check("read_child", not _blocks(prof, pol, ws, "Read", proj + "/sub/x.md"))
        v = g._verdict(prof, pol, ws, "Write", path=proj + "/sub/x.md")
        check("write_child_refused", v.blocks, str(v))
        check("names_1386", "#1386" in v.reason and "missing w" in v.reason, v.reason)
        check("write_elsewhere_in_parent", not _blocks(prof, pol, ws, "Write", proj + "/other/x.md"))


def test_a_read_only_umbrella_does_not_erase_a_full_child():
    with g._Workspace() as ws:
        proj = _world(ws)
        prof, pol = _pol(ws, narrowed=[(proj, "r", True)], full=[_full(proj + "/sub")])
        check("write_full_child", not _blocks(prof, pol, ws, "Write", proj + "/sub/x.md"))
        check("write_under_umbrella_refused", _blocks(prof, pol, ws, "Write", proj + "/other/x.md"))
        check("read_under_umbrella", not _blocks(prof, pol, ws, "Read", proj + "/other/x.md"))


def test_the_nearest_decides_between_two_narrowed_grants_not_their_union():
    with g._Workspace() as ws:
        proj = _world(ws)
        prof, pol = _pol(ws, narrowed=[(proj, "r", True), (proj + "/sub", "w", True)])
        check("read_under_w_child_refused", _blocks(prof, pol, ws, "Read", proj + "/sub/x.md"))
        check("write_under_w_child", not _blocks(prof, pol, ws, "Write", proj + "/sub/x.md"))
        check("read_under_r_parent", not _blocks(prof, pol, ws, "Read", proj + "/other/x.md"))


def test_an_exact_grant_decides_only_its_own_path():
    with g._Workspace() as ws:
        proj = _world(ws)
        f = proj + "/sub/f.md"
        prof, pol = _pol(ws, narrowed=[(f, "r", False)], full=[_full(proj)])
        check("exact_file_capped", _blocks(prof, pol, ws, "Write", f))
        check("exact_file_read", not _blocks(prof, pol, ws, "Read", f))
        check("sibling_falls_to_parent", not _blocks(prof, pol, ws, "Write", proj + "/sub/g.md"))


def test_grants_on_one_node_union():
    with g._Workspace() as ws:
        proj = _world(ws)
        prof, pol = _pol(ws, narrowed=[(proj + "/sub", "r", True), (proj + "/sub", "w", True)],
                         full=[_full(proj)])
        check("read", not _blocks(prof, pol, ws, "Read", proj + "/sub/x.md"))
        check("write", not _blocks(prof, pol, ws, "Write", proj + "/sub/x.md"))
        check("delete_refused", _blocks(prof, pol, ws, "git_clean", proj + "/sub/x.md"))


def test_a_shell_line_takes_the_nearest_grant_for_every_path_it_reaches():
    with g._Workspace() as ws:
        proj = _world(ws)
        prof, pol = _pol(ws, narrowed=[(proj + "/sub", "r", True)], full=[_full(proj)])
        v = g._verdict(prof, pol, ws, "Bash", command=f"cp {proj}/a.txt {proj}/sub/y.txt")
        check("write_into_child_refused", v.blocks, str(v))
        check("names_the_path", "sub/y.txt" in v.reason and "#1386" in v.reason, v.reason)
        check("read_in_child", not _blocks(prof, pol, ws, "Bash", command=f"cat {proj}/sub/y.txt"))
        check("write_outside_child", not _blocks(prof, pol, ws, "Bash",
                                                 command=f"cp {proj}/a.txt {proj}/other/b.txt"))


def test_a_workspace_direct_root_takes_part_in_the_walk():
    """The bare-name spelling (part B v2) is a node like any other, in both directions."""
    with g._Workspace() as ws:
        gov = ws + "/governance"
        prof, pol = _pol(ws, narrowed=[(gov + "/hestia", "r", True)], full=[_full(gov)])
        check("full_bare_name_parent_capped", _blocks(prof, pol, ws, "Write", gov + "/hestia/x.py"))
        check("rest_of_parent", not _blocks(prof, pol, ws, "Write", gov + "/journal.md"))
        sc = ws + "/shared-context"
        prof, pol = _pol(ws, narrowed=[(sc, "r", True)], full=[_full(sc + "/forum")])
        check("narrowed_bare_name_parent_full_child", not _blocks(prof, pol, ws, "Write", sc + "/forum/n.md"))
        check("narrowed_bare_name_parent", _blocks(prof, pol, ws, "Write", sc + "/other.md"))


def test_without_nesting_nothing_changes():
    """No narrowed grant at or beneath another node: part B's verdicts exactly."""
    with g._Workspace() as ws:
        proj = _world(ws)
        prof, pol = _pol(ws, narrowed=[(_forum := ws + "/shared-context/forum", "r", True)],
                         full=[_full(proj)])
        check("full_write", not _blocks(prof, pol, ws, "Write", proj + "/sub/x.md"))
        check("narrowed_read", not _blocks(prof, pol, ws, "Read", _forum + "/t.md"))
        check("narrowed_write_refused", _blocks(prof, pol, ws, "Write", _forum + "/t.md"))
        check("shell_write_in_full", not _blocks(prof, pol, ws, "Bash",
                                                 command=f"cp {proj}/a {proj}/sub/b"))


def test_nearest_grant_modes_is_the_gates_answer_for_consumers():
    with g._Workspace() as ws:
        proj = _world(ws)
        _prof, pol = _pol(ws, narrowed=[(proj + "/sub", "r", True)], full=[_full(proj)])
        check("child", core.nearest_grant_modes(pol, ws, proj + "/sub/x") == "r")
        check("parent", core.nearest_grant_modes(pol, ws, proj + "/other/x") == "rwed")
        check("none", core.nearest_grant_modes(pol, ws, ws + "/hestia/x") is None)


def test_an_act_on_the_parent_cannot_reach_a_narrower_child():
    """nomad's HOLD on #1394 (Nova corroborated): the act was judged by the path it NAMED, so an act
    aimed at the parent reached the narrowed child. His table, both child shapes, with the direct
    controls that already held."""
    with g._Workspace() as ws:
        proj = _world(ws)
        secret = proj + "/sub/secret.md"
        # a write-only drop under a full parent
        prof, pol = _pol(ws, narrowed=[(proj + "/sub", "w", True)], full=[_full(proj)])
        check("w_child_direct_read_refused", _blocks(prof, pol, ws, "Read", secret))
        v = g._verdict(prof, pol, ws, "Grep", path=proj)
        check("w_child_grep_on_parent_refused", v.blocks, str(v))
        check("names_the_child", "sub" in v.reason and "#1386" in v.reason, v.reason)
        check("w_child_recursive_grep_refused", _blocks(prof, pol, ws, "Bash", command=f"grep -r child {proj}"))
        check("w_child_cat_refused", _blocks(prof, pol, ws, "Bash", command=f"cat {secret}"))
        check("w_child_write_in_child_ok", not _blocks(prof, pol, ws, "Write", secret))
        check("parent_file_read_still_ok", not _blocks(prof, pol, ws, "Read", proj + "/other/x.md"))
        # a read-only child under a full parent
        prof, pol = _pol(ws, narrowed=[(proj + "/sub", "r", True)], full=[_full(proj)])
        check("r_child_direct_write_refused", _blocks(prof, pol, ws, "Write", secret))
        v = g._verdict(prof, pol, ws, "Bash",
                       command=f"find {proj} -name '*.md' -exec sed -i s/a/b/ {{}} +")
        check("r_child_find_sed_on_parent_refused", v.blocks, str(v))
        check("r_child_grep_on_parent_ok", not _blocks(prof, pol, ws, "Grep", proj),
              "a reader over the parent may read an r child")
        check("r_child_git_clean_parent_refused", _blocks(prof, pol, ws, "git_clean", proj))


def test_a_reserved_floor_still_cannot_widen_a_child_through_its_parent():
    """The floor rides `scopes` as full nodes, safe because the daemon withholds an overlapping floor
    entry (#1387). If that withholding were reverted, the gate must still refuse an ancestor act
    that reaches a narrowed child: the child is a node beneath any floor entry above it."""
    with g._Workspace() as ws:
        parent, child = ws + "/shared-context", ws + "/shared-context/forum"
        fake = mt._std_stub(ws, generation=3)
        fake.extra["hestia_scope_status"]["grants_by_mode"] = [g._grant(child, "w")]
        fake.extra["hestia_scope_status"]["society_floor"] = [{"path": parent, "recursive": True}]
        m._discover_endpoint = lambda: "http://fake/mcp"
        m._McpHttp = lambda ep, dl: fake
        snap = m.fetch_policy_snapshot("cbp-being", use_cache=False)
        prof, pol = g._policy(snap)
        check("reserved_floor_grep_parent_refused", _blocks(prof, pol, ws, "Grep", parent))
        check("reserved_floor_direct_child_read_refused", _blocks(prof, pol, ws, "Read", child + "/n.md"))


ALL = [
    test_an_act_on_the_parent_cannot_reach_a_narrower_child,
    test_a_reserved_floor_still_cannot_widen_a_child_through_its_parent,
    test_a_narrowed_child_caps_a_full_parent,
    test_a_read_only_umbrella_does_not_erase_a_full_child,
    test_the_nearest_decides_between_two_narrowed_grants_not_their_union,
    test_an_exact_grant_decides_only_its_own_path,
    test_grants_on_one_node_union,
    test_a_shell_line_takes_the_nearest_grant_for_every_path_it_reaches,
    test_a_workspace_direct_root_takes_part_in_the_walk,
    test_without_nesting_nothing_changes,
    test_nearest_grant_modes_is_the_gates_answer_for_consumers,
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
