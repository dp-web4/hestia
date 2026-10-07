#!/usr/bin/env python3
"""Run supplied bar tests and registered-location probes on a disposable daemon.

Usage: python3 this.py PATH_TO_DAEMON_BUILT_FROM_REVIEWED_HEAD
Relocates the existing seat fixtures into this worktree's writable scratch dir.
Classified commands are never executed. No live daemon is contacted.
"""
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import types

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "plugins/_shared"))
seat_path = ROOT / "plugins/_shared/seat_gate_boundary_test.py"
seat_source = seat_path.read_text().replace(
    'os.path.expanduser("~/.cache/hestia-seat-boundary-tests")',
    repr(str(ROOT / ".review-fixtures")))
sb = types.ModuleType("seat_gate_boundary_test")
sb.__file__ = str(seat_path)
sys.modules[sb.__name__] = sb
exec(compile(seat_source, str(seat_path), "exec"), sb.__dict__)


def main():
    binary = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="codex-18786-daemon-") as temp:
        env = dict(os.environ, HESTIA_HOME=temp, HESTIA_PASSPHRASE="disposable-review-fixture")
        log = open(Path(temp) / "daemon.log", "w+")
        subprocess.run([str(binary), "--home", temp, "init", "--ai"], env=env,
                       stdout=log, stderr=log, check=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        assert port != 7711
        endpoint = f"http://127.0.0.1:{port}/mcp"
        proc = subprocess.Popen([str(binary), "--home", temp, "serve", "--bind",
                                 f"127.0.0.1:{port}"], env=env, stdout=log, stderr=log)
        try:
            os.environ["HESTIA_ESCALATION_BAR_ENDPOINT"] = endpoint
            path = ROOT / "tools/escalation_bar_real_daemon_test.py"
            spec = importlib.util.spec_from_file_location("bar_test", path)
            suite = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(suite)
            for attempt in range(60):
                try:
                    suite._post(endpoint, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                   "clientInfo": {"name": "review-fixture", "version": "0"}}})
                    break
                except Exception:
                    if proc.poll() is not None:
                        raise RuntimeError("isolated daemon exited")
                    time.sleep(0.5)
            else:
                raise RuntimeError("isolated daemon did not become ready")
            for test in suite.ALL:
                before = len(suite.FAILS)
                test()
                print(("PASS " if len(suite.FAILS) == before else "FAIL ") + test.__name__, flush=True)
            failed = len(suite.FAILS)
            print(f"Supplied suite failures: {failed}", flush=True)
            fx = sb.Fixture()
            try:
                home = fx.home("gemini", endpoint)
                legacy, entry, _ = sb._legacy_install("gemini", home)
                cases = [
                    ("registered-literal", entry, "sovereign_plus_peer"),
                    ("registered-glob", os.path.join(legacy, "before_*"), "sovereign_plus_peer"),
                    ("registered-glob-negative-control", os.path.join(legacy, "after_*"), "single_approver"),
                    ("unknown-target", os.path.join(legacy, "$TARGET"), "sovereign_plus_peer"),
                ]
                for n, (label, target, expected) in enumerate(cases, 110):
                    rec = suite.open_and_read("gemini", home,
                        sb.native("gemini", "Bash", {"command": "touch " + target}, n=n),
                        label, shim_path=entry)
                    ok = rec.get("bar") == expected
                    failed += not ok
                    print(f"{'PASS' if ok else 'FAIL'} {label}: recorded={rec.get('bar')} expected={expected}", flush=True)
            finally:
                fx.close()
            return bool(failed or suite.FAILS)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            log.close()


if __name__ == "__main__":
    sys.exit(main())
