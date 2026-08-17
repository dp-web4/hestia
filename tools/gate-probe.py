#!/usr/bin/env python3
"""Drive a member's gate with a synthetic payload — and exonerate the ding it causes.

WHY THIS EXISTS. Measuring a gate means making it deny something, and a deny lands on the
MEMBER's conduct record. On 2026-07-26 that happened to codex three separate times in one
session: instrumenting the gate for the bypass catalogue, verifying a NameError fix, then
verifying the `attempted` field. Each round left codex looking worse at governance while
it was, in dp's words, an exemplary collaborator — and each round needed a manual
exoneration afterwards that was easy to forget and easy to get wrong (the first attempt
double-nested the payload and silently did nothing).

    "poor codex :) you need to exonerate it again" — dp, 2026-07-26

The member is not the defect. The PRACTICE was: a probe that writes to someone else's
record and relies on the prober to remember. This makes the cleanup part of the act.

WHAT IT DOES NOT DO. It does not suppress the deny, hide it, or witness under a fake
identity. The deny happens, is enforced, and is recorded — that is the behaviour under
test and faking it would make the probe worthless. What follows is a witnessed
`exoneration` naming this probe as the cause, so the record ends up TRUE rather than
empty: the reach happened, and it was the prober's, not the member's.

A deliberate non-feature: there is no "probe mode" flag in the gate itself. A gate that
skipped conduct accounting when asked nicely would be a one-env-var bypass of the trust
record — precisely the class catalogued in docs/GATE_BYPASS_CATALOG.md. The asymmetry is
the point: probing is cheap, but it is never invisible.

    ./gate-probe.py ~/.codex/hooks/pre_tool_use.py codex 'rm -rf /x/DOES-NOT-EXIST'
    ./gate-probe.py ~/.codex/hooks/pre_tool_use.py codex --json payload.json
    ./gate-probe.py ... --no-exonerate     # leave the ding (you are auditing conduct)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

MCP = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
API = MCP.rsplit("/mcp", 1)[0]
WORKSPACE = os.environ.get("HESTIA_WORKSPACE")


def _post(url, body, hdrs=None, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json, text/event-stream",
                                          **(hdrs or {})})
    r = urllib.request.urlopen(req, timeout=timeout)
    return r.read().decode(), r.headers.get("mcp-session-id")


def _mcp_result(raw):
    for line in raw.splitlines():
        if line.startswith("data: {"):
            p = json.loads(line[6:])
            if "result" in p:
                return json.loads(p["result"]["content"][0]["text"])
            if "error" in p:
                return {"error": p["error"]}
    return None


def operator_token():
    """Operator session, for reading the chain to find what the probe caused."""
    from nacl.signing import SigningKey  # only needed on the read path
    key = json.load(open(os.path.expanduser("~/.hestia/operator.key")))
    sk = SigningKey(bytes.fromhex(key["secret_key_hex"])[:32])
    ch = json.loads(_post(f"{API}/api/operator/challenge", {})[0])["challenge"]
    sess = json.loads(_post(f"{API}/api/operator/session", {
        "lct_id": key["lct_id"], "challenge": ch,
        "signature": sk.sign(ch.encode()).signature.hex()})[0])
    return sess["token"]


def denies_for(tok, plugin, since_pos):
    req = urllib.request.Request(
        f"{API}/api/chain?limit=500&range=hour&event_type=policy_decision",
        headers={"Authorization": f"Bearer {tok}"})
    c = json.loads(urllib.request.urlopen(req, timeout=30).read())
    rows = c if isinstance(c, list) else (c.get("entries") or c.get("chain") or [])
    return [e for e in rows
            if e.get("decision") == "deny"
            and (e.get("plugin_id") or "").startswith(plugin)
            # >= not >: `chain_length` is a COUNT, so the next entry written takes
            # position == the length we sampled. With `>` the probe's own deny was
            # excluded by exactly one and the harness reported "0 denies caused" while
            # the ding sat on the record — a cleanup tool that silently cleans nothing.
            and (e.get("chain_position") or 0) >= since_pos]


def chain_head(tok):
    req = urllib.request.Request(f"{API}/api/dashboard?range=hour",
                                 headers={"Authorization": f"Bearer {tok}"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())["society"]["chain_length"]


def exonerate(hashes, subject, note):
    """Witness one exoneration per deny, authored as claude-code.

    The author MUST NOT be the subject — derivation refuses a self-exoneration, and that
    refusal is the integrity of the whole mechanism. If you probe claude-code's gate with
    this script, change the author or the exonerations will be silently ignored.
    """
    author = "claude-code" if subject != "claude-code" else "hestia-router"
    _, sid = _post(MCP, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "gate-probe", "version": "1"}}})
    h = {"mcp-session-id": sid} if sid else {}
    _post(MCP, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)

    def call(tool, args):
        raw, _ = _post(MCP, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                             "params": {"name": tool, "arguments": args}}, h)
        return _mcp_result(raw)

    conn = call("hestia_connect", {"plugin_id": author, "host_agent": author,
                                   "instance_name": "gate-probe"}) or {}
    sess = conn.get("sessionId") or conn.get("session_id")
    if not sess:
        print(f"  ! could not connect as {author}; denies left on {subject}'s record")
        return 0
    ok = 0
    for hsh in hashes:
        # NOTE the shape: hestia_request_witness already wraps event_data under `data`.
        # Wrapping it again here produces data.data.deny_hash, which derivation never
        # reads — six exonerations were witnessed and silently inert that way on
        # 2026-07-26. Pass the fields flat.
        r = call("hestia_request_witness", {
            "session_id": sess, "event_type": "exoneration",
            "event_data": {"deny_hash": hsh,
                           "ref": "hestia/tools/gate-probe.py — synthetic gate probe",
                           "reason": note}}) or {}
        ok += bool(r.get("witnessEntryHash"))
    return ok


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if len(args) < 3:
        print(__doc__)
        return 2
    if not WORKSPACE:
        print("HESTIA_WORKSPACE is required; the probe will not guess installation scope", file=sys.stderr)
        return 2
    gate, subject, rest = args[0], args[1], args[2]
    if "--json" in flags:
        payload = json.load(open(rest))
    else:
        payload = {"hook_event_name": "PreToolUse", "session_id": "gate-probe",
                   "cwd": WORKSPACE, "tool_name": "bash",
                   "tool_input": {"command": rest}}

    tok = operator_token()
    before = chain_head(tok)

    proc = subprocess.run([sys.executable, os.path.expanduser(gate)],
                          input=json.dumps(payload), capture_output=True, text=True,
                          env={**os.environ, "HESTIA_WORKSPACE": WORKSPACE}, timeout=60)
    verdict = "DENY" if proc.returncode == 2 else ("ALLOW" if proc.returncode == 0 else f"rc={proc.returncode}")
    print(f"gate: {verdict}")
    if proc.stderr.strip():
        print(f"  {proc.stderr.strip()[:300]}")

    time.sleep(2)  # the gate witnesses fire-and-forget
    caused = denies_for(tok, subject, before)
    print(f"denies this probe put on {subject}: {len(caused)}")
    for e in caused:
        print(f"  #{e['chain_position']} {(e.get('attempted') or e.get('reason') or '')[:70]}")

    if not caused:
        return 0
    if "--no-exonerate" in flags:
        print("  --no-exonerate: left on the record")
        return 0
    n = exonerate([e["hash"] for e in caused], subject,
                  f"Not {subject} conduct. A synthetic payload from hestia/tools/gate-probe.py "
                  f"drove this gate directly to measure its behaviour. The reach was the "
                  f"prober's; only the record landed on {subject}.")
    print(f"exonerated {n}/{len(caused)} — {subject}'s conduct record is clean again")
    return 0


if __name__ == "__main__":
    sys.exit(main())
