#!/usr/bin/env python3
"""Contract tests for the generated PRD readiness ledger (#746)."""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC = importlib.util.spec_from_file_location("prd_readiness", HERE / "prd_readiness.py")
PR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PR)


def _run_git(cwd: pathlib.Path, *args: str) -> str:
    result = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                            cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _open_runner(data: dict, drop_issue: int | None = None, drafts: set = frozenset()):
    """A `gh ... list` stand-in that reports every referenced issue and PR open."""
    def runner(args, **_kwargs):
        if args[1] == "issue":
            numbers = sorted({n for row in data["rows"] for n in row["issues"]} - {drop_issue})
            payload = [{"number": n} for n in numbers]
        else:
            numbers = sorted({n for row in data["rows"] for n in row["pull_requests"]})
            payload = [{"number": n, "isDraft": n in drafts} for n in numbers]
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
    return runner


def _two_commit_repo(repo: pathlib.Path) -> tuple[str, str]:
    repo.mkdir()
    _run_git(repo, "init", "-q")
    commits = []
    for name in ("a", "b"):
        (repo / name).write_text(name, encoding="utf-8")
        _run_git(repo, "add", name)
        _run_git(repo, "commit", "-q", "-m", name)
        commits.append(_run_git(repo, "rev-parse", "HEAD"))
    return commits[0], commits[1]


class ReadinessTest(unittest.TestCase):
    def setUp(self):
        self.data = PR.load()

    def test_repository_data_and_generated_report_are_current(self):
        self.assertEqual(PR.validate(self.data), [])
        self.assertEqual((ROOT / PR.REPORT).read_text(encoding="utf-8"), PR.render(self.data))

    def test_every_normative_row_is_present(self):
        row_ids = {row["id"] for row in self.data["rows"]}
        self.assertEqual(row_ids, set(PR.REQUIRED_ROWS))

    def test_missing_row_is_rejected(self):
        broken = copy.deepcopy(self.data)
        broken["rows"] = [row for row in broken["rows"] if row["id"] != "5.5"]
        self.assertIn("missing required PRD row: 5.5", PR.validate(broken))

    def test_offline_baseline_check_does_not_require_current_origin_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            first, second = _two_commit_repo(repo)
            # origin/main moved past the baseline: offline check still passes.
            _run_git(repo, "update-ref", "refs/remotes/origin/main", second)
            self.assertEqual(PR.baseline_problems({"ref": "origin/main", "commit": first}, repo), [])
            # No origin/main at all (shallow CI checkout): offline check still passes.
            _run_git(repo, "update-ref", "-d", "refs/remotes/origin/main")
            self.assertEqual(PR.baseline_problems({"ref": "origin/main", "commit": first}, repo), [])

    def test_shallow_checkout_without_baseline_commit_skips_ancestry(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            first, _second = _two_commit_repo(repo)
            shallow = pathlib.Path(tmp) / "shallow"
            _run_git(pathlib.Path(tmp), "clone", "-q", "--depth", "1", repo.as_uri(), str(shallow))
            self.assertEqual(PR.baseline_problems({"ref": "origin/main", "commit": first}, shallow), [])

    def test_baseline_must_exist_and_be_an_ancestor_in_full_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            first, second = _two_commit_repo(repo)
            self.assertIn("baseline.commit does not exist", PR.baseline_problems(
                {"ref": "origin/main", "commit": "7f0a9da8f910b7d5505278e072bf3e4f4d79103f"}, repo))
            _run_git(repo, "checkout", "-q", first)
            self.assertIn("baseline.commit is not an ancestor of HEAD", PR.baseline_problems(
                {"ref": "origin/main", "commit": second}, repo))

    def test_stale_baseline_is_rejected_by_the_remeasure_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            first, second = _two_commit_repo(repo)
            self.assertEqual(PR.freshness_problems({"commit": first}, repo),
                             ["origin/main could not be resolved"])
            _run_git(repo, "update-ref", "refs/remotes/origin/main", second)
            self.assertEqual(PR.freshness_problems({"commit": first}, repo),
                             ["baseline.commit is not current origin/main"])
            self.assertEqual(PR.freshness_problems({"commit": second}, repo), [])

    def test_rung_cannot_exceed_named_evidence(self):
        broken = copy.deepcopy(self.data)
        broken["rows"][0]["rung"] = "public"
        self.assertTrue(any("exceeds or understates evidence" in problem
                            for problem in PR.validate(broken)))

    def test_unknown_rung_requires_an_explicit_unknown(self):
        broken = copy.deepcopy(self.data)
        row = next(row for row in broken["rows"] if row["rung"] == "UNKNOWN")
        row["unknown"] = ""
        self.assertTrue(any("requires an explicit unknown" in problem
                            for problem in PR.validate(broken)))

    def test_missing_evidence_path_is_rejected(self):
        broken = copy.deepcopy(self.data)
        broken["rows"][0]["evidence"][0]["path"] = "docs/DOES_NOT_EXIST.md"
        self.assertTrue(any("evidence path does not exist" in problem
                            for problem in PR.validate(broken)))

    def test_evidence_must_name_an_artifact(self):
        broken = copy.deepcopy(self.data)
        item = broken["rows"][0]["evidence"][0]
        del item["path"]
        self.assertTrue(any("needs a repo path or GitHub URL" in problem
                            for problem in PR.validate(broken)))

    def test_open_work_index_is_derived_from_every_row(self):
        expected = {}
        for row in self.data["rows"]:
            for kind, field in (("issues", "issues"), ("pull", "pull_requests")):
                for number in row[field]:
                    expected.setdefault((kind, number), set()).add(row["id"])
        for (kind, number), row_ids in expected.items():
            label = f"PR #{number}" if kind == "pull" else f"#{number}"
            self.assertIn(f"[{label}](https://github.com/dp-web4/hestia/{kind}/{number})",
                          PR.render(self.data))
            for row_id in row_ids:
                self.assertIn(row_id, PR.render(self.data))

    def test_remote_check_accepts_only_open_references(self):
        self.assertEqual(PR.remote_problems(self.data, runner=_open_runner(self.data)), [])

    def _run_main_in(self, root, data, argv, remote=(), stub_remote=True):
        (root / "docs").mkdir(exist_ok=True)
        (root / PR.DATA).write_text(json.dumps(data), encoding="utf-8")
        saved = PR.REPO, PR.validate, PR.remote_check, PR.freshness_problems, PR.staleness_note
        PR.REPO = root
        PR.validate = lambda _data: []
        if stub_remote:
            PR.remote_check = lambda _data, **_kwargs: (list(remote), [])
        PR.freshness_problems = lambda _baseline: []
        PR.staleness_note = lambda _baseline: None
        try:
            return PR.main(argv)
        finally:
            PR.REPO, PR.validate, PR.remote_check, PR.freshness_problems, PR.staleness_note = saved

    def test_remote_check_stamps_success_into_json_and_report(self):
        unstamped = copy.deepcopy(self.data)
        unstamped.pop("remote_verified_at", None)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.assertEqual(self._run_main_in(root, unstamped, ["check", "--remote"]), 0)
            written = json.loads((root / PR.DATA).read_text(encoding="utf-8"))
            stamp = written.get("remote_verified_at")
            self.assertIsNotNone(stamp, "a successful remote check must stamp the JSON")
            self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertIn(f"Open work remotely verified:** `{stamp}`",
                          (root / PR.REPORT).read_text(encoding="utf-8"))

    def test_failed_remote_check_changes_nothing(self):
        unstamped = copy.deepcopy(self.data)
        unstamped.pop("remote_verified_at", None)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "docs").mkdir()
            (root / PR.REPORT).write_text("previous report\n", encoding="utf-8")
            before = json.dumps(unstamped)
            status = self._run_main_in(root, unstamped, ["check", "--remote"],
                                       remote=["5.1: issue #1 is closed or missing"])
            self.assertEqual(status, 1)
            self.assertEqual((root / PR.DATA).read_text(encoding="utf-8"), before)
            self.assertEqual((root / PR.REPORT).read_text(encoding="utf-8"), "previous report\n")

    def test_remote_check_rejects_closed_or_missing_references(self):
        closed = self.data["rows"][0]["issues"][0]
        self.assertTrue(any("closed or missing" in problem for problem in PR.remote_problems(
            self.data, runner=_open_runner(self.data, drop_issue=closed))))

    def test_remote_transport_failure_is_not_silent(self):
        def runner(_args, **_kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="unavailable")

        problems = PR.remote_problems(self.data, runner=runner)
        self.assertTrue(problems)
        self.assertIn("unavailable", problems[0])

    # NOVA 2026-11-22: pinning, staleness, UNKNOWN on API failure, demonstration vs source.

    def test_generated_report_pins_source_commit_and_measured_at_as_a_snapshot(self):
        report = PR.render(self.data)
        self.assertIn(f"commit `{self.data['baseline']['commit']}`", report)
        self.assertIn(f"`{self.data['baseline']['measured_at']}`", report)
        self.assertIn("**Snapshot, not live state:**", report)
        for key in ("commit", "measured_at"):
            broken = copy.deepcopy(self.data)
            del broken["baseline"][key]
            self.assertTrue(PR.validate(broken), f"a baseline without {key} must not validate")

    def test_remote_stamp_cannot_predate_the_measurement(self):
        broken = copy.deepcopy(self.data)
        broken["remote_verified_at"] = "2000-01-01T00:00:00Z"
        self.assertIn("remote_verified_at predates baseline.measured_at", PR.validate(broken))
        broken["remote_verified_at"] = "yesterday"
        self.assertIn("remote_verified_at must be a UTC ISO timestamp", PR.validate(broken))

    def test_measured_at_cannot_predate_the_baseline_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            first, _second = _two_commit_repo(repo)
            self.assertIn("baseline.measured_at predates the baseline commit", PR.baseline_problems(
                {"ref": "origin/main", "commit": first, "measured_at": "2000-01-01T00:00:00Z"}, repo))
            self.assertEqual(PR.baseline_problems(
                {"ref": "origin/main", "commit": first, "measured_at": "2999-01-01T00:00:00Z"}, repo), [])

    def test_offline_check_names_a_stale_baseline_instead_of_passing_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            first, second = _two_commit_repo(repo)
            _run_git(repo, "update-ref", "refs/remotes/origin/main", second)
            note = PR.staleness_note({"commit": first, "measured_at": "2026-11-23T00:00:00Z"}, repo)
            self.assertIn("STALE", note)
            self.assertIn("1 commit(s) behind origin/main", note)
            self.assertIsNone(PR.staleness_note({"commit": second}, repo))
            _run_git(repo, "update-ref", "-d", "refs/remotes/origin/main")
            self.assertIn("UNKNOWN", PR.staleness_note({"commit": first}, repo))

    def test_offline_check_never_reaches_the_remote(self):
        def refuse(*_args, **_kwargs):
            raise AssertionError("offline check must not call GitHub")
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "docs").mkdir()
            (root / PR.REPORT).write_text(PR.render(self.data), encoding="utf-8")
            saved = PR.remote_check
            PR.remote_check = refuse
            try:
                self.assertEqual(self._run_main_in(root, self.data, ["check"], stub_remote=False), 0)
            finally:
                PR.remote_check = saved

    def test_remote_api_failure_is_unknown_not_no_blockers(self):
        def down(_args, **_kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="HTTP 502")
        unstamped = copy.deepcopy(self.data)
        unstamped.pop("remote_verified_at", None)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "docs").mkdir()
            before = PR.render(unstamped)
            (root / PR.REPORT).write_text(before, encoding="utf-8")
            out = io.StringIO()
            saved = PR.remote_check
            PR.remote_check = lambda data, **_kw: saved(data, runner=down)
            try:
                with contextlib.redirect_stdout(out):
                    status = self._run_main_in(root, unstamped, ["check", "--remote"], stub_remote=False)
            finally:
                PR.remote_check = saved
            self.assertEqual(status, 2, "API failure is UNKNOWN (exit 2), not FAIL and not OK")
            self.assertIn("UNKNOWN open-work state", out.getvalue())
            self.assertNotIn("OK", out.getvalue())
            self.assertNotIn("remote_verified_at", (root / PR.DATA).read_text(encoding="utf-8"))
            self.assertEqual((root / PR.REPORT).read_text(encoding="utf-8"), before)

    def test_truncated_or_malformed_listing_is_unknown(self):
        def full(args, **_kwargs):
            limit = int(args[args.index("--limit") + 1])
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                [{"number": n, "isDraft": False} for n in range(1, limit + 1)]), stderr="")
        problems, _drafts = PR.remote_check(self.data, runner=full)
        self.assertTrue(problems and all(p.startswith("UNKNOWN") for p in problems), problems)
        for payload in ("{}", "null", "[1, 2]"):
            def odd(_args, **_kwargs):
                return SimpleNamespace(returncode=0, stdout=payload, stderr="")
            problems, _drafts = PR.remote_check(self.data, runner=odd)
            self.assertTrue(problems and all(p.startswith("UNKNOWN") for p in problems),
                            f"{payload}: {problems}")

    def test_draft_prs_are_marked_and_unverified_state_is_unknown(self):
        linked = sorted({n for row in self.data["rows"] for n in row["pull_requests"]})
        draft = linked[0]
        problems, drafts = PR.remote_check(self.data, runner=_open_runner(self.data, drafts={draft}))
        self.assertEqual((problems, drafts), ([], [draft]))
        stamped = copy.deepcopy(self.data)
        stamped["remote_verified_at"] = "2999-01-01T00:00:00Z"
        stamped["remote_draft_pull_requests"] = drafts
        report = PR.render(stamped)
        self.assertIn(f"[PR #{draft}](https://github.com/dp-web4/hestia/pull/{draft}) (draft)", report)
        self.assertIn(f"| pull | draft at remote check |", report)
        unverified = copy.deepcopy(self.data)
        unverified.pop("remote_verified_at", None)
        unverified.pop("remote_draft_pull_requests", None)
        report = PR.render(unverified)
        self.assertIn("UNKNOWN — not remotely verified", report)
        self.assertNotIn("open at remote check", report)

    def test_demonstrated_coverage_needs_an_acceptance_rung_not_a_merged_file(self):
        broken = copy.deepcopy(self.data)
        row = next(row for row in broken["rows"] if row["rung"] == "merged")
        row["coverage"] = "demonstrated"
        self.assertIn(f"{row['id']}: demonstrated coverage needs observed or public evidence, "
                      "not a source or merged artifact", PR.validate(broken))

    def test_future_row_update_can_regenerate_incrementally(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            updated = copy.deepcopy(self.data)
            updated["rows"][0]["unknown"] = "A new measurement is still owed."
            self.assertEqual(self._run_main_in(root, updated, ["generate"]), 0)
            report = root / PR.REPORT
            self.assertTrue(report.exists())
            self.assertIn("A new measurement is still owed.", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
