"""Regression tests for tools/adjudication_role_census.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from adjudication_role_census import census  # noqa: E402


def entry(hash_: str, prev: str | None, data: dict, timestamp: str) -> dict:
    return {
        "hash": hash_,
        "prevHash": prev,
        "eventType": "adjudication",
        "eventData": data,
        "timestamp": timestamp,
    }


class AdjudicationRoleCensusTests(unittest.TestCase):
    def test_omission_and_non_default_siblings_are_direction_independent(self):
        shared = {"subject_plugin_id": "codex", "axis": "validity", "ref": "same-evidence"}
        rows = [
            entry("new-omitted", "explicit-reviewer", shared | {"score": 0.9}, "2026-11-03"),
            entry("explicit-reviewer", "other-omitted", shared | {
                "subject_role": "role:constellation:reviewer", "score": 0.8,
            }, "2026-11-02"),
            entry("other-omitted", "legacy-string", {
                "subject_plugin_id": "kimi-code", "axis": "validity", "ref": "other",
                "adjudicator": "dp", "score": 0.7,
            }, "2026-11-01"),
            entry("legacy-string", "null-role", {
                "subject_plugin_id": "codex", "axis": "validity", "ref": "legacy",
                "adjudicator": "dp", "score": 0.6,
            }, "2026-10-31"),
            entry("null-role", None, shared | {"subject_role": None, "score": 0.5}, "2026-10-30"),
        ]
        result = census(rows)
        self.assertEqual(result["as_of_head"], "new-omitted")
        self.assertEqual(result["entries_walked"], 5)
        self.assertTrue(result["complete_to_genesis"])
        self.assertFalse(result["truncated_at_max_entries"])
        self.assertEqual(result["adjudications"], 5)
        self.assertEqual(result["subject_role_omitted"], 3)
        self.assertEqual(result["subject_role_null_or_empty"], 1)
        self.assertEqual(result["omitted_with_non_default_role_sibling"], 1)
        self.assertEqual(result["omitted_without_non_default_role_sibling"], 2)
        self.assertEqual(result["sibling_examples"][0]["hash"], "new-omitted")
        self.assertEqual(
            result["sibling_examples"][0]["non_default_roles"],
            ["role:constellation:reviewer"],
        )
        self.assertEqual(result["omitted_writer_shapes"], {"dp": 2, "<unattributed>": 1})
        self.assertEqual(result["oldest_timestamp"], "2026-10-30")
        self.assertEqual(len(result["omitted_hash_sha256"]), 64)

    def test_object_writer_and_truncation_are_reported(self):
        rows = [entry("head", "older", {
            "subject_plugin_id": "codex", "axis": "validity", "ref": "x",
            "adjudicated_by": {"plugin_id": "claude-code"}, "score": 1.0,
        }, "2026-11-03")]
        result = census(rows, max_entries=1)
        self.assertFalse(result["complete_to_genesis"])
        self.assertTrue(result["truncated_at_max_entries"])
        self.assertTrue(result["oldest_has_predecessor"])
        self.assertEqual(result["omitted_writer_shapes"], {"claude-code": 1})

    def test_zero_position_identifies_genesis_with_a_sentinel_predecessor(self):
        genesis = entry("genesis", "0" * 64, {
            "subject_plugin_id": "codex", "axis": "validity", "ref": "first", "score": 1.0,
        }, "2026-05-16")
        genesis["chainPosition"] = 0
        result = census([genesis], max_entries=2)
        self.assertTrue(result["complete_to_genesis"])
        self.assertFalse(result["truncated_at_max_entries"])
        self.assertEqual(result["oldest_hash"], "genesis")
        self.assertEqual(result["oldest_prev_hash"], "0" * 64)
        self.assertEqual(result["oldest_chain_position"], 0)


if __name__ == "__main__":
    unittest.main()
