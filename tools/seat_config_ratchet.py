#!/usr/bin/env python3
"""seat_config_ratchet.py — RETIRED as a mechanism; kept as a name (#1001).

This file used to seed the shared + per-seat vault documents itself, as THREE sequential
per-document PUT writes to the seat surface (prune the seat, write the shared set, write
the seat). That
shape has the failure #987 was built to eliminate: a process or daemon failure, or another
writer, after the first successful PUT leaves a namespace that is non-empty but incomplete,
and the empty-only ratchet then correctly refuses to touch it — the partial bootstrap is
permanent until an operator repairs it by hand. Two tools for one bootstrap, one of them
unsafe, is what current main had after #997; this is the disposition.

WHAT IT DOES NOW. Translates the flags operators' notes name into the one bootstrap path,
`tools/seed_seat_config.py`, and calls it ONCE. That tool plans locally and issues exactly
one `POST /api/config/seed`; the daemon re-checks emptiness under its own lock and commits
every document or none. This wrapper issues no request of its own — the test proves it
never PUTs — and carries no default for anything the vault owns.

FLAGS, and what became of them:
  --home <dir>        the bootstrap locator, HESTIA_HOME. Supplied here or by the launcher;
                      there is no default (the old `~/.hestia` fallback is gone — #944).
  --workspace <dir>   passed through. Still never guessed, still never the cwd.
  --seat <id>         accepted and IGNORED with a note: the seed is whole-box, every
                      installed seat at once, because a box seeded for three of four seats
                      is the partial state the ratchet exists to refuse.
  --role <lct>        accepted and IGNORED with a note: a role is declared by the launcher
                      that starts the seat (hook line, fire script, unit — #984), not
                      seeded into its config. The old tool wrote one; nothing read it.
  --apply             passed through. Dry run without it, as before.

    python3 tools/seat_config_ratchet.py --home ~/.hestia --workspace ~/ai-workspace [--apply]
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("seed_seat_config", HERE / "seed_seat_config.py")
seeder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seeder)


def translate(argv: list[str], environ: dict) -> tuple[list[str] | None, list[str]]:
    """`(seeder argv, notes)` for the legacy flags, or `(None, notes)` when this must refuse.

    Pure, so the translation is testable without running the seeder. `environ` is mutated
    only to carry `--home` into `HESTIA_HOME`: that is the launcher's job, and passing the
    flag is the operator doing the launcher's job by hand — the one form of supplying the
    locator this wrapper accepts. It never fills it in.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seat")
    parser.add_argument("--role")
    parser.add_argument("--workspace")
    parser.add_argument("--home")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    notes: list[str] = []
    if args.seat:
        notes.append(f"--seat {args.seat} ignored: the seed is whole-box (every installed "
                     "seat, one act); a box seeded for one seat is the partial state the "
                     "ratchet refuses")
    if args.role:
        notes.append(f"--role {args.role} ignored: roles are declared by the launcher "
                     "that starts a seat, never seeded into its config (#984)")
    if args.home:
        environ["HESTIA_HOME"] = os.path.expanduser(args.home)
    if not environ.get("HESTIA_HOME"):
        notes.append("HESTIA_HOME is not set and --home was not given. The bootstrap "
                     "locator has no default, by design (#944); nothing is attempted.")
        return None, notes

    out: list[str] = []
    if args.workspace:
        out += ["--workspace", args.workspace]
    if args.apply:
        out.append("--apply")
    return out, notes


def main(argv: list[str] | None = None) -> int:
    seeder_argv, notes = translate(sys.argv[1:] if argv is None else argv, os.environ)
    print("seat_config_ratchet.py is a wrapper over tools/seed_seat_config.py (#1001):")
    print("  one POST /api/config/seed, committed by the daemon all-or-nothing; no PUTs.")
    for note in notes:
        print(f"  ! {note}")
    if seeder_argv is None:
        return 2
    return seeder.main(seeder_argv)


if __name__ == "__main__":
    sys.exit(main())
