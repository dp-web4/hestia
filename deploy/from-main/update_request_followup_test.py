#!/usr/bin/env python3
"""#1553: a dashboard request arriving during a run gets one bounded follow-up."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "hestia-deploy.sh"


def extract_function(text: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}\(\) *\{{\s*$", text, re.M)
    assert match, f"{name} not found"
    depth = 0
    for index in range(match.start(), len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[match.start():index + 1]
    raise AssertionError(f"{name} is not brace-balanced")


READ_REQUEST = extract_function(SCRIPT.read_text(), "read_update_request_id")
CLEANUP = extract_function(SCRIPT.read_text(), "cleanup_deploy")


def run_cleanup(request: str | None, claimed: str = "", followup: bool = False) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        home = root / "hh"
        home.mkdir()
        log = root / "followup.log"
        installer = root / "hestia-deploy"
        installer.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$1\" > \"$FOLLOWUP_LOG\"\n")
        installer.chmod(0o755)
        request_path = home / "deploy-update.request"
        if request is not None:
            request_path.write_text(request + "\n")
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(root),
            "HESTIA_HOME": str(home),
            "FOLLOWUP_LOG": str(log),
        }
        if followup:
            env["HESTIA_DEPLOY_FOLLOWUP"] = "1"
        lines = [
            "set -euo pipefail",
            "MODE=full",
            "CHECK_WRITTEN=0",
            "LOCKD_OWNED=0",
            f"LOCKD={shlex.quote(str(home / 'lock.d'))}",
            f"SELF_INSTALL={shlex.quote(str(installer))}",
            f"UPDATE_REQUEST={shlex.quote(str(request_path))}",
            f"UPDATE_STATUS={shlex.quote(str(home / 'deploy-status.tsv'))}",
            f"UPDATE_REQUEST_ID={shlex.quote(claimed)}",
            "UPDATE_TARGET=''",
            "write_check_result() { :; }",
            "finish_update_status() { :; }",
            READ_REQUEST,
            CLEANUP,
            "cleanup_deploy",
            "printf 'NO_FOLLOWUP\\n'",
        ]
        result = subprocess.run(["bash", "-c", "\n".join(lines)], env=env,
                                capture_output=True, text=True, timeout=20)
        observed = log.read_text() if log.exists() else result.stdout
        return result.returncode, observed, result.stderr


def test_new_request_gets_one_immediate_followup():
    rc, out, err = run_cleanup("request-new")
    assert rc == 0, err
    assert out == "full\n", out


def test_request_from_prior_claim_gets_followup_too():
    rc, out, err = run_cleanup("request-new", claimed="request-old")
    assert rc == 0, err
    assert out == "full\n", out


def test_followup_guard_prevents_an_immediate_loop():
    rc, out, err = run_cleanup("request-new", followup=True)
    assert rc == 0, err
    assert out == "NO_FOLLOWUP\n", out


def test_no_new_or_malformed_request_does_not_rerun():
    for request in (None, "bad id!"):
        rc, out, err = run_cleanup(request)
        assert rc == 0, (request, err)
        assert out == "NO_FOLLOWUP\n", (request, out)


def main() -> None:
    test_new_request_gets_one_immediate_followup()
    test_request_from_prior_claim_gets_followup_too()
    test_followup_guard_prevents_an_immediate_loop()
    test_no_new_or_malformed_request_does_not_rerun()
    print("ok: 4 update-followup checks")


if __name__ == "__main__":
    main()
