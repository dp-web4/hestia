#!/usr/bin/env python3
"""Generate and check #1449's portable chain fixtures against a disposable real daemon.

--write creates a fresh temporary Hestia home, performs real MCP and operator-signed calls,
exports the signed segment, and writes valid/altered/swapped/missing-key fixtures. Without
--write it only runs the offline CLI checks against an existing fixture directory. No live
home, service, credential or daemon is used.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("valid", "altered", "swapped", "missing-key")
EXPECTED = {"valid": ("valid", 0), "altered": ("tampered", 1),
            "swapped": ("tampered", 1), "missing-key": ("unverifiable", 1)}
# This harness owns its time budget. hestia_gate_mechanism's default per-request cap
# (HESTIA_PRE_REQUEST_TIMEOUT_S, 5 s) is the gate hook's own deadline: right for a hook that must
# answer fast, wrong for a cold disposable daemon in a debug build on a loaded runner, where
# `hestia_connect` alone has outlasted it. So every MCP call here gets an explicit cap that the
# gate's environment cannot shorten, inside one whole-run deadline.
MCP_CALL_TIMEOUT_S = 60.0
MCP_RUN_DEADLINE_S = 300.0
MCP_READY_DEADLINE_S = 120.0


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def unwrap(payload: dict) -> dict:
    result = payload.get("result") or {}
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    text = (result.get("content") or [{}])[0].get("text")
    if not text:
        raise RuntimeError(f"tool returned no content: {payload}")
    return json.loads(text)


def wait_for_mcp(mechanism, endpoint: str, daemon: subprocess.Popen, log_path: Path):
    """Return an initialized MCP client once the daemon lists `hestia_connect`.

    `/api/version` answering proves the HTTP listener is up, not that the MCP surface can serve a
    tool call. Retry the handshake and `tools/list` until the tool is listed, and fail by name if
    it never is."""
    give_up = time.monotonic() + MCP_READY_DEADLINE_S
    last = "no attempt completed"
    while time.monotonic() < give_up:
        if daemon.poll() is not None:
            raise RuntimeError(f"daemon exited before MCP was ready: {log_path.read_text()}")
        mcp = mechanism._McpHttp(endpoint, time.monotonic() + MCP_RUN_DEADLINE_S,
                                 request_cap=MCP_CALL_TIMEOUT_S)
        try:
            if "result" not in mcp.initialize():
                raise RuntimeError("initialize returned no result")
            mcp.initialized()
            listed = mcp._request({"jsonrpc": "2.0", "id": mcp._id(),
                                   "method": "tools/list", "params": {}}) or {}
            names = {t.get("name") for t in (listed.get("result") or {}).get("tools") or []}
            if "hestia_connect" in names:
                return mcp
            last = f"tools/list did not list hestia_connect ({len(names)} tools)"
        except Exception as exc:  # not ready yet: retry until the readiness deadline
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.25)
    raise RuntimeError(f"MCP did not become ready within {MCP_READY_DEADLINE_S:.0f}s: {last}")


def call(mcp, name: str, arguments: dict) -> dict:
    """One MCP tool call that names the tool and the elapsed time when it does not answer."""
    started = time.monotonic()
    try:
        return unwrap(mcp.call_tool(name, arguments))
    except (TimeoutError, OSError) as exc:
        raise RuntimeError(f"{name} did not answer after {time.monotonic() - started:.1f}s "
                           f"(per-call cap {MCP_CALL_TIMEOUT_S:.0f}s): {exc}") from exc


def run(args: list[str], env: dict, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, env=env, text=True, capture_output=True, timeout=90, **kwargs)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def generate_valid(binary: Path, home: Path, passphrase: str) -> dict:
    env = dict(os.environ, HESTIA_HOME=str(home), HESTIA_PASSPHRASE=passphrase)
    init = run([str(binary), "init", "--ai"], env)
    if init.returncode:
        raise RuntimeError(f"init failed: {init.stdout}\n{init.stderr}")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log = (home / "daemon.log").open("w")
    daemon = subprocess.Popen([str(binary), "serve", "--bind", f"127.0.0.1:{port}"],
                              env=env, stdout=log, stderr=subprocess.STDOUT)
    endpoint = f"http://127.0.0.1:{port}/mcp"
    try:
        for _ in range(300):
            if daemon.poll() is not None:
                raise RuntimeError(f"daemon exited during startup: {(home / 'daemon.log').read_text()}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=0.2):
                    break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("daemon did not become ready")

        mechanism = load("chain_segment_mechanism", ROOT / "plugins" / "_shared" / "hestia_gate_mechanism.py")
        mcp = wait_for_mcp(mechanism, endpoint, daemon, home / "daemon.log")
        connected = call(mcp, "hestia_connect", {
            "plugin_id": "fixture-member", "host_agent": "chain-segment-smoke",
            "host_agent_version": "1", "requested_role": "citizen",
        })
        session = connected["sessionId"]

        seed = load("chain_segment_seed", ROOT / "tools" / "seed_seat_config.py")
        operator = seed.Operator(f"http://127.0.0.1:{port}", home / "operator.key")
        operator.open_session()
        status, grant = operator.call("POST", "/api/scope/grant", {
            "plugin_id": "fixture-member", "path": "/fixture", "recursive": True,
            "modes": "r", "reason": "install-smoke fixture grant",
        })
        if status != 200:
            raise RuntimeError(f"grant failed ({status}): {grant}")

        outside = home.parent / "outside" / "book.txt"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("denied fixture content\n", encoding="utf-8")
        denied_path = str(outside)
        for decision, target in (("allow", "/fixture/book.txt"), ("deny", denied_path)):
            answer = call(mcp, "hestia_witness_decision", {
                "plugin_id": "fixture-member", "decision": decision,
                "adjudicator": "install-smoke", "reason": f"fixture {decision}",
                "rule_id": "mrh.path", "tool_name": "Read", "target": target,
                "attempted": f"Read -> {target}", "session_id": session,
            })
            if answer.get("_hestia_error") or not answer.get("witnessEntryHash"):
                raise RuntimeError(f"{decision} witness failed: {answer}")

        claim = call(mcp, "hestia_scope_claim", {
            "plugin_id": "fixture-member", "session_id": session,
            "path": denied_path, "rule": "mrh.path", "tool_name": "Read",
            "act": f"Read -> {denied_path}", "act_digest": "1" * 64, "spend": False,
        })
        if claim.get("verdict") != "not_asked" or not claim.get("refusal_id"):
            raise RuntimeError(f"scope refusal was not recorded: {claim}")
        opened = call(mcp, "hestia_scope_escalate", {
            "plugin_id": "fixture-member", "session_id": session,
            "refusal_id": claim["refusal_id"],
            "reason": "install-smoke escalation for the denied read",
        })
        if opened.get("verdict") != "opened":
            raise RuntimeError(f"scope escalation failed: {opened}")

        status, chain = operator.call("GET", "/api/chain?limit=500")
        if status != 200 or not chain.get("entries"):
            raise RuntimeError(f"chain read failed ({status}): {chain}")
        tail = max(e["chain_position"] for e in chain["entries"])
        exported = run([str(binary), "chain-export", "--from", "0", "--to", str(tail)], env)
        if exported.returncode:
            raise RuntimeError(f"export failed: {exported.stdout}\n{exported.stderr}")
        segment = json.loads(exported.stdout)
        kinds = {e["event_type"] for e in segment["entries"]}
        required = {"scope_granted", "policy_allow", "policy_decision", "scope_requested"}
        if not required.issubset(kinds):
            raise RuntimeError(f"fixture is missing required event kinds {required - kinds}")
        if not segment["signatures"]:
            raise RuntimeError("fixture has no signed rows")
        whole = run([str(binary), "chain-verify"], env)
        if whole.returncode:
            raise RuntimeError(f"whole-chain verify failed: {whole.stdout}\n{whole.stderr}")
        return segment
    finally:
        if daemon.poll() is None:
            daemon.terminate()
            try:
                daemon.wait(timeout=10)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait(timeout=5)
        log.close()


def variants(valid: dict) -> dict[str, dict]:
    altered = json.loads(json.dumps(valid))
    altered["entries"][1]["event_data"]["fixture_tamper"] = "content changed"
    altered["entries"][1]["event_data_json"] = json.dumps(
        altered["entries"][1]["event_data"], separators=(",", ":"), ensure_ascii=False)
    swapped = json.loads(json.dumps(valid))
    swapped["entries"].insert(1, swapped["entries"].pop(2))
    missing = json.loads(json.dumps(valid))
    missing["signatures"][0]["witness_public_key"] = ""
    return {"valid": valid, "altered": altered, "swapped": swapped, "missing-key": missing}


def anchor_args(segment: dict) -> list[str]:
    args = ["--expect-chain-id", segment["chain_id"],
            "--expect-previous-hash", segment["previous_hash"],
            "--expect-end-hash", segment["entries"][-1]["hash"]]
    for key in sorted({rec["witness_public_key"] for rec in segment["signatures"]}):
        args.extend(["--trusted-witness-key", key])
    return args


def check(binary: Path, fixtures: Path, isolated_home: Path) -> None:
    isolated_home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HESTIA_HOME=str(isolated_home))
    for name in NAMES:
        path = fixtures / f"{name}.json"
        segment = json.loads(path.read_text(encoding="utf-8"))
        if name == "valid":
            unanchored = run([str(binary), "chain-verify", str(path)], env)
            report = json.loads(unanchored.stdout)
            if (report.get("status") != "unverifiable" or report.get("complete") is not False
                    or report.get("provenance") != "unanchored"):
                raise RuntimeError(f"unanchored segment was presented as authenticated: {report}")
        result = run([str(binary), "chain-verify", str(path)] + anchor_args(segment), env)
        expected, nonzero = EXPECTED[name]
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{name}: no JSON verdict: {result.stdout}\n{result.stderr}") from exc
        if report.get("status") != expected or bool(result.returncode) != bool(nonzero):
            raise RuntimeError(
                f"{name}: expected {expected}/exit {nonzero}, got {report.get('status')}/exit "
                f"{result.returncode}: {result.stdout}\n{result.stderr}")
        if name == "altered" and not any("hash mismatch" in s for s in report.get("tampered", [])):
            raise RuntimeError(f"altered fixture did not name its hash failure: {report}")
        if name == "swapped" and not any("ordering mismatch" in s for s in report.get("tampered", [])):
            raise RuntimeError(f"swapped fixture did not name its ordering failure: {report}")
        if name == "missing-key" and not any("signing key is absent" in s for s in report.get("unverifiable", [])):
            raise RuntimeError(f"missing-key fixture did not name its absent key: {report}")

    oversized = isolated_home / "oversized.json"
    oversized.write_text(" " * (16 * 1024 * 1024 + 1), encoding="utf-8")
    result = run([str(binary), "chain-verify", str(oversized)], env)
    if result.returncode == 0 or "exceeding the" not in result.stderr:
        raise RuntimeError(f"oversized segment was not bounded: {result.stdout}\n{result.stderr}")
    recursive = isolated_home / "recursive.json"
    recursive.write_text("[" * 200 + "]" * 200, encoding="utf-8")
    result = run([str(binary), "chain-verify", str(recursive)], env)
    if result.returncode == 0 or json.loads(result.stdout).get("status") != "unverifiable":
        raise RuntimeError(f"recursive JSON was not rejected safely: {result.stdout}\n{result.stderr}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--fixtures-dir", required=True, type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    binary = args.binary.resolve()
    fixtures = args.fixtures_dir.resolve()
    fixtures.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hestia-chain-segment-") as tmp:
        if args.write:
            valid = generate_valid(binary, Path(tmp) / "home", secrets.token_hex(16))
            for name, segment in variants(valid).items():
                write_json(fixtures / f"{name}.json", segment)
        check(binary, fixtures, Path(tmp) / "offline-home")
    print("chain-segment: ok (valid, altered, swapped, missing-key)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        traceback.print_exc()
        print(f"chain-segment: FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
