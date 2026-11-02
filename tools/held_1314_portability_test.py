#!/usr/bin/env python3
"""Hermetic checks of held #1314's contract wrapper; no held code is executed."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "held/build-1314/contract.sh"


class ContractWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base = root / "base"
        self.base.mkdir()
        scratch = root / "scratch"
        scratch.mkdir()
        bins = root / "bin"
        bins.mkdir()
        # Relocate only the temporary output path. The real held contract is
        # never invoked: the timeout executable below is a synthetic stub.
        self.wrapper = root / "contract.sh"
        self.wrapper.write_text(WRAPPER.read_text().replace("/tmp/s1314e", str(scratch)))
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
        timeout.write_text('#!/bin/sh\necho "synthetic contract called"\nexit 42\n')
        for program in (git, timeout):
            program.chmod(0o700)
        self.env = dict(os.environ, HESTIA_1314_BASE=str(self.base),
                        PATH=str(bins) + os.pathsep + os.environ.get("PATH", ""))

    def run_wrapper(self, mode):
        return subprocess.run(["bash", str(self.wrapper)], text=True, capture_output=True,
                              env=dict(self.env, FAKE_GIT_MODE=mode))

    def test_failing_contract_status_is_not_lost(self):
        result = self.run_wrapper("clean")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertIn("synthetic contract called", result.stdout)

    def test_wrong_or_dirty_base_does_not_run_contract(self):
        for mode in ("wrong", "dirty", "error"):
            with self.subTest(mode=mode):
                result = self.run_wrapper(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("synthetic contract called", result.stdout)


if __name__ == "__main__":
    unittest.main()
