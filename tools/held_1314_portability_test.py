#!/usr/bin/env python3
"""Hermetic checks of held #1314's contract wrapper; no held code is executed."""
import os
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "held/build-1314/contract.sh"
BUILD = WRAPPER.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(BUILD))
import apply_lib
import scratch
import verify


class ContractWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hestia test " ')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base = root / "base"
        self.base.mkdir()
        self.scratch = scratch.create_scratch(root)
        bins = root / "bin"
        bins.mkdir()
        # The real held contract is never invoked: timeout is a synthetic stub.
        self.wrapper = root / "contract.sh"
        shutil.copyfile(WRAPPER, self.wrapper)
        shutil.copyfile(BUILD / "scratch.py", root / "scratch.py")
        git = bins / "git"
        git.write_text('''#!/bin/sh
case "$1:$2" in
  rev-parse:--show-toplevel) pwd ;;
  rev-parse:--verify) if [ "$3" = HEAD ] && [ "$FAKE_GIT_MODE" = wrong ]; then
    echo wrong; else echo expected; fi ;;
  status:--porcelain) if [ "$FAKE_GIT_MODE" = dirty ]; then echo ' M fixture'; fi
    if [ "$FAKE_GIT_MODE" = error ]; then exit 9; fi ;;
  *) exit 8 ;;
esac
''')
        timeout = bins / "timeout"
        timeout.write_text('#!/bin/sh\necho "$HESTIA_CONTRACT_OVERLAY"\necho "synthetic contract called"\nexit 42\n')
        for program in (git, timeout):
            program.chmod(0o700)
        self.env = dict(os.environ, HESTIA_1314_BASE=str(self.base), HESTIA_1314_SCRATCH=str(self.scratch),
                        PATH=str(bins) + os.pathsep + os.environ.get("PATH", ""))

    def run_wrapper(self, mode):
        return subprocess.run(["bash", str(self.wrapper)], text=True, capture_output=True,
                              env=dict(self.env, FAKE_GIT_MODE=mode))

    def test_failing_contract_status_is_not_lost(self):
        result = self.run_wrapper("clean")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertIn("synthetic contract called", result.stdout)
        self.assertEqual(json.loads(result.stdout.splitlines()[1]),
                         {"hestia_gate_core": str(self.scratch / "core_rev.py")})

    def test_wrong_or_dirty_base_does_not_run_contract(self):
        for mode in ("wrong", "dirty", "error"):
            with self.subTest(mode=mode):
                result = self.run_wrapper(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("synthetic contract called", result.stdout)

    def test_unmarked_scratch_is_refused_before_contract(self):
        env = dict(self.env, HESTIA_1314_SCRATCH=str(self.base), FAKE_GIT_MODE="clean")
        result = subprocess.run(["bash", str(self.wrapper)], text=True,
                                capture_output=True, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("synthetic contract called", result.stdout)
        self.assertFalse((self.base / "contract_out.txt").exists())

    def test_separator_reports_a_failed_synthetic_arm(self):
        wrapper = self.wrapper.parent / "sep.sh"
        shutil.copyfile(BUILD / "sep.sh", wrapper)
        env = dict(self.env, HESTIA_1314_REPO=str(self.base), FAKE_GIT_MODE="clean")
        result = subprocess.run(["bash", str(wrapper)], text=True,
                                capture_output=True, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.count("exit 42"), 3)


class ScratchAndPatchTests(unittest.TestCase):
    def test_unique_private_scratch_and_reject_unsafe_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = scratch.create_scratch(root)
            second = scratch.create_scratch(root)
            self.assertNotEqual(first, second)
            with mock.patch.dict(os.environ, {"HESTIA_1314_SCRATCH": str(first)}):
                self.assertEqual(scratch.require_scratch(), first)
            link = root / "link"
            link.symlink_to(first, target_is_directory=True)
            for value in ("", "relative", str(link), str(root)):
                with self.subTest(value=value), mock.patch.dict(os.environ, {"HESTIA_1314_SCRATCH": value}):
                    with self.assertRaises((RuntimeError, OSError)):
                        scratch.require_scratch()
            first.chmod(0o755)
            with mock.patch.dict(os.environ, {"HESTIA_1314_SCRATCH": str(first)}):
                with self.assertRaises(RuntimeError):
                    scratch.require_scratch()
            first.chmod(0o700)
            marker = first / scratch.MARKER
            marker.write_text("not a marker")
            with mock.patch.dict(os.environ, {"HESTIA_1314_SCRATCH": str(first)}):
                with self.assertRaises(RuntimeError):
                    scratch.require_scratch()
            marker.unlink()
            marker.symlink_to(second / scratch.MARKER)
            with mock.patch.dict(os.environ, {"HESTIA_1314_SCRATCH": str(first)}):
                with self.assertRaises(RuntimeError):
                    scratch.require_scratch()

    def test_exact_patch_digest_uses_only_synthetic_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = b"synthetic fixture only\n"
            digest = hashlib.sha256(data).hexdigest()
            path = root / (digest + ".patch")
            path.write_bytes(data)
            self.assertEqual(verify.checked_patch(root, digest), data.decode())
            for invalid in ("../outside", digest.upper(), digest[:-1]):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    verify.checked_patch(root, invalid)
            path.write_bytes(b"different")
            with self.assertRaises(ValueError):
                verify.checked_patch(root, digest)

    def test_synthetic_patch_context_and_duplicate_paths_are_checked(self):
        lines = ["@@ -1 +1 @@\n", "-expected\n", "+replacement\n"]
        self.assertEqual(apply_lib.apply("expected\n", lines), "replacement\n")
        with self.assertRaises(ValueError):
            apply_lib.apply("different\n", lines)
        duplicate = "diff --git a/x b/x\ndiff --git a/x b/x\n"
        with self.assertRaises(ValueError):
            apply_lib.split(duplicate)
        with self.assertRaises(ValueError):
            apply_lib.apply("expected\n", ["@@ -1 +1 @@\n", "?invalid\n"])
        with self.assertRaises(ValueError):
            apply_lib.apply("expected\n", ["@@ -3 +3 @@\n", " expected\n"])
        for lines in (["@@ -1,2 +1 @@\n", "-expected\n", "+replacement\n"],
                      ["@@ -1 +2 @@\n", "-expected\n", "+replacement\n"],
                      ["@@ malformed @@\n", "-expected\n", "+replacement\n"],
                      ["@@ -1 +1 @@\n", "-expected\n", "+replacement\n",
                       "\\ No newline at end of file\n"]):
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                apply_lib.apply("expected\n", lines)
        with self.assertRaises(ValueError):
            apply_lib.split("diff --git a/x b/y\n")
        self.assertEqual(apply_lib.apply("old\n", ["@@ -0,0 +1 @@\n", "+new\n"]),
                         "new\nold\n")
        self.assertEqual(apply_lib.apply("old\n", ["@@ -1 +0,0 @@\n", "-old\n"]), "")
        self.assertEqual(apply_lib.apply("a\nb\nc\n", [
            "@@ -1 +1 @@\n", "-a\n", "+A\n",
            "@@ -3 +3,2 @@\n", " c\n", "+d\n"]), "A\nb\nc\nd\n")

    def test_verifier_fails_on_synthetic_reconstruction_mismatch(self):
        # Neither real repository data nor a held patch is read: git and the
        # patch are synthetic, and apply_lib only constructs strings in memory.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = scratch.create_scratch(root)
            bins = root / "bin"
            bins.mkdir()
            git = bins / "git"
            git.write_text('#!/bin/sh\nprintf "old\\n"\n')
            git.chmod(0o700)
            names = ["plugins/_shared/hestia_gate_core.py",
                     "tools/shell_scope_reach_battery_test.py",
                     "tools/one_gate_decide_contract_test.py"]
            data = "".join(f"diff --git a/{name} b/{name}\n@@ -1 +1 @@\n-old\n+new\n"
                           for name in names).encode()
            digest = hashlib.sha256(data).hexdigest()
            (workspace / (digest + ".patch")).write_bytes(data)
            for name in ("core_rev.py", "battery_rev.py", "contract_held.py"):
                (workspace / name).write_text("new\n")
            env = dict(os.environ, HESTIA_1314_SCRATCH=str(workspace),
                       HESTIA_1314_PATCH_SHA=digest, HESTIA_1314_REPO=str(root),
                       PATH=str(bins) + os.pathsep + os.environ.get("PATH", ""),
                       PYTHONDONTWRITEBYTECODE="1")
            command = [sys.executable, str(BUILD / "verify.py")]
            okay = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(okay.returncode, 0, okay.stderr)
            (workspace / "core_rev.py").write_text("different\n")
            bad = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("reconstructed bytes differ", bad.stderr)


if __name__ == "__main__":
    unittest.main()
