#!/usr/bin/env python3
"""#1097A: a CURRENT binary/manifest does not hide registration drift."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPT = HERE / "hestia-deploy.sh"
REGISTRAR = REPO / "deploy" / "register-members.py"
FAILS: list[str] = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def extract_function(text: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}\(\) *\{{\s*$", text, re.M)
    assert match, f"{name}() not found"
    depth = 0
    for index in range(match.start(), len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[match.start():index + 1]
    raise AssertionError(f"{name}() is not brace-balanced")


def run_drift(function: str, root: Path, home: Path, hestia_home: Path) -> tuple[int, str, str]:
    log = home / "deploy.log"
    program = (
        "set -euo pipefail\n"
        f"DEPLOY_ROOT={root}\nHOME={home}\nHESTIA_HOME={hestia_home}\nLOG={log}\n"
        f"{function}\n"
        "if registration_drift; then rc=0; else rc=$?; fi\n"
        "printf 'RC=%s\\nSTATUS=%s\\n' \"$rc\" \"$registration_drift_status\"\n"
    )
    result = subprocess.run(["bash", "-c", program], capture_output=True, text=True, timeout=30)
    check("drift probe shell succeeds", result.returncode, 0)
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return (int(fields.get("RC", "-1")), fields.get("STATUS", ""),
            log.read_text() if log.exists() else "")


def make_case(root: Path) -> tuple[Path, Path, Path, Path, str]:
    deploy_root = root / "deploy-root"
    member = deploy_root / "hestia" / "plugins" / "alpha"
    (member / "hooks").mkdir(parents=True)
    (deploy_root / "hestia" / "deploy").mkdir(parents=True)
    shutil.copyfile(REGISTRAR, deploy_root / "hestia" / "deploy" / "register-members.py")
    home = root / "home"
    hestia_home = home / ".hestia"
    installed = home / ".alpha" / "hooks" / "pre_tool_use.py"
    foreign = root / "foreign" / "pre_tool_use.py"
    spec = {"install": {
        "dest": str(installed.parent),
        "default_role": "role:test",
        "registration": {"path": [".alpha", "settings.json"], "reader": "json-hook-commands"},
    }}
    template = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{
        "type": "command",
        "command": "HESTIA_HOME=@HESTIA_HOME@ python3 @HESTIA_PLUGIN_ROOT@/alpha/hooks/pre_tool_use.py",
        "timeout": 10,
    }]}]}}
    (member / "expects.json").write_text(json.dumps(spec))
    (member / "hooks" / "hooks.json").write_text(json.dumps(template))
    config = home / ".alpha" / "settings.json"
    config.parent.mkdir(parents=True)
    installed.parent.mkdir(parents=True, exist_ok=True)
    installed.write_text("# test hook\n")
    foreign_command = f"python3 {foreign}"
    config.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": f"python3 {installed}", "timeout": 10},
        {"type": "command", "command": foreign_command, "timeout": 10},
    ]}]}}))
    return deploy_root, home, hestia_home, config, foreign_command


def main() -> int:
    text = SCRIPT.read_text()
    function = extract_function(text, "registration_drift")
    with tempfile.TemporaryDirectory(prefix="registration-drift-test-") as raw:
        root = Path(raw)
        deploy_root, home, hestia_home, config, foreign_command = make_case(root)
        before = config.read_bytes()
        rc, status, log = run_drift(function, deploy_root, home, hestia_home)
        check("stale owned registration is drift", (rc, status), (0, "drift"))
        check("dry-run drift check writes no registration", config.read_bytes(), before)
        check("drift output names the planned rewrite", "would rewrite" in log, True)

        env = dict(os.environ, HESTIA_HOME=str(hestia_home), DRY_RUN="0")
        repair = subprocess.run([
            "python3", str(deploy_root / "hestia" / "deploy" / "register-members.py"),
            "--home", str(home),
        ], capture_output=True, text=True, env=env, timeout=30)
        check("real registrar repair succeeds", repair.returncode, 0)
        rc, status, _ = run_drift(function, deploy_root, home, hestia_home)
        check("repaired registration is current", (rc, status), (1, "current"))
        check("foreign registration is untouched", foreign_command in config.read_text(), True)

        registrar = deploy_root / "hestia" / "deploy" / "register-members.py"
        registrar.write_text("#!/usr/bin/env python3\nprint('  NARROW alpha: measured gap')\nraise SystemExit(8)\n")
        rc, status, _ = run_drift(function, deploy_root, home, hestia_home)
        check("measured registration gap is drift", (rc, status), (0, "drift(rc=8)"))
        registrar.write_text("#!/usr/bin/env python3\nraise SystemExit(7)\n")
        rc, status, log = run_drift(function, deploy_root, home, hestia_home)
        check("registrar failure is unmeasured", (rc, status), (2, "unmeasured(rc=7)"))
        check("registrar failure is logged", "rc=7" in log, True)

    current = text.split('if same_build "$running" "$target" && same_build "$ondisk" "$target"; then', 1)[1]
    current = current.split('if [ "$MODE" = "--check" ]', 1)[0]
    check("CURRENT branch probes registration drift", "registration_drift" in current, True)
    check("drift triggers the members install",
          "registration drift" in current and "re-running the members' install" in current, True)
    install_hooks = extract_function(text, "install_hooks")
    check("install proves registrations after writing the manifest",
          "same_build \"$after\"" in install_hooks and
          install_hooks.index("registration_drift") > install_hooks.index('same_build "$after"'), True)

    if FAILS:
        print("FAIL\n  " + "\n  ".join(FAILS))
        return 1
    print("ok: CURRENT detects and repairs owned registration drift; foreign lines and dry-run bytes stay untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
