import dataclasses
import json
import os
import pathlib
import sys

ROOT = pathlib.Path("/home/dp/ai-workspace/hestia/scratchpad/kimi-review-hestia-1474")
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
sys.path.insert(0, str(ROOT / "tools"))
import hestia_gate_core as core
import hestia_single_gate as single
import grant_modes_gate_test as fixture


def remote(tool, owner, ws):
    event = single.normalized_event(single.GateEvent(
        tool=tool,
        tool_input={"repository_full_name": owner + "/project", "path": "README.md"},
        cwd=ws,
    ))
    assert event.repos == ["project"] and event.repo_full == [owner + "/project"]
    return event


def verdict(event, prof, pol, ws):
    result = core.evaluate(event, prof, ws, policy=pol)
    return {"allow": not result.blocks, "rule": result.rule}


with fixture._Workspace() as ws:
    project = pathlib.Path(ws) / "project"
    project.mkdir()
    (project / "README.md").write_text("synthetic")
    (pathlib.Path(ws) / "outside.md").write_text("synthetic")
    no_grant = fixture._snapshot(ws)
    recursive = fixture._snapshot(ws, standing=[{"path": str(project), "recursive": True}])
    exact = fixture._snapshot(ws, standing=[{"path": str(project), "recursive": False}])
    prof, none_policy = fixture._policy(no_grant)
    _, recursive_policy = fixture._policy(recursive)
    _, exact_policy = fixture._policy(exact)
    assert recursive["in_scope"] == ["project"], recursive["in_scope"]
    assert exact["in_scope"] == ["path:" + str(project)], exact["in_scope"]

    rows = {}
    for label, policy in (("none", none_policy), ("recursive", recursive_policy), ("exact", exact_policy)):
        for owner in ("me", "foreign-owner"):
            for action, tool in (("read", "mcp__github__get_file"), ("delete_file", "mcp__github__delete_file")):
                key = f"{label}:{owner}:{action}"
                rows[key] = verdict(remote(tool, owner, ws), prof, policy, ws)

    local_read = single.normalized_event(single.GateEvent(
        tool="Read", tool_input={"file_path": str(project / "README.md")}, cwd=ws))
    sibling_read = single.normalized_event(single.GateEvent(
        tool="Read", tool_input={"file_path": str(pathlib.Path(ws) / "outside.md")}, cwd=ws))
    rows["local:no_grant"] = verdict(local_read, prof, none_policy, ws)
    rows["local:recursive_inside"] = verdict(local_read, prof, recursive_policy, ws)
    rows["local:recursive_sibling"] = verdict(sibling_read, prof, recursive_policy, ws)

    legacy = dataclasses.replace(none_policy, scope=tuple(none_policy.scope) + ("project",))
    qualified = dataclasses.replace(none_policy, scope=tuple(none_policy.scope) + ("me/project",))
    rows["legacy:foreign-owner:read"] = verdict(remote("mcp__github__get_file", "foreign-owner", ws), prof, legacy, ws)
    rows["qualified:me:read"] = verdict(remote("mcp__github__get_file", "me", ws), prof, qualified, ws)
    rows["qualified:foreign-owner:read"] = verdict(remote("mcp__github__get_file", "foreign-owner", ws), prof, qualified, ws)

    original_mapper = fixture.m._scope_entry_for_grant
    try:
        fixture.m._scope_entry_for_grant = lambda path, recursive=False: (
            "path:" + path.strip().rstrip("/") + ("/**" if recursive else ""))
        path_only = fixture._snapshot(ws, standing=[{"path": str(project), "recursive": True}])
    finally:
        fixture.m._scope_entry_for_grant = original_mapper
    _, path_only_policy = fixture._policy(path_only)
    assert path_only["in_scope"] == ["path:" + str(project) + "/**"], path_only["in_scope"]
    rows["path_only:foreign-owner:read"] = verdict(remote("mcp__github__get_file", "foreign-owner", ws), prof, path_only_policy, ws)
    rows["path_only:foreign-owner:delete_file"] = verdict(remote("mcp__github__delete_file", "foreign-owner", ws), prof, path_only_policy, ws)
    rows["path_only:local_inside"] = verdict(local_read, prof, path_only_policy, ws)
    rows["path_only:local_sibling"] = verdict(sibling_read, prof, path_only_policy, ws)

    for row in rows.values():
        if not row["allow"]:
            assert row["rule"] == "mrh.repo" or row["rule"] == "mrh.path", row
    assert not rows["none:foreign-owner:read"]["allow"]
    assert not rows["none:foreign-owner:delete_file"]["allow"]
    assert rows["recursive:foreign-owner:read"]["allow"]
    assert rows["recursive:foreign-owner:delete_file"]["allow"]
    assert not rows["exact:foreign-owner:read"]["allow"]
    assert not rows["local:no_grant"]["allow"]
    assert rows["local:recursive_inside"]["allow"]
    assert not rows["local:recursive_sibling"]["allow"]
    assert rows["legacy:foreign-owner:read"]["allow"]
    assert rows["qualified:me:read"]["allow"]
    assert not rows["qualified:foreign-owner:read"]["allow"]
    assert not rows["path_only:foreign-owner:read"]["allow"]
    assert not rows["path_only:foreign-owner:delete_file"]["allow"]
    assert rows["path_only:local_inside"]["allow"]
    assert not rows["path_only:local_sibling"]["allow"]
    print(json.dumps({"head": "83f57eb8dc3da6b3e44220b8e527207d488344dd", "rows": rows}, indent=2, sort_keys=True))
    print("CONFIRMED: recursive local path projection authorizes same-named foreign remote read and mutation")
