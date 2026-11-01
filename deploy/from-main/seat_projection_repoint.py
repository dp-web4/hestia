#!/usr/bin/env python3
"""Copy a seat projection into a throwaway home, re-pointing two keys (deploy #1171).

The gate loads its seat projection at import and exports every projected key
OVER the probe's environment, so a preflight that pins HESTIA_SHARED_DIR in the
environment alone pairs the candidate gate with the INSTALLED engine. Both
preflight arms (hestia-deploy.sh's claude-code probe and gate-preflight.py's
per-member runner) therefore probe under a throwaway seat home whose projection
is the seat's own with exactly two keys re-pointed:

- HESTIA_SHARED_DIR -> the candidate tree's plugins/_shared
- HESTIA_HOME       -> the throwaway (the loader realpath-compares the
                       projection's HESTIA_HOME against the launcher's supply
                       and calls a mismatch a miswire)

The rewrite is TEXT, not sed: the replacement side of sed's s/// expands `&`
to the whole match and treats `\\` and the delimiter specially, so a deploy
root like `build&review` corrupted the line it was meant to re-point (GPT
review of #1176). Seat-token-prefixed lines (`TOKEN__KEY=`) keep their prefix;
a key the seat's projection does not carry is appended. The source projection
is never modified.

CLI: seat_projection_repoint.py <member> <src projection> <dst home> <shared dir>
Prints the throwaway home on success. Used by hestia-deploy.sh; gate-preflight.py
imports repoint() directly.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

# A line the loader exports can be plain (`KEY=`) or seat-owned (`TOKEN__KEY=`); either
# spelling must be re-pointed, and the token prefix must survive the rewrite.
_PROJECTED_KEY = re.compile(r"^([A-Za-z0-9_]+__)?(HESTIA_SHARED_DIR|HESTIA_HOME)=")

PROJECTION_DIR = "seats"


def repoint(member: str, src: Path, dst_home: Path, shared_dir: str) -> Path:
    """Write dst_home/seats/<member> projection from src with the two keys re-pointed.

    Returns the throwaway home. Raises OSError/ValueError on an unreadable source; the
    caller decides what an unconfigured seat means (today: probe unchanged).
    """
    lines = src.read_text(encoding="utf-8").splitlines()
    rewritten: list[str] = []
    seen: set[str] = set()
    for line in lines:
        m = _PROJECTED_KEY.match(line)
        if m:
            prefix, key = m.group(1) or "", m.group(2)
            value = shared_dir if key == "HESTIA_SHARED_DIR" else str(dst_home)
            rewritten.append(f"{prefix}{key}={value}")
            seen.add(key)
        else:
            rewritten.append(line)
    if "HESTIA_SHARED_DIR" not in seen:
        rewritten.append(f"HESTIA_SHARED_DIR={shared_dir}")
    if "HESTIA_HOME" not in seen:
        rewritten.append(f"HESTIA_HOME={dst_home}")
    seats = dst_home / PROJECTION_DIR
    seats.mkdir(parents=True, exist_ok=True)
    (seats / f"{member}.env").write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    return dst_home


def main(argv: list[str] | None = None) -> int:
    args = (argv if argv is not None else sys.argv[1:])
    if len(args) != 4:
        print("usage: seat_projection_repoint.py <member> <src projection> <dst home> <shared dir>",
              file=sys.stderr)
        return 2
    member, src, dst_home, shared_dir = args
    repoint(member, Path(src), Path(dst_home), shared_dir)
    print(dst_home)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
