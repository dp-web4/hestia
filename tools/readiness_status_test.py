#!/usr/bin/env python3
"""Structural and render-drift tests for the readiness ledger."""

from __future__ import annotations

import re

import readiness_status


EXPECTED_ROWS = {
    "5.1",
    "5.2",
    "5.3",
    "5.4",
    "5.5",
    "5.6",
    "5.7",
    "5.8",
    "non-functional",
    "public-release",
    "demo-target",
}
RUNGS = {"source", "merged", "installed", "restarted", "live", "observed", "publicly released"}
ASSESSMENTS = {"met", "partial", "failed", "unknown"}
GAP_TYPES = {
    "product functionality",
    "security/governance correctness",
    "deployment truth",
    "UX",
    "evidence-only",
}


def main() -> int:
    data = readiness_status.load()
    assert data["schema_version"] == 1
    assert re.fullmatch(r"[0-9a-f]{40}", data["baseline"])
    rows = data["rows"]
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), "duplicate readiness row"
    assert set(ids) == EXPECTED_ROWS, f"readiness row drift: {set(ids) ^ EXPECTED_ROWS}"

    for row in rows:
        assert row["assessment"] in ASSESSMENTS, row["id"]
        assert row["highest_evidence_rung"] in RUNGS, row["id"]
        assert row["rung_basis"].strip(), row["id"]
        assert row["evidence"], row["id"]
        assert row["unknowns"], row["id"]
        assert set(row["gap_types"]) <= GAP_TYPES, row["id"]
        for field in ("blocker_issues", "related_issues", "active_prs"):
            refs = row[field]
            assert refs == sorted(set(refs)), f"{row['id']} {field} must be sorted and unique"
            assert all(isinstance(n, int) and n > 0 for n in refs), row["id"]
        assert not (set(row["blocker_issues"]) & set(row["related_issues"])), row["id"]

    rendered = readiness_status.render(data)
    assert "IMPLEMENTED" not in rendered
    assert readiness_status.OUTPUT.read_text(encoding="utf-8") == rendered, (
        "readiness status drift: run tools/readiness_status.py --write"
    )
    print(f"ok: {len(rows)} readiness rows, deterministic render, explicit evidence vocabulary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
