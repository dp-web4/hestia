#!/usr/bin/env python3
"""#581: the daemon reads the passphrase in-process; the launchers switch in a follow-up."""
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

    # The launchers keep main's shell wrapper until a published release contains the reader
    # (the installers run the newest PUBLISHED binary). Pin that here, so the switch to direct
    # exec is a deliberate change made with its own checks, not a drive-by.
    unit = (ROOT / "deploy/templates/hestia.service").read_text()
    install = (ROOT / "deploy/fleet/install.sh").read_text()
    check("the launchers still use the wrapper an older published binary needs",
          "HESTIA_PASSPHRASE=" in unit and "HESTIA_PASSPHRASE=" in install)

    assurance = (ROOT / "docs/PRD_ASSURANCE.md").read_text()
    check("A1 same-UID file access is disclosed, not overclaimed",
          "any process at that UID can read it" in assurance
          and "/proc/<pid>/environ" in assurance
          and "have not switched yet" in assurance)

    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {FAILS}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
