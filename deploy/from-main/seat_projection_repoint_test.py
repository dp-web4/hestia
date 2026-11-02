#!/usr/bin/env python3
"""Behavioural pins for seat_projection_repoint (#1171, #1176 review).

The rewrite that pairs a candidate gate with the candidate engine must be TEXT-safe:
the pre-#1176-review implementation used sed, whose replacement side expands `&` to the
whole match and treats backslash and the delimiter specially — a deploy root of
`build&review` wrote a corrupted HESTIA_SHARED_DIR (GPT's repro). These cases execute
the actual CLI the deploy's shell arm invokes, with hostile characters in every path,
and assert the exact output bytes and an unchanged source projection.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
CLI = HERE / "seat_projection_repoint.py"

SOURCE = (
    "# rendered from the vault by hestia. Do not edit: this file is a projection,\n"
    "# and an edit here is reported as a miswire rather than applied.\n"
    "# member: alpha\n"
    "HESTIA_HOME={old_home}\n"
    "ALPHA__HESTIA_SHARED_DIR={old_shared}\n"
    "HESTIA_STATE_DIR={old_home}/state\n"
    "HESTIA_ENDPOINT=http://127.0.0.1:7711/mcp\n"
)


def run_cli(member: str, src: Path, dst_home: Path, shared_dir: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), member, str(src), str(dst_home), shared_dir],
        text=True, capture_output=True, timeout=10, check=False,
    )


def read_projection(home: Path, member: str) -> str:
    return (home / "seats" / f"{member}.env").read_text(encoding="utf-8")


def test_hostile_paths_are_repointed_literally() -> None:
    """Deploy root and temp home carrying spaces, `&`, `|`, and a backslash survive byte-exact;
    the token prefix survives; unrelated keys are untouched; the source is unchanged."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        hostile = root / "deploy root & review|back\\slash"
        hostile.mkdir()
        old_home = root / "old home & seat|root"
        old_shared = str(old_home / "shared")
        src = root / "src.fixture"
        src.write_text(SOURCE.format(old_home=old_home, old_shared=old_shared), encoding="utf-8")
        before = src.read_bytes()

        dst_home = hostile / "throwaway home"
        new_shared = str(hostile / "hestia" / "plugins" / "_shared")
        completed = run_cli("alpha", src, dst_home, new_shared)
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == str(dst_home), completed.stdout

        out = read_projection(dst_home, "alpha").splitlines()
        assert f"HESTIA_HOME={dst_home}" in out, out
        assert f"ALPHA__HESTIA_SHARED_DIR={new_shared}" in out, out
        assert f"HESTIA_STATE_DIR={old_home}/state" in out, out
        assert "HESTIA_ENDPOINT=http://127.0.0.1:7711/mcp" in out, out
        assert "# member: alpha" in out, out
        # no line may contain the OLD engine path anymore
        assert not any(line.startswith("ALPHA__HESTIA_SHARED_DIR=") and old_shared in line
                       for line in out), out
        assert src.read_bytes() == before, "source projection was modified"


def test_missing_keys_are_appended() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        src = root / "src.fixture"
        src.write_text("# member: alpha\nHESTIA_STATE_DIR=/old/state\n", encoding="utf-8")
        dst_home = root / "throwaway"
        completed = run_cli("alpha", src, dst_home, "/candidate/_shared")
        assert completed.returncode == 0, completed.stderr
        out = read_projection(dst_home, "alpha").splitlines()
        assert "HESTIA_SHARED_DIR=/candidate/_shared" in out, out
        assert f"HESTIA_HOME={dst_home}" in out, out
        assert "HESTIA_STATE_DIR=/old/state" in out, out


def test_plain_keys_without_token_prefix_are_repointed() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        src = root / "src.fixture"
        src.write_text("HESTIA_HOME=/old/home\nHESTIA_SHARED_DIR=/old/shared\n", encoding="utf-8")
        dst_home = root / "throwaway"
        completed = run_cli("alpha", src, dst_home, "/candidate/_shared")
        assert completed.returncode == 0, completed.stderr
        out = read_projection(dst_home, "alpha").splitlines()
        assert "HESTIA_SHARED_DIR=/candidate/_shared" in out, out
        assert f"HESTIA_HOME={dst_home}" in out, out


def test_wrong_arity_is_a_usage_error() -> None:
    completed = subprocess.run(
        [sys.executable, str(CLI), "alpha", "/only/three", "/tmp/x"],
        text=True, capture_output=True, timeout=10, check=False,
    )
    assert completed.returncode == 2
    assert "usage:" in completed.stderr


def test_an_unreadable_source_is_a_nonzero_exit_not_a_silent_pass() -> None:
    completed = run_cli("alpha", Path("/nonexistent"), Path("/tmp/x"), "/shared")
    assert completed.returncode != 0


if __name__ == "__main__":
    test_hostile_paths_are_repointed_literally()
    test_missing_keys_are_appended()
    test_plain_keys_without_token_prefix_are_repointed()
    test_wrong_arity_is_a_usage_error()
    test_an_unreadable_source_is_a_nonzero_exit_not_a_silent_pass()
    print("ok: 5 seat-projection-repoint checks")
