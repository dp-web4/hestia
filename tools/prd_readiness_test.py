#!/usr/bin/env python3
"""Contract tests for the generated PRD readiness ledger (#746)."""

from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import tempfile
import unittest
from types import SimpleNamespace

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC = importlib.util.spec_from_file_location("prd_readiness", HERE / "prd_readiness.py")
PR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PR)


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
        def runner(args, **_kwargs):
            if args[1] == "issue":
                numbers = sorted({number for row in self.data["rows"] for number in row["issues"]})
            else:
                numbers = sorted({number for row in self.data["rows"] for number in row["pull_requests"]})
            return SimpleNamespace(returncode=0, stdout=json.dumps(numbers), stderr="")

        self.assertEqual(PR.remote_problems(self.data, runner=runner), [])

    def test_remote_check_rejects_closed_or_missing_references(self):
        def runner(args, **_kwargs):
            if args[1] == "issue":
                numbers = sorted({number for row in self.data["rows"] for number in row["issues"]})
                numbers.remove(self.data["rows"][0]["issues"][0])
            else:
                numbers = sorted({number for row in self.data["rows"] for number in row["pull_requests"]})
            return SimpleNamespace(returncode=0, stdout=json.dumps(numbers), stderr="")

        self.assertTrue(any("closed or missing" in problem
                            for problem in PR.remote_problems(self.data, runner=runner)))

    def test_remote_transport_failure_is_not_silent(self):
        def runner(_args, **_kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="unavailable")

        problems = PR.remote_problems(self.data, runner=runner)
        self.assertTrue(problems)
        self.assertIn("unavailable", problems[0])

    def test_future_row_update_can_regenerate_incrementally(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "docs").mkdir()
            updated = copy.deepcopy(self.data)
            updated["rows"][0]["unknown"] = "A new measurement is still owed."
            (root / PR.DATA).write_text(json.dumps(updated), encoding="utf-8")
            loaded = PR.load(root)
            self.assertEqual(PR.validate(loaded, ROOT), [])
            self.assertIn("A new measurement is still owed.", PR.render(loaded))


if __name__ == "__main__":
    unittest.main()
