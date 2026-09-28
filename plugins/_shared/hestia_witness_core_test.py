#!/usr/bin/env python3
"""The outcome witness is ONE core, and every harness's gate<->outcome seam closes through it.

findings/per-harness-witness-drift-2026-09-28.md measured the seam per harness from the delta
stream — warned acts closed by an outcome under the SAME action_id, since #977:
claude-code 1985/1986, kimi-code 0/37, codex 0/1, gemini no outcomes at all. Two halves were
missing, and this suite pins both, per harness, from the harness's REAL event shapes:

  * the gate half: only claude-code's gate cached the action it began. The cache now lives in
    hestia_gate_mechanism.query_society_safety(..., correlation_key=...), which every gate
    that reaches the daemon calls — so a gate that forgets the kwarg is caught in E;
  * the witness half: kimi keys on `tool_call_id` (not `tool_use_id`) and reports failures as
    `PostToolUseFailure`; gemini has no call id at all and its gate hands the governor a
    translated event. Each is a pair of events that must meet on one key.

Sections:
  A. the key: pre and post events of one call meet; two calls do not
  B. what the act was: failure shapes per harness
  C. THE SEAM, end to end per harness, against a stub daemon: the gate's begun action is the
     one the witness closes, and the witness begins nothing
  D. control: without the correlation key the same run goes cold — the kwarg is load-bearing
  E. no forks: every harness ships the byte-identical shim, declares it as its observe target,
     and every gate that asks the daemon passes the key

Run:  HESTIA_SHARED_DIR=plugins/_shared python3 plugins/_shared/hestia_witness_core_test.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import hestia_witness_core as core  # noqa: E402
import hestia_gate_mechanism as mech  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILURES.append(name)


# ---- real event shapes, one pair per harness (fields as measured on CBP 2026-09-28) ----------

def pairs() -> dict[str, tuple[dict, dict]]:
    claude_pre = {"hook_event_name": "PreToolUse", "session_id": "cc-sess", "tool_name": "Bash",
                  "tool_input": {"command": "make test"}, "tool_use_id": "toolu_01ABC"}
    claude_post = {**claude_pre, "hook_event_name": "PostToolUse",
                   "tool_response": {"stdout": "ok", "stderr": "", "interrupted": False}}
    # codex's pre-tool-use.command.input schema REQUIRES tool_use_id; its post carries a string.
    codex_pre = {"hook_event_name": "PreToolUse", "session_id": "019f-codex", "turn_id": "t1",
                 "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_use_id": "call_J0y1"}
    codex_post = {**codex_pre, "hook_event_name": "PostToolUse", "tool_response": ""}
    # kimi: toolCallId on both (kimi hook runner), snake-cased on the wire; failure is its own event.
    kimi_pre = {"hook_event_name": "PreToolUse", "session_id": "session_7176", "tool_name": "Bash",
                "tool_input": {"command": "rm -rf build"}, "tool_call_id": "tool_fB63llPw"}
    kimi_fail = {"hook_event_name": "PostToolUseFailure", "session_id": "session_7176",
                 "tool_name": "Bash", "tool_input": {"command": "rm -rf build"},
                 "tool_call_id": "tool_fB63llPw",
                 "error": {"code": "internal", "message": "exit status 1"}}
    # gemini: no call id. Its gate hands the governor a TRANSLATED event carrying `source_event`.
    g_input = {"command": "npm run build", "description": "build"}
    gemini_pre_translated = {"hook_event_name": "BeforeTool", "session_id": "gem-sess",
                             "tool_name": "Shell", "tool_input": dict(g_input),
                             "source_event": {"lineage": "gemini", "tool_name": "run_shell_command",
                                              "tool_input": dict(g_input)}}
    gemini_post = {"hook_event_name": "AfterTool", "session_id": "gem-sess",
                   "tool_name": "run_shell_command", "tool_input": dict(g_input),
                   "tool_response": {"llmContent": "built", "returnDisplay": "built"}}
    return {"claude-code": (claude_pre, claude_post), "codex": (codex_pre, codex_post),
            "kimi-code": (kimi_pre, kimi_fail), "gemini": (gemini_pre_translated, gemini_post)}


# ---- a stub daemon: records every tool call ----------------------------------------------------

class Daemon:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.n = 0
        daemon = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # noqa: D401
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                method = body.get("method")
                if "id" not in body:
                    self.send_response(202)
                    self.end_headers()
                    return
                if method == "initialize":
                    result = {"protocolVersion": "2024-11-05", "capabilities": {}}
                else:
                    name, args = body["params"]["name"], body["params"]["arguments"]
                    daemon.calls.append((name, args))
                    if name == "hestia_connect":
                        payload = {"sessionId": "S-1"}
                    elif name == "hestia_begin_action":
                        daemon.n += 1
                        payload = {"actionId": f"A-{daemon.n}"}
                    elif name == "hestia_query_policy":
                        payload = {"status": "decided", "decision": "warn", "reason": "stub"}
                    else:
                        payload = {"ok": True}
                    result = {"structuredContent": payload}
                out = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("mcp-session-id", "M-1")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/mcp"

    def named(self, name: str) -> list[dict]:
        return [a for n, a in self.calls if n == name]


def main() -> int:
    P = pairs()

    print("A. the key: one call's pre and post meet; two calls do not")
    for member, (pre, post) in P.items():
        check(f"A {member}: pre and post compute the same key",
              core.correlation_key(pre) == core.correlation_key(post),
              f"{core.correlation_key(pre)} != {core.correlation_key(post)}")
    k_pre, k_post = P["kimi-code"]
    check("A kimi keys on tool_call_id (the id kimi's runner sends), not a session fallback",
          core.correlation_key(k_post) == "tool_fB63llPw", core.correlation_key(k_post))
    g_pre, g_post = P["gemini"]
    other = {**g_post, "tool_input": {"command": "npm test"}}
    check("A gemini: a different call in the same session gets a different key",
          core.correlation_key(other) != core.correlation_key(g_post))
    check("A gemini: the translated pre event keys on the untranslated fields it carries",
          core.correlation_key({**g_pre, "source_event": None}) != core.correlation_key(g_post))
    check("A a key is a filename component",
          re.fullmatch(r"[A-Za-z0-9_.-]+", core.correlation_key({"tool_use_id": "../../etc/x"})) is not None,
          core.correlation_key({"tool_use_id": "../../etc/x"}))
    as_string = {**k_post, "tool_input": json.dumps(k_post["tool_input"])}
    del as_string["tool_call_id"]
    as_dict = dict(k_post)
    del as_dict["tool_call_id"]
    check("A a tool input handed over as a JSON string keys like the object",
          core.correlation_key(as_string) == core.correlation_key(as_dict))

    print("B. what the act was")
    core.configure(plugin_id="kimi-code")
    it = core.intent_from(k_post)
    check("B kimi PostToolUseFailure is witnessed (its fork read only PostToolUse)", it is not None)
    check("B and recorded as a failure with the harness's message",
          it and it["success"] is False and it["error"] == "exit status 1", json.dumps(it))
    ok_g = core.intent_from(g_post)
    check("B gemini AfterTool is witnessed", ok_g is not None and ok_g["success"] is True, json.dumps(ok_g))
    bad_g = core.intent_from({**g_post, "tool_response": {"error": {"message": "EACCES"}}})
    check("B gemini AfterTool with an error is a failure",
          bad_g and bad_g["success"] is False and "EACCES" in bad_g["error"], json.dumps(bad_g))
    check("B a non-outcome event is not witnessed", core.intent_from({"hook_event_name": "SessionStart"}) is None)
    check("B gemini's absolute_path is the target", core.extract_target({"absolute_path": "/x/y"}) == "/x/y")

    with tempfile.TemporaryDirectory() as tmp:
        core.ACTIONS_DIR = Path(tmp) / "actions"
        os.environ["HESTIA_STATE_DIR"] = str(Path(tmp) / "state")
        os.environ.pop("HESTIA_HOME", None)
        daemon = Daemon()
        os.environ["HESTIA_ENDPOINT"] = daemon.endpoint

        print("C. THE SEAM, per harness: the gate's action is the one the witness closes")
        for member, (pre, post) in P.items():
            daemon.calls.clear()
            core.configure(plugin_id=member)
            verdict = mech.query_society_safety(
                pre, plugin_id=member, host_agent=member, host_session_id=pre.get("session_id"),
                correlation_key=mech.correlation_key(pre))
            check(f"C {member}: the gate got a decided verdict with an action",
                  verdict.decided and bool(verdict.action_id), repr(verdict))
            gated = verdict.action_id
            daemon.calls.clear()
            core.run(post)
            recs = daemon.named("hestia_record_outcome")
            check(f"C {member}: the witness closed THE GATE'S action",
                  [r.get("action_id") for r in recs] == [gated], json.dumps(daemon.calls))
            check(f"C {member}: and began none of its own",
                  daemon.named("hestia_begin_action") == [], json.dumps(daemon.calls))
            check(f"C {member}: the correlation file is retired once the outcome is recorded",
                  not (core.ACTIONS_DIR / f"{core.correlation_key(post)}.json").exists())
            check(f"C {member}: the witness connects as {member}",
                  [c.get("plugin_id") for c in daemon.named("hestia_connect")] == [member],
                  json.dumps(daemon.named("hestia_connect")))

        print("D. control: without the key the gate caches nothing and the witness goes cold")
        pre, post = P["kimi-code"]
        daemon.calls.clear()
        mech.query_society_safety(pre, plugin_id="kimi-code", host_agent="kimi-code",
                                  host_session_id=pre.get("session_id"))
        daemon.calls.clear()
        core.run(post)
        begins = daemon.named("hestia_begin_action")
        check("D the witness began a cold action, typed as such",
              len(begins) == 1 and begins[0].get("intent") == core.COLD_NO_CACHE, json.dumps(begins))
        check("D a key that fails to compute is None, never a raise into the gate",
              mech.correlation_key(object()) in (None, "no-id"))
        daemon.server.shutdown()

    print("E. no forks")
    shims = {m: (REPO / "plugins" / d / "hooks" / "witness.py")
             for m, d in (("claude-code", "claude-code"), ("codex", "codex"),
                          ("kimi-code", "kimi"), ("gemini", "gemini"))}

    def normalized(p: Path) -> str:
        text = p.read_text()
        text = re.sub(r'^(DEFAULT_PLUGIN_ID|HOST_AGENT_VERSION) = ".*"$', r'\1 = "<id>"', text, flags=re.M)
        text = re.sub(r'^(""")?Hestia outcome witness — the .* shim\. Stdlib only\.$', r"\1<title>", text, flags=re.M)
        text = re.sub(r"^Registered on the harness's post-tool event\(s\): .*$", "<events>", text, flags=re.M)
        return text

    base = None
    for member, p in shims.items():
        check(f"E {member} ships the shim", p.is_file(), str(p))
        if not p.is_file():
            continue
        n = normalized(p)
        check(f"E {member}: the shim loads the shared core, and carries no witness logic of its own",
              '_load_shared_module("hestia_witness_core")' in n and "def witness_one" not in n)
        if base is None:
            base = (member, n)
        else:
            check(f"E {member}'s shim is byte-identical to {base[0]}'s but for identity",
                  n == base[1], f"{member} differs")
        m = re.search(r'^DEFAULT_PLUGIN_ID = "(.*)"$', p.read_text(), re.M)
        check(f"E {member}'s shim defaults to its own member id", bool(m) and m.group(1) == member,
              m.group(1) if m else "none")

    for d in ("claude-code", "codex", "kimi", "gemini"):
        spec = json.loads((REPO / "plugins" / d / "expects.json").read_text())
        files = (spec.get("install") or {}).get("files") or []
        check(f"E {d} installs hooks/witness.py", "hooks/witness.py" in files, json.dumps(files))
        check(f"E {d} declares witness.py as the file its observe role needs",
              "witness.py" in ((spec.get("targets") or {}).get("observe") or []),
              json.dumps(spec.get("targets")))

    for rel in ("claude-code/hooks/pre_tool_use.py", "codex/hooks/pre_tool_use.py",
                "kimi/hooks/pre_tool_use.py"):
        src = (REPO / "plugins" / rel).read_text()
        # A call site opens its argument list on the next line; a comment mentioning
        # `query_society_safety()` is not a call and must not be scored as one.
        calls = re.findall(r"query_society_safety\(\n(.*?)\)\n", src, flags=re.S)
        check(f"E {rel}: every daemon ask passes the correlation key",
              bool(calls) and all("correlation_key=" in c for c in calls), f"{len(calls)} call(s)")
    manifest = (HERE / "RUNTIME_MANIFEST.txt").read_text().split()
    check("E the core is in the installed engine set", "hestia_witness_core.py" in manifest)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
