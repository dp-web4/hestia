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


WRITE_STATUS = extract_function(SCRIPT.read_text(), "write_update_status")
FINISH_STATUS = extract_function(SCRIPT.read_text(), "finish_update_status")
READ_REQUEST = extract_function(SCRIPT.read_text(), "read_update_request_id")
CLEANUP = extract_function(SCRIPT.read_text(), "cleanup_deploy")


def run_cleanup(
    request: str | None,
    claimed: str = "",
    followup: bool = False,
    completed: bool = True,
    exit_rc: int = 0,
    finish_rc: int = 0,
    missing_installer: bool = False,
) -> tuple[int, str, str, str | None, str | None]:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        home = root / "hh"
        home.mkdir()
        log = root / "followup.log"
        installer = root / "hestia-deploy"
        if not missing_installer:
            installer.write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$1\" > \"$FOLLOWUP_LOG\"\n")
            installer.chmod(0o755)
        request_path = home / "deploy-update.request"
        if request is not None:
            request_path.write_text(request + "\n")
        status_path = home / "deploy-status.tsv"
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
            f"DEPLOY_COMPLETED={1 if completed else 0}",
            f"LOCKD={shlex.quote(str(home / 'lock.d'))}",
            f"SELF_INSTALL={shlex.quote(str(installer))}",
            f"UPDATE_REQUEST={shlex.quote(str(request_path))}",
            f"UPDATE_STATUS={shlex.quote(str(status_path))}",
            f"UPDATE_REQUEST_ID={shlex.quote(claimed)}",
            "UPDATE_TARGET=''",
            "log() { :; }",
            "write_check_result() { :; }",
            WRITE_STATUS,
            FINISH_STATUS,
        ]
        if finish_rc:
            lines.append(f"write_update_status() {{ return {finish_rc}; }}")
        lines.extend([READ_REQUEST, CLEANUP])
        if exit_rc:
            lines.append(f"(exit {exit_rc}) || cleanup_deploy")
        else:
            lines.append("cleanup_deploy")
        lines.append("printf 'NO_FOLLOWUP\\n'")
        result = subprocess.run(["bash", "-c", "\n".join(lines)], env=env,
                                capture_output=True, text=True, timeout=20)
        observed = log.read_text() if log.exists() else result.stdout
        request_state = request_path.read_text() if request_path.exists() else None
        status_state = status_path.read_text() if status_path.exists() else None
        return result.returncode, observed, result.stderr, request_state, status_state


def test_new_request_gets_one_immediate_followup():
    rc, out, err, _, _ = run_cleanup("request-new")
    assert rc == 0, err
    assert out == "full\n", out


def test_request_from_prior_claim_gets_followup_too():
    rc, out, err, _, _ = run_cleanup("request-new", claimed="request-old")
    assert rc == 0, err
    assert out == "full\n", out


def test_followup_guard_prevents_an_immediate_loop():
    rc, out, err, request, status = run_cleanup(
        "request-new", claimed="request-old", followup=True)
    assert rc == 0, err
    assert out == "NO_FOLLOWUP\n", out
    assert request == "request-new\n", request
    assert status.startswith("succeeded\trequest-old\t"), status


def test_no_new_or_malformed_request_does_not_rerun():
    for request in (None, "bad id!"):
        rc, out, err, _, _ = run_cleanup(request)
        assert rc == 0, (request, err)
        assert out == "NO_FOLLOWUP\n", (request, out)


def test_failed_parent_run_does_not_follow_up():
    rc, out, err, request, status = run_cleanup(
        "request-new", claimed="request-old", completed=False, exit_rc=1)
    assert rc == 0, err
    assert out == "NO_FOLLOWUP\n", out
    assert request == "request-new\n", request
    assert status.startswith("failed\trequest-old\t"), status


def test_failed_status_finalization_does_not_follow_up():
    rc, out, err, request, status = run_cleanup(
        "request-new", claimed="request-old", finish_rc=1)
    assert rc == 0, err
    assert out == "NO_FOLLOWUP\n", out
    assert request == "request-new\n", request
    assert status is None, status


def test_operator_stop_does_not_follow_up():
    rc, out, err, request, status = run_cleanup("request-new", completed=False)
    assert rc == 0, err
    assert out == "NO_FOLLOWUP\n", out
    assert request == "request-new\n", request
    assert status is None, status


def test_exec_failure_leaves_request_for_timer_recovery():
    rc, _, _, request, status = run_cleanup(
        "request-new", claimed="request-old", missing_installer=True)
    assert rc != 0, rc
    assert request == "request-new\n", request
    assert status.startswith("succeeded\trequest-old\t"), status


def test_completion_latch_is_wired_on_real_success_exits():
    text = SCRIPT.read_text()
    assert "DEPLOY_COMPLETED=0" in text
    assert text.count("DEPLOY_COMPLETED=1") == 3
    assert "ok) DEPLOY_COMPLETED=1; exit 0 ;;" in text
    assert "ok|skipped) DEPLOY_COMPLETED=1; exit 0 ;;" in text
    assert 'log "CURRENT $target' in text
    assert "DEPLOY_COMPLETED=1\n  exit 0" in text


def main() -> None:
    test_new_request_gets_one_immediate_followup()
    test_request_from_prior_claim_gets_followup_too()
    test_followup_guard_prevents_an_immediate_loop()
    test_no_new_or_malformed_request_does_not_rerun()
    test_failed_parent_run_does_not_follow_up()
    test_failed_status_finalization_does_not_follow_up()
    test_operator_stop_does_not_follow_up()
    test_exec_failure_leaves_request_for_timer_recovery()
    test_completion_latch_is_wired_on_real_success_exits()
    print("ok: 9 update-followup checks")


if __name__ == "__main__":
    main()
