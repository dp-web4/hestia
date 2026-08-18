#!/usr/bin/env python3
"""A read timeout is NOT "I never got there" — issue #523.

`hestia-mesh.py` bounded the whole exchange with `urlopen(timeout=5)` and routed the
resulting OSError into `Unreachable`, whose docstring declared it to mean "No answer at
all: connection refused, DNS, timeout. rc=1 — I never got there."

A timeout is not a member of that set. `urlopen`'s deadline covers READING THE RESPONSE,
so a POST the daemon received, processed and COMMITTED — but answered slowly — exited
rc=1. Measured 2026-08-18: a `send` binding a reply to notice 3049 exited rc=1 "timed
out", and 3049 was discharged from `unanswered` immediately after. The write had landed.

The cost is not the wrong word in a message. rc decides what the caller does next: rc=1
invites a retry, `send` has no idempotency key, and a retry after a committed write
duplicates the notice. So the CLI must distinguish "never left" (rc=1, safe to retry)
from "no answer, may have landed" (rc=4, NOT safe to retry blind).

BOTH ARMS IN ONE TEST, on purpose. An exit code that is always 4 and an exit code that
discriminates are indistinguishable from a single arm — and the pre-fix code passes any
one-armed "timeout gives rc=1" or "refused gives rc=1" assertion, because it gave rc=1
to both. The load-bearing assertion here is that the two arms DIFFER.

Drives the real CLI as a subprocess. No test seam: the code path exercised is the one
every member uses.
"""
import http.server, os, socket, subprocess, sys, threading, time, unittest

CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "hestia-mesh.py")


class _Slow(http.server.BaseHTTPRequestHandler):
    """Answers, but later than any deadline the test sets. The daemon is HEALTHY here —
    that is the point. Under one global lock its tail is long, not absent."""
    delay = 5.0

    def do_POST(self):
        time.sleep(self.delay)
        body = b'{"jsonrpc":"2.0","id":1,"result":{}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

    def handle_error(self, *a):
        # The client hangs up at its deadline while we are still sleeping; the
        # resulting BrokenPipe is the EXPECTED shape of this arm, not a failure.
        pass


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _run(endpoint, timeout_s):
    env = {**os.environ,
           "HESTIA_MESH_PLUGIN": "test-member",
           "HESTIA_ENDPOINT": endpoint,
           "HESTIA_MESH_TIMEOUT": str(timeout_s)}
    env.pop("HESTIA_ROLE", None)
    return subprocess.run([sys.executable, CLI, "peek"], env=env,
                          capture_output=True, text=True, timeout=60)


class TimeoutIsUndetermined(unittest.TestCase):
    def test_slow_answer_and_refused_connection_do_not_share_an_exit_code(self):
        # --- Arm A: the server is UP and answers after the deadline. May have landed.
        srv = http.server.HTTPServer(("127.0.0.1", 0), _Slow)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            slow = _run(f"http://127.0.0.1:{srv.server_port}/mcp", 0.75)
        finally:
            srv.shutdown()
            srv.server_close()

        # --- Arm B: nothing is listening. Genuinely never got there.
        refused = _run(f"http://127.0.0.1:{_free_port()}/mcp", 0.75)

        self.assertEqual(slow.returncode, 4,
                         f"a slow ANSWER must be UNDETERMINED (rc=4), got "
                         f"{slow.returncode}: {slow.stderr!r}")
        self.assertEqual(refused.returncode, 1,
                         f"connection refused must stay rc=1, got "
                         f"{refused.returncode}: {refused.stderr!r}")

        # The assertion the pre-fix code fails. Before #523 both arms were rc=1, so any
        # single-arm check passed while the distinction the caller needs did not exist.
        self.assertNotEqual(
            slow.returncode, refused.returncode,
            "a timeout and a refused connection must NOT share an exit code — that "
            "collapse is what let a committed send report 'I never got there'")

        # rc is what a script branches on; the text is what a human retries on. Both
        # must say the write may have landed, or the caller duplicates it.
        self.assertIn("UNDETERMINED", slow.stderr)
        self.assertIn("may have been COMMITTED", slow.stderr)
        self.assertNotIn("UNDETERMINED", refused.stderr)

    def test_the_deadline_is_configurable_and_the_default_clears_the_measured_tail(self):
        """The 5s that shipped sat INSIDE the daemon's latency tail — bare `initialize`
        was measured at 6.944s on a healthy daemon while the fleet was live. A ceiling
        below the tail turns routine contention into a false delivery failure."""
        with open(os.path.join(os.path.dirname(CLI), "hestia-mesh.py")) as fh:
            src = fh.read()
        # assertFalse on a bool, not assertNotIn on the file: a failing assertNotIn
        # prints the entire 300-line source as its message and buries the reason.
        self.assertFalse("timeout=5)" in src,
                         "the hard-coded 5s deadline is back; it is below the measured "
                         "6.944s tail of a healthy, contended daemon")
        self.assertIn("HESTIA_MESH_TIMEOUT", src)

        import re
        m = re.search(r'HESTIA_MESH_TIMEOUT",\s*"([0-9.]+)"', src)
        self.assertIsNotNone(m, "the default must be readable from the source")
        self.assertGreater(float(m.group(1)), 6.944,
                           "the default deadline must clear the measured tail")


if __name__ == "__main__":
    unittest.main()
