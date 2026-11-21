#!/usr/bin/env python3
import json
import os
import pathlib
import select
import shutil
import subprocess
import sys
import tempfile

HESTIA = pathlib.Path("/home/dp/ai-workspace/hestia")
SRC = HESTIA / "scratchpad/kimi-856-v3"
TARGET = HESTIA / "scratchpad/kimi-854-review"
CLI = "/home/dp/ai-workspace/GitNexus/gitnexus/dist/cli/index.js"
DIFF = "/tmp/kimi-856-v4-governed-a6bf4d09.diff"
GATE_CODE = r'''
import json, os
import hestia_single_gate as single
import hestia_gate_core as core
event = single.normalized_event(single.GateEvent(
    tool="mcp__gitnexus__detect_changes",
    tool_input={"repo": os.environ["REPO_INPUT"], "scope": "staged"},
    cwd=os.getcwd(),
))
profile = single.GateProfile(member_id="kimi-code", identity_path="").core_profile()
policy = core.AgentPolicy(member_id="kimi-code", scope=("kimi-854-review",), source="live-review")
verdict = core.evaluate(event, profile, workspace=os.getcwd(), policy=policy)
print(json.dumps({"paths": event.paths, "repos": event.repos,
                  "decision": verdict.decision, "rule": verdict.rule, "blocks": verdict.blocks}))
'''


def request(proc, payload, timeout=90):
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    wanted = payload.get("id")
    if wanted is None:
        return None
    while True:
        ready, _, _ = select.select([proc.stdout], [], [], timeout)
        if not ready:
            raise TimeoutError(f"MCP response timed out: {payload}")
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError(f"MCP exited early: {proc.poll()}")
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if wanted is None or msg.get("id") == wanted:
            return msg


def call(proc, ident, name, args):
    return request(proc, {"jsonrpc": "2.0", "id": ident, "method": "tools/call",
                          "params": {"name": name, "arguments": args}})


def body(response):
    text = response["result"]["content"][0]["text"]
    raw = text.split("\n\n---\n", 1)[0]
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = {"text": raw}
    return value, response["result"].get("isError", False)


def main():
    with tempfile.TemporaryDirectory(prefix="kimi-856-live-", dir=HESTIA / "scratchpad") as raw:
        root = pathlib.Path(raw)
        for variant in ("base", "v4"):
            dest = root / variant / "plugins"
            dest.parent.mkdir()
            shutil.copytree(SRC / "plugins/_shared", dest / "_shared")
        subprocess.run(["git", "apply", DIFF], cwd=root / "v4", check=True,
                       capture_output=True, text=True)
        server = root / "server"
        server.mkdir()
        (server / "~").mkdir()
        tilde_target = server / "~" / TARGET.name
        tilde_target.symlink_to(TARGET, target_is_directory=True)
        results = {}
        for arm, repo_input, registered in (
            ("relative", os.path.relpath(TARGET, server), TARGET),
            ("tilde", f"~/{TARGET.name}", tilde_target),
        ):
            home = root / f"home-{arm}"
            home.mkdir()
            entry = {
                "name": "outside-target",
                "path": str(registered),
                "storagePath": str(registered / ".gitnexus"),
                "indexedAt": "2026-11-05T03:19:36.381Z",
                "lastCommit": "a58c236124bcd7434718941a489d3bedd8652496",
                "stats": {"files": 2614, "nodes": 146876, "edges": 211667,
                          "communities": 1563, "processes": 233, "embeddings": 0},
            }
            (home / "registry.json").write_text(json.dumps([entry]), encoding="utf-8")
            gates = {}
            for variant in ("base", "v4"):
                env = os.environ.copy()
                env["PYTHONPATH"] = str(root / variant / "plugins/_shared")
                env["REPO_INPUT"] = repo_input
                run = subprocess.run([sys.executable, "-c", GATE_CODE], cwd=server, env=env,
                                     check=True, capture_output=True, text=True)
                gates[variant] = json.loads(run.stdout)
            env = os.environ.copy()
            env["GITNEXUS_HOME"] = str(home)
            proc = subprocess.Popen(
                ["node", CLI, "mcp"], cwd=server, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
            try:
                request(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                               "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                          "clientInfo": {"name": "kimi-856-live-review", "version": "1"}}})
                request(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
                overview_response = call(proc, 2, "overview", {
                    "repo": repo_input, "showClusters": False, "showProcesses": False,
                })
                overview, overview_error = body(overview_response)
                detect_response = call(proc, 3, "detect_changes", {"repo": repo_input, "scope": "staged"})
                detect, detect_error = body(detect_response)
            finally:
                proc.terminate()
                try:
                    _, stderr = proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    _, stderr = proc.communicate(timeout=5)
            results[arm] = {
                "repo_input": repo_input,
                "expected_registered_path": str(registered),
                "gate": gates,
                "mcp": {
                    "selected_name": overview.get("repo"),
                    "selected_path": overview.get("repoPath"),
                    "overview_error": overview_error,
                    "overview_detail": overview.get("error"),
                    "detect_summary": detect.get("summary"),
                    "detect_error": detect_error,
                    "detect_detail": detect.get("error"),
                },
                "backend_stderr_tail": stderr.splitlines()[-3:],
            }
            for variant in ("base", "v4"):
                assert gates[variant]["decision"] == "allow", (arm, variant, gates[variant])
                assert gates[variant]["paths"] == [], (arm, variant, gates[variant])
                assert gates[variant]["repos"] == [TARGET.name], (arm, variant, gates[variant])
            assert overview.get("repoPath") == str(registered), (arm, overview)
            assert overview.get("repo") == "outside-target", (arm, overview)
            assert not overview_error and not detect_error, (arm, overview, detect)
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
