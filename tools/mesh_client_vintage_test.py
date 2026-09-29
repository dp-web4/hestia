#!/usr/bin/env python3
"""The vintage walk must follow the declared anchor, never the checkout branch."""

from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "mesh_client_vintage_under_test", HERE / "mesh_client_vintage.py"
)
VINTAGE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VINTAGE)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(repo), *args),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo = root / "repo"
        installed = root / "installed.py"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "vintage-test")
        git(repo, "config", "user.email", "vintage@example.invalid")

        tracked = repo / VINTAGE.TRACKED
        write(tracked, "base\n")
        git(repo, "add", VINTAGE.TRACKED)
        git(repo, "commit", "-qm", "base")
        base = git(repo, "rev-parse", "HEAD")

        # Build a main-only vintage and then a newer main head.
        git(repo, "switch", "-qc", "main-line")
        write(tracked, "installed-main-vintage\n")
        git(repo, "commit", "-qam", "main vintage")
        vintage = git(repo, "rev-parse", "HEAD")
        installed.write_bytes(tracked.read_bytes())
        write(tracked, "current-main\n")
        git(repo, "commit", "-qam", "current main")
        current = git(repo, "rev-parse", "HEAD")
        git(repo, "update-ref", "refs/remotes/origin/main", current)

        # The checkout cannot reach the installed vintage. The anchor can.
        git(repo, "switch", "-q", "--detach", base)
        write(repo / "side-only.txt", "side\n")
        git(repo, "add", "side-only.txt")
        git(repo, "commit", "-qm", "divergent checkout")
        ancestry = subprocess.run(
            ("git", "-C", str(repo), "merge-base", "--is-ancestor", vintage, "HEAD")
        )
        assert ancestry.returncode == 1

        saved_repo, saved_seats, saved_argv = VINTAGE.REPO, VINTAGE.SEATS, sys.argv
        VINTAGE.REPO = str(repo)
        VINTAGE.SEATS = {"probe": str(installed)}
        sys.argv = ["mesh_client_vintage.py", "origin/main"]
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                rc = VINTAGE.main()
        finally:
            VINTAGE.REPO, VINTAGE.SEATS, sys.argv = saved_repo, saved_seats, saved_argv

        rendered = output.getvalue()
        if rc != 1 or "probe        STALE" not in rendered or vintage[:12] not in rendered:
            print(rendered, file=sys.stderr)
            print(
                "FAIL: a main-line vintage was not identified while HEAD was divergent",
                file=sys.stderr,
            )
            return 1

    print("ok: vintage history follows origin/main even from a divergent checkout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
