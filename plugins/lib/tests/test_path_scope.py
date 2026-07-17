"""
Tests for path_scope (Gate-1b realpath containment).

Covers Legion's three named escapes (../, symlink, /mnt-absolute) + the
prefix-sibling bug + the new-file-write case + every fail-closed-on-doubt path.
Uses a real temp filesystem with real symlinks — string mocking would miss the
symlink-resolution case, which is the whole point.

Run: python3 -m pytest test_path_scope.py -q   (or: python3 -m unittest)
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from path_scope import check_path, check_paths, ScopeResult  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # granted root: <tmp>/workspace ; out-of-scope sibling: <tmp>/secret
        self.root = os.path.join(self.tmp, "workspace")
        self.secret = os.path.join(self.tmp, "secret")
        os.makedirs(os.path.join(self.root, "sub"))
        os.makedirs(self.secret)
        Path(self.root, "sub", "ok.txt").write_text("ok")
        Path(self.secret, "keys.txt").write_text("sshhh")
        self.roots = [self.root]

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestInScope(Base):
    def test_file_inside_root(self):
        r = check_path(os.path.join(self.root, "sub", "ok.txt"), self.roots, self.root)
        self.assertTrue(r.allowed)
        self.assertEqual(r.matched_root, self.root)

    def test_root_itself(self):
        self.assertTrue(check_path(self.root, self.roots, self.root).allowed)

    def test_relative_path_resolved_against_cwd(self):
        r = check_path("sub/ok.txt", self.roots, cwd=self.root)
        self.assertTrue(r.allowed)

    def test_dot_segments_that_stay_inside_are_ok(self):
        # /root/sub/../sub/ok.txt collapses to /root/sub/ok.txt — still inside
        p = os.path.join(self.root, "sub", "..", "sub", "ok.txt")
        self.assertTrue(check_path(p, self.roots, self.root).allowed)


class TestEscapes(Base):
    def test_dotdot_traversal_denied(self):
        # Legion escape #1
        p = os.path.join(self.root, "..", "secret", "keys.txt")
        r = check_path(p, self.roots, self.root)
        self.assertFalse(r.allowed)
        self.assertIn("secret", r.resolved)

    def test_symlink_escape_denied(self):
        # Legion escape #2: a symlink INSIDE the root pointing OUT
        link = os.path.join(self.root, "escape")
        os.symlink(self.secret, link)
        r = check_path(os.path.join(link, "keys.txt"), self.roots, self.root)
        self.assertFalse(r.allowed, "symlink out of root must be denied")
        self.assertTrue(r.resolved.startswith(os.path.realpath(self.secret)))

    def test_absolute_mnt_denied(self):
        # Legion escape #3 (absolute host path outside roots)
        r = check_path("/etc/passwd", self.roots, self.root)
        self.assertFalse(r.allowed)

    def test_prefix_sibling_not_contained(self):
        # /a/bc must NOT count as inside /a/b — the commonpath-vs-startswith bug
        sibling = self.root + "_evil"   # e.g. .../workspace_evil
        os.makedirs(sibling)
        Path(sibling, "x.txt").write_text("x")
        r = check_path(os.path.join(sibling, "x.txt"), self.roots, self.root)
        self.assertFalse(r.allowed, "string-prefix sibling must not be in scope")


class TestNewFileWrite(Base):
    def test_new_file_in_scope_allowed(self):
        # Legion note 2: a not-yet-existing path resolves via nearest parent
        p = os.path.join(self.root, "sub", "newfile.txt")
        self.assertFalse(os.path.exists(p))
        r = check_path(p, self.roots, self.root, for_write=True)
        self.assertTrue(r.allowed, "new file under an in-scope existing parent must be writable")

    def test_new_file_in_new_subdir_in_scope(self):
        p = os.path.join(self.root, "brand", "new", "deep", "f.txt")
        r = check_path(p, self.roots, self.root, for_write=True)
        self.assertTrue(r.allowed)

    def test_new_file_escaping_via_dotdot_denied(self):
        # nearest-parent resolution must still deny an escaping new-file write
        p = os.path.join(self.root, "sub", "..", "..", "secret", "planted.txt")
        r = check_path(p, self.roots, self.root, for_write=True)
        self.assertFalse(r.allowed)

    def test_new_file_under_symlinked_dir_denied(self):
        link = os.path.join(self.root, "outlink")
        os.symlink(self.secret, link)
        p = os.path.join(link, "planted.txt")   # parent (link) exists, resolves out
        r = check_path(p, self.roots, self.root, for_write=True)
        self.assertFalse(r.allowed)


class TestFailClosed(Base):
    def test_empty_roots_denies(self):
        r = check_path(os.path.join(self.root, "sub", "ok.txt"), [], self.root)
        self.assertFalse(r.allowed)

    def test_unresolvable_roots_deny(self):
        r = check_path(self.root, ["/no/such/root/anywhere"], self.root)
        self.assertFalse(r.allowed)

    def test_nonexistent_root_dropped_not_widened(self):
        # a bogus root alongside a good one: good one still governs, bogus ignored
        r = check_path(os.path.join(self.root, "sub", "ok.txt"),
                       ["/no/such/root", self.root], self.root)
        self.assertTrue(r.allowed)

    def test_empty_path_denies(self):
        self.assertFalse(check_path("", self.roots, self.root).allowed)

    def test_multi_path_denies_if_any_out(self):
        paths = [os.path.join(self.root, "sub", "ok.txt"), "/etc/passwd"]
        r = check_paths(paths, self.roots, self.root)
        self.assertFalse(r.allowed, "one out-of-scope path denies the whole tool call")

    def test_multi_path_all_in_scope_allowed(self):
        paths = [os.path.join(self.root, "sub", "ok.txt"), self.root]
        self.assertTrue(check_paths(paths, self.roots, self.root).allowed)

    def test_multi_path_empty_denies(self):
        self.assertFalse(check_paths([], self.roots, self.root).allowed)


class TestResultShape(Base):
    def test_result_is_falsy_on_deny(self):
        r = check_path("/etc/passwd", self.roots, self.root)
        self.assertFalse(bool(r))
        self.assertIsInstance(r, ScopeResult)

    def test_deny_reason_is_steering(self):
        r = check_path("/etc/passwd", self.roots, self.root)
        # deny reason names the roots and tells the agent what to do (steering,
        # per the kimi exit-2 contract), not just "denied"
        self.assertIn("ask the launching human", r.reason)


if __name__ == "__main__":
    unittest.main()
