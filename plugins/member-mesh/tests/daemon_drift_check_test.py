#!/usr/bin/env python3
"""The daemon must report its own drift the way the watcher reports its own.

WHY THIS TEST EXISTS (mesh-vocabulary thread, 2026-08-03). The watcher already
refuses to run stale bytes of itself (watch_artifact_identity_test.py), but the
daemon had no equivalent: it knew its own build string and never compared it to
anything. So a scope door committed in 7c6ab83 sat absent from the running
daemon's 29-tool surface, and F1 (PR #165) sat merge-green while the daemon
answering every `unanswered` query predated the defect being named. "Merged" and
"running" were indistinguishable in every report the mesh produced.

The repair has two halves, and this test pins both against a stub MCP daemon:

  1. The daemon exposes its build provenance on the initialize handshake
     (serverInfo.version carries the same string `--version` prints). The stub
     speaks exactly that contract; a daemon that does not is precisely the
     drift case (a binary too old to report its build predates the exposure).
  2. The watcher compares that string to `git describe` of the checkout it runs
     from, equality not ancestry, and alarms on the EDGE while a periodic
     DAEMON line keeps the LEVEL visible — the same discipline as
     check_artifact_drift, because an alarm that fires once and goes quiet
     reads as resolved.

Properties asserted:

  A. MATCH: a daemon built from the checkout's own describe string reads
     state=ok reason=matches-source, with both raw strings on the line.
  B. DRIFT: a different build string produces an explicit
     "DAEMON DRIFT — rebuild+restart required" edge naming running AND source,
     and the periodic gauge keeps reporting state=drift after the edge.
  C. RECOVERY CLEARS THE EDGE: flipping the stub back to the matching build
     returns the gauge to state=ok (and re-drifting alarms again — the edge
     memory is not a one-shot latch).
  D. NO PROVENANCE IS DRIFT, NOT "UNVERIFIABLE": a pre-exposure daemon (a bare
     semver with no parenthesized build string) is the exact condition this
     check exists to catch; reporting it as "unverifiable" would let the one
     daemon that needs rebuilding pass silently.
  E/F. THE REMEDY NAMES THE STALE SIDE. Equality is the verdict but it is not
     the repair: a daemon behind its checkout needs rebuild+restart, a checkout
     behind its daemon needs a pull, and the first instruction given in the
     second situation walks the daemon backwards. E pins the ancestor case, F
     the descendant case, and B pins the honest third answer — a build string
     naming a commit this checkout does not have leaves the direction
     unresolved, and the alarm says so instead of guessing.

Hermetic: the stub is a local HTTP server on an ephemeral port; the source
side of the comparison is the real checkout this test runs in (CI checkouts
have no tags and depth-1 history, so the test derives its expectation from
`git describe` itself rather than hardcoding a shape).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HERE = Path(__file__).resolve().parent
WATCHER = HERE.parent / "hestia-watch-member.sh"
TIMEOUT = 15.0


class StubDaemon:
    """Just enough MCP to carry serverInfo.version on initialize."""

    def __init__(self, version: str) -> None:
        self.version = version
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # silence
                pass

            def _sse(self, payload: dict) -> None:
                body = f"data: {json.dumps(payload)}\n\n".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    req = json.loads(self.rfile.read(length) or b"{}")
                except Exception:
                    req = {}
                method = req.get("method")
                if method == "initialize":
                    self._sse({
                        "jsonrpc": "2.0",
                        "id": req.get("id"),
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "serverInfo": {"name": "hestia", "version": outer.version},
                        },
                    })
                elif method == "tools/call":
                    # The watcher's drain lands here; a refusal-shaped result
                    # keeps the loop on its empty-inbox path.
                    self._sse({
                        "jsonrpc": "2.0",
                        "id": req.get("id"),
                        "result": {"content": [{"type": "text",
                                                "text": '{"_hestia_error":"stub"}'}]},
                    })
                else:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/mcp"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def synthetic_checkout(root: Path) -> tuple[str, str]:
    """A two-commit checkout carrying its own copy of the watcher.

    The direction cases cannot use the real checkout: a DESCENDANT of HEAD does
    not exist in it, and CI's depth-1 clone has no HEAD~1 either, so neither
    direction is constructible there. Only the git plumbing has to be real for
    ancestry to mean anything, and here it is. Returns (older, newer) describes.
    """
    wm = root / "plugins" / "member-mesh"
    wm.mkdir(parents=True)
    (wm / WATCHER.name).write_bytes(WATCHER.read_bytes())
    (wm / WATCHER.name).chmod(0o755)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git(root, "config", "user.email", "drift-test@example.invalid")
    git(root, "config", "user.name", "drift test")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "watcher")
    older = git(root, "describe", "--tags", "--always", "--dirty")
    (root / "marker").write_text("second\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "second")
    newer = git(root, "describe", "--tags", "--always", "--dirty")
    assert older != newer, (older, newer)
    return older, newer


def divergent_checkout(root: Path) -> str:
    """Leave HEAD on `main` and return the describe of a sibling branch.

    Both commits exist here and neither is an ancestor of the other — the only
    pair that makes BOTH `merge-base --is-ancestor` calls run and answer no.
    B's unresolvable pair short-circuits earlier, on a commit the checkout does
    not have, so without this case that branch is never executed by any test.
    """
    synthetic_checkout(root)
    base = git(root, "rev-parse", "HEAD~1")
    git(root, "checkout", "-q", "-b", "side", base)
    (root / "side-marker").write_text("side\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "side")
    side = git(root, "describe", "--tags", "--always", "--dirty")
    git(root, "checkout", "-q", "main")
    for a, b in (("side", "main"), ("main", "side")):
        rc = subprocess.run(["git", "-C", str(root), "merge-base",
                             "--is-ancestor", a, b]).returncode
        assert rc != 0, f"{a} is an ancestor of {b} — not a divergent pair"
    return side


def source_describe() -> str:
    out = subprocess.run(
        ["git", "-C", str(HERE.parent.parent.parent),
         "describe", "--tags", "--always", "--dirty"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out, "git describe produced nothing — the watcher will read the same"
    return out


def read_until(proc: subprocess.Popen[str], needle: str, accept=None) -> str:
    lines: list[str] = []
    deadline = time.monotonic() + TIMEOUT
    assert proc.stdout is not None
    while time.monotonic() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], 0.25)
        if not ready:
            if proc.poll() is not None:
                break
            continue
        line = proc.stdout.readline()
        if not line:
            break
        lines.append(line)
        if needle in line and (accept is None or accept(line)):
            return "".join(lines)
    raise AssertionError(
        f"did not observe {needle!r}; rc={proc.poll()} output={''.join(lines)!r}"
    )


def stop(proc: subprocess.Popen[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


def start(home: Path, endpoint: str, watcher: Path = WATCHER) -> subprocess.Popen[str]:
    env = dict(
        os.environ,
        HOME=str(home),
        HESTIA_MESH_STATE=str(home / "state"),
        HESTIA_ENDPOINT=endpoint,
        WATCH_INTERVAL="0.1",
        UNANSWERED_EVERY="1",  # gauge every second: the level, not just the edge
    )
    return subprocess.Popen(
        [str(watcher), "daemon-drift-test", "test-host"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )


def main() -> None:
    describe = source_describe()
    matching = describe.removesuffix("-dirty")
    drifted = "v9.9.9-1-gdeadbeef"
    assert drifted != matching

    stub = StubDaemon(version=f"0.0.3 ({matching})")
    try:
        with tempfile.TemporaryDirectory() as td:
            proc = start(Path(td) / "home", stub.endpoint)
            try:
                # A. match reads ok at startup, with both raw strings visible.
                startup = read_until(proc, "DAEMON state=")
                assert "state=ok" in startup, startup
                assert "reason=matches-source" in startup, startup
                assert f"running={matching}" in startup, startup

                # B. a divergent build alarms on the edge, naming both sides…
                # `deadbeef` is not a commit this checkout has, so the direction
                # is genuinely unresolvable and the alarm must NOT pick one:
                # "rebuild+restart" here would be a guess, and E/F below show the
                # guess is wrong half the time.
                stub.version = f"0.0.3 ({drifted})"
                drift = read_until(proc, "DAEMON DRIFT")
                assert "direction unresolved" in drift, drift
                assert "rebuild+restart" not in drift, drift
                assert f"running={drifted}" in drift, drift
                assert f"source={describe}" in drift or f"source={matching}" in drift, drift

                # …and the periodic gauge HOLDS the drift after the edge — an
                # alarm that goes quiet must not read as resolved.
                gauge = read_until(proc, "DAEMON state=drift")
                assert "reason=differs-from-source" in gauge, gauge

                # C. recovery returns the gauge to ok…
                stub.version = f"0.0.3 ({matching})"
                recovered = read_until(
                    proc, "DAEMON state=ok",
                )
                assert "reason=matches-source" in recovered, recovered

                # …and a second drift alarms again — the edge is not latched.
                stub.version = "0.0.3"  # pre-provenance daemon: bare semver
                redrift = read_until(proc, "DAEMON DRIFT")
                # D. no parenthesized provenance IS drift, not "unverifiable".
                assert "reason=no-build-provenance" in redrift, redrift
                assert "DAEMON UNVERIFIABLE" not in redrift, redrift
            finally:
                stop(proc)
    finally:
        stub.stop()

    check_direction_cases()

    print("ok: daemon build drift is reported on the edge, held on the level, "
          "and names which side is stale")


def check_direction_cases(only: str | None = None) -> None:
    # E/F. THE REMEDY IS DIRECTIONAL AND EQUALITY CANNOT SUPPLY IT.
    # Observed on CBP 2026-08-03, the hour this check merged: the daemon was
    # deployed at f863088 from a clean worktree while the shared checkout every
    # watcher runs from sat 12 commits behind, so the alarm read "rebuild+restart
    # required" for a daemon that was AHEAD — an instruction that, followed, would
    # have installed a binary older than the one it replaced. Mismatch is one
    # verdict with two opposite repairs; the alarm has to say which.
    for label, head_at, running_is, want_reason, want_fix in (
        ("E daemon-behind-source", "newer", "older", "daemon-behind-source",
         "rebuild+restart required"),
        ("F source-behind-daemon", "older", "newer", "source-behind-daemon",
         "pull the checkout"),
    ):
        # `only` exists so each case can be run alone against an unpatched
        # watcher: a case that never executes because an earlier one aborted has
        # not been shown to be red, and a guard never seen red is a claim.
        if only and not label.startswith(only):
            continue
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "checkout"
            older, newer = synthetic_checkout(root)
            if head_at == "older":
                git(root, "reset", "--hard", "-q", "HEAD~1")
            running = older if running_is == "older" else newer
            stub = StubDaemon(version=f"0.0.3 ({running})")
            try:
                proc = start(Path(td) / "home", stub.endpoint,
                             watcher=root / "plugins" / "member-mesh" / WATCHER.name)
                try:
                    line = read_until(proc, "DAEMON DRIFT")
                    assert f"reason={want_reason}" in line, (label, line)
                    assert want_fix in line, (label, line)
                    if want_reason == "source-behind-daemon":
                        # The wrong instruction must be absent, not merely
                        # outranked: a line carrying both reads as either.
                        assert "rebuild+restart" not in line, (label, line)
                finally:
                    stop(proc)
            finally:
                stub.stop()

    if only and not "G".startswith(only):
        return
    # G. DIVERGENT IS UNRESOLVABLE FOR A SECOND REASON. B's pair is unorderable
    # because a commit is MISSING; here both are present and the history simply
    # forks — a daemon built on a branch while the checkout sits on main. Same
    # neutral wording, different cause, and only this one exercises the path
    # where both `merge-base` calls actually run and both say no.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "checkout"
        side = divergent_checkout(root)
        stub = StubDaemon(version=f"0.0.3 ({side})")
        try:
            proc = start(Path(td) / "home", stub.endpoint,
                         watcher=root / "plugins" / "member-mesh" / WATCHER.name)
            try:
                line = read_until(proc, "DAEMON DRIFT")
                assert "reason=differs-from-source" in line, line
                assert "direction unresolved" in line, line
                # The level survives the pair the resolver cannot order: a
                # verdict it declines to refine is still a verdict it must keep
                # reporting.
                read_until(proc, "DAEMON state=drift")
                assert proc.poll() is None, "watcher stopped on a divergent pair"
            finally:
                stop(proc)
        finally:
            stub.stop()


if __name__ == "__main__":
    main()
