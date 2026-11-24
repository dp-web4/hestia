#!/usr/bin/env python3
"""#757: only a completed member wake records exact invitation observation."""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = pathlib.Path(__file__).resolve().parent
CLI = os.environ.get("HESTIA_MESH_CLI") or str(HERE.parent / "hestia-mesh.py")
CALLS = []
FAIL_ON = set()
NOT_INVITED_ON = set()
SETTLED_ON = set()


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or "{}")
        method = body.get("method")
        if method == "initialize":
            return self._json({"jsonrpc": "2.0", "id": body["id"],
                               "result": {"protocolVersion": "2024-11-05"}}, sid="stub-session")
        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        name = body.get("params", {}).get("name")
        if name == "hestia_connect":
            return self._sse(body["id"], {"sessionId": "s-1"})
        if name == "hestia_gate_escalation_presented":
            args = body["params"]["arguments"]
            CALLS.append(args)
            if args["escalation_id"] in NOT_INVITED_ON:
                return self._sse(body["id"], {"_hestia_error": {
                    "code": "hestia.test.not_invited",
                    "message": f"{args['escalation_id']} was not invited to escalation; refusing an unbound observation"}})
            if args["escalation_id"] in SETTLED_ON:
                return self._sse(body["id"], {"_hestia_error": {
                    "code": "hestia.test.settled", "message": "escalation is Approved, not pending"}})
            if args["escalation_id"] in FAIL_ON:
                return self._sse(body["id"], {"_hestia_error": {
                    "code": "hestia.test.transport", "message": "transport failed"}})
            return self._sse(body["id"], {
                "escalation_id": args["escalation_id"], "recorded": True,
                "observed": True, "witnessEntryHash": "witness"})
        raise AssertionError(f"unexpected tool: {name}")

    def _json(self, payload, sid=None):
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        if sid:
            self.send_header("mcp-session-id", sid)
        self.end_headers()
        self.wfile.write(raw)

    def _sse(self, rid, obj):
        envelope = {"jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "text", "text": json.dumps(obj)}]}}
        raw = f"event: message\ndata: {json.dumps(envelope)}\n\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class PresentedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Stub)
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}/mcp"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def setUp(self):
        CALLS.clear()
        FAIL_ON.clear()
        NOT_INVITED_ON.clear()
        SETTLED_ON.clear()

    def run_cli(self, text):
        env = dict(os.environ, HESTIA_ENDPOINT=self.endpoint,
                   HESTIA_MESH_PLUGIN="test-member", PYTHONDONTWRITEBYTECODE="1")
        env.pop("HESTIA_ROLE", None)
        result = subprocess.run([sys.executable, CLI, "presented"], input=text,
                                capture_output=True, text=True, env=env, timeout=20, check=False)
        return result.returncode, result.stdout, result.stderr

    def test_exact_ids_are_deduplicated_and_attributed(self):
        a = "0123456789abcdef"
        b = "fedcba9876543210"
        digest = (
            f"- id=1 kind=review_request pointer=hestia://escalation/{a}#review\n"
            f"- id=2 kind=review_request pointer=hestia://escalation/{a}#duplicate\n"
            f"- id=3 kind=review_request pointer=hestia://escalation/{b}#review\n"
            "- id=4 kind=reply pointer=hestia://scope/deadbeefdeadbeef#not-an-escalation\n"
            "- id=5 kind=reply pointer=hestia://escalation/not-hex#not-an-id\n"
        )
        rc, out, err = self.run_cli(digest)
        self.assertEqual(rc, 0, err)
        self.assertEqual([call["escalation_id"] for call in CALLS], [a, b])
        self.assertEqual([call["notice_id"] for call in CALLS], [1, 3])
        self.assertTrue(all(call["session_id"] == "s-1" for call in CALLS))
        payload = json.loads(out)
        self.assertEqual(payload["member"], "test-member")
        self.assertEqual(len(payload["observations"]), 2)
        self.assertIn("presented 2 invitation(s) as test-member", err)

    def test_no_rendered_invitation_means_no_session_and_no_observation(self):
        rc, out, err = self.run_cli("ordinary activity with no invitation pointer\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["observations"], [])
        self.assertEqual(CALLS, [])

    def test_refusal_preserves_prior_results_and_exits_nonzero(self):
        a = "0123456789abcdef"
        b = "fedcba9876543210"
        FAIL_ON.add(b)
        c = "1111111111111111"
        rc, out, err = self.run_cli(
            f"id=1 hestia://escalation/{a}\nid=2 hestia://escalation/{b}\nid=3 hestia://escalation/{c}")
        self.assertEqual(rc, 3, err)
        payload = json.loads(out)
        self.assertEqual(len(payload["observations"]), 2)
        self.assertEqual(payload["observations"][0]["escalation_id"], a)
        self.assertEqual(payload["observations"][1]["escalation_id"], c)
        self.assertIn("_hestia_error", payload)
        self.assertEqual(len(CALLS), 3)

    def test_not_invited_disposition_does_not_drop_later_invitations(self):
        own = "aaaaaaaaaaaaaaaa"
        invited = "bbbbbbbbbbbbbbbb"
        NOT_INVITED_ON.add(own)
        rc, out, err = self.run_cli(
            f"id=10 hestia://escalation/{own}#decided\nid=11 hestia://escalation/{invited}#review")
        self.assertEqual(rc, 0, err)
        self.assertEqual([call["escalation_id"] for call in CALLS], [own, invited])
        payload = json.loads(out)
        self.assertEqual([row["escalation_id"] for row in payload["observations"]], [invited])

    def test_settled_disposition_does_not_drop_later_invitations(self):
        own = "aaaaaaaaaaaaaaaa"
        invited = "bbbbbbbbbbbbbbbb"
        SETTLED_ON.add(own)
        rc, out, err = self.run_cli(
            f"id=10 hestia://escalation/{own}#decided\nid=11 hestia://escalation/{invited}#review")
        self.assertEqual(rc, 0, err)
        self.assertEqual([call["escalation_id"] for call in CALLS], [own, invited])
        self.assertEqual([call["notice_id"] for call in CALLS], [10, 11])
        payload = json.loads(out)
        self.assertEqual([row["escalation_id"] for row in payload["observations"]], [invited])

    def run_fire(self, script, executable, sender, member, member_rc):
        escalation_id = "0123456789abcdef"
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bindir = root / "bin"
            bindir.mkdir()
            (bindir / executable).write_text(f"#!/usr/bin/env bash\nexit {member_rc}\n")
            (bindir / executable).chmod(0o755)
            primer = root / "notice.json"
            primer.write_text(json.dumps({
                "notices": [{
                    "id": 1, "kind": "review_request", "from_plugin": sender,
                    "to_plugin": member,
                    "pointer_uri": f"hestia://escalation/{escalation_id}#review",
                    "queued_at": "2026-11-21T00:00:00Z",
                }],
                "unanswered": {},
            }))
            env = dict(
                os.environ,
                HOME=tmp,
                PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}",
                HESTIA_ENDPOINT=self.endpoint,
                HESTIA_MESH_LOCK_DIR=str(root / "locks"),
                HESTIA_MESH_STATE=str(root / "state"),
                HESTIA_FIRE_LOCK_WAIT="2",
                HESTIA_WORKSPACE=tmp,
                PYTHONDONTWRITEBYTECODE="1",
            )
            env.pop("HESTIA_ROLE", None)
            result = subprocess.run([str(HERE.parent / script), str(primer)],
                                    capture_output=True, text=True, env=env, timeout=45,
                                    check=False)
            return result.returncode, result.stdout + result.stderr, list(CALLS)

    def test_real_fire_success_records_and_failed_member_does_not(self):
        cases = (
            ("fire-claude.sh", "claude", "kimi-code", "claude-code"),
            ("fire-codex.sh", "codex", "kimi-code", "codex"),
            ("fire-kimi.sh", "kimi", "claude-code", "kimi-code"),
        )
        for script, executable, sender, member in cases:
            with self.subTest(script=script, outcome="success"):
                rc, output, calls = self.run_fire(script, executable, sender, member, 0)
                self.assertEqual(rc, 0, output)
                self.assertEqual([call["escalation_id"] for call in calls],
                                 ["0123456789abcdef"], output)
                self.assertTrue(all(call["session_id"] == "s-1" for call in calls), output)
                self.assertTrue(all(call["notice_id"] == 1 for call in calls), output)
            CALLS.clear()
            with self.subTest(script=script, outcome="member failed"):
                rc, output, calls = self.run_fire(script, executable, sender, member, 3)
                self.assertEqual(rc, 3, output)
                self.assertEqual(calls, [], output)
            CALLS.clear()

    def test_every_fire_template_gates_observation_on_member_success(self):
        for name in ("fire-kimi.sh", "fire-claude.sh", "fire-codex.sh"):
            text = (HERE.parent / name).read_text(encoding="utf-8")
            guard = 'if [ "$RC" -eq 0 ]; then'
            self.assertIn(guard, text, name)
            launch = text.rindex("RC=$?")
            observation = text.index(guard, launch)
            command = text.index("presented >>", observation)
            done = text.index("done rc=$RC", command)
            self.assertLess(launch, observation, name)
            self.assertLess(observation, command, name)
            self.assertLess(command, done, name)
            self.assertIn('HESTIA_MESH_PLUGIN="$MEMBER"', text[observation:done], name)
            self.assertIn("remains unanswered, not observed", text[observation:done], name)


if __name__ == "__main__":
    unittest.main()
