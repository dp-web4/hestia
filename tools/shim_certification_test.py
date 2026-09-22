"""Falsifiers for tools/shim_certification.py. Run directly by CI."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("shim_certification", HERE / "shim_certification.py")
assert SPEC and SPEC.loader
sc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sc)

SEATS = sc.REPO_SHIMS
RUNTIME = ("hestia_single_gate.py", "hestia_gate_core.py")


def fixture():
    td = tempfile.TemporaryDirectory()
    root = Path(td.name) / "repo"
    home = Path(td.name) / "home"
    shared = root / "plugins" / "_shared"
    deployed = home / "shared"
    shared.mkdir(parents=True)
    deployed.mkdir(parents=True)
    (shared / "RUNTIME_MANIFEST.txt").write_text("\n".join(RUNTIME) + "\n", encoding="utf-8")
    for name in RUNTIME:
        payload = f"# {name}\nVALUE = 1\n"
        (shared / name).write_text(payload, encoding="utf-8")
        (deployed / name).write_text(payload, encoding="utf-8")
    for seat, parts in SEATS.items():
        repo_shim = root / "plugins" / Path(*parts)
        repo_shim.parent.mkdir(parents=True, exist_ok=True)
        repo_shim.write_text(f"# {seat}\nPROFILE = {{}}\n", encoding="utf-8")
        dep_parts = sc.DEPLOYED_SHIMS[seat]
        # Rebase the declared ~/. paths under the fixture home.
        rel = Path(*dep_parts[1:])
        dep_shim = home.parent / rel if dep_parts[0] != "~" else Path(td.name) / "user" / rel
        # The module uses expanduser, so HOME must point at this user dir.
        user = Path(td.name) / "user"
        dep_shim = user / rel
        dep_shim.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo_shim, dep_shim)
    return td, root, home, Path(td.name) / "user"


def with_fixture(fn):
    td, root, home, user = fixture()
    old = dict(os.environ)
    try:
        os.environ["HESTIA_REPO_ROOT"] = str(root)
        os.environ["HESTIA_HOME"] = str(home)
        os.environ["HOME"] = str(user)
        fn(root, home, user)
    finally:
        os.environ.clear(); os.environ.update(old)
        td.cleanup()


def test_identical_repo_and_deployed_subject_match():
    def run(_root, _home, _user):
        for seat in SEATS:
            assert sc.certification(seat, False)["certification_sha256"] == \
                   sc.certification(seat, True)["certification_sha256"]
    with_fixture(run)


def test_runtime_mutation_invalidates_every_seat_without_changing_shim():
    def run(_root, home, _user):
        before = {s: sc.certification(s, True) for s in SEATS}
        (home / "shared" / RUNTIME[0]).write_text("VALUE = 2\n", encoding="utf-8")
        after = {s: sc.certification(s, True) for s in SEATS}
        for seat in SEATS:
            assert before[seat]["shim_sha256_raw"] == after[seat]["shim_sha256_raw"]
            assert before[seat]["certification_sha256"] != after[seat]["certification_sha256"]
    with_fixture(run)


def test_missing_runtime_is_unknown_not_a_shorter_hash():
    def run(_root, home, _user):
        (home / "shared" / RUNTIME[1]).unlink()
        try:
            sc.certification("codex", True)
        except sc.Unknown:
            return
        raise AssertionError("missing runtime must not produce a certification")
    with_fixture(run)


TESTS = [
    test_identical_repo_and_deployed_subject_match,
    test_runtime_mutation_invalidates_every_seat_without_changing_shim,
    test_missing_runtime_is_unknown_not_a_shorter_hash,
]

if __name__ == "__main__":
    declared = {n for n, v in globals().items() if n.startswith("test_") and callable(v)}
    listed = {fn.__name__ for fn in TESTS}
    assert declared == listed, f"TESTS drift: declared={declared} listed={listed}"
    for test in TESTS:
        test()
    print(f"OK - {len(TESTS)} shim certification tests")
