#!/usr/bin/env python3
"""#581: the daemon and shipped launchers read the passphrase in-process."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
FAILS = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILS.append(name)


def main():
    cli = (ROOT / "core/src/cli.rs").read_text()
    check("the CLI has an in-process file reader", "fn read_passphrase_file" in cli)
    check("the file is read after env automation and before TTY",
          "if let Some(pp) = read_passphrase_file(home)?" in cli
          and "rpassword::prompt_password(prompt)" in cli)

    unit = (ROOT / "deploy/templates/hestia.service").read_text()
    check("systemd starts the daemon directly",
          "ExecStart=%h/.local/bin/hestia serve --bind 127.0.0.1:7711" in unit)
    check("systemd does not export the passphrase",
          "HESTIA_PASSPHRASE=" not in unit)

    install = (ROOT / "deploy/fleet/install.sh").read_text()
    check("the installer starts systemd directly",
          "ExecStart=%h/.local/bin/hestia serve --bind ${HESTIA_BIND}" in install)
    check("launchd arguments are a direct array",
          "<string>\\$HOME/.local/bin/hestia</string>" in install
          and "<string>/bin/sh</string>" not in install)

    canon = (ROOT / "deploy/fleet/canonicalize-macos-seat.sh").read_text()
    check("canonicalization compares the full argv array",
          "plutil -extract ProgramArguments json -o -" in canon)
    check("canonicalization writes direct argv, not a shell wrapper",
          "plutil -replace ProgramArguments -json \"$want_args\"" in canon
          and "line = f'HESTIA_PASSPHRASE" not in canon)

    assurance = (ROOT / "docs/PRD_ASSURANCE.md").read_text()
    check("A1 same-UID file access is disclosed, not overclaimed",
          "any process at that UID can read it" in assurance
          and "/proc/<pid>/environ" in assurance)

    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {FAILS}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
