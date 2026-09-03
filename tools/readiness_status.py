#!/usr/bin/env python3
"""Render the current Hestia readiness matrix from its machine-readable ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "readiness_status.json"
OUTPUT = ROOT / "docs" / "STATUS_AUDIT_CURRENT.md"


def load() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def _link(repo: str, kind: str, number: int) -> str:
    plural = "issues" if kind == "issue" else "pull"
    return f"[#{number}](https://github.com/{repo}/{plural}/{number})"


def _refs(repo: str, kind: str, numbers: list[int]) -> str:
    return ", ".join(_link(repo, kind, n) for n in numbers) if numbers else "none"


def render(data: dict) -> str:
    repo = data["repository"]
    lines = [
        "# Hestia current readiness audit",
        "",
        f"**As of:** {data['as_of']}  ",
        f"**Source baseline:** `{data['baseline']}`  ",
        "**Authority:** `docs/readiness_status.json` (this file is generated)  ",
        "**Evidence rule:** source, merged, installed, restarted, live, observed, and publicly "
        "released are different claims. The rung says how far evidence reached; the assessment "
        "says whether that evidence satisfies the requirement. A high rung can therefore carry a "
        "failed assessment.",
        "",
        "> This is a current coordination map, not a replacement for the linked issue records. "
        "An active PR is a candidate change, never implementation evidence. UNKNOWN is preserved "
        "where no durable measurement was found.",
        "",
        "## Executive state",
        "",
        f"- Public daemon: {data['public_artifacts']['daemon']}.",
        f"- Public app: {data['public_artifacts']['app']}.",
        "- The source product is broad and actively used, but it does not yet meet the public-release "
        "bar: onboarding is unproven, the public app/daemon set is unmatched, gate execution is not "
        "one attested authority, and live governance evidence contains known unrecorded and "
        "unrecoverable decisions.",
        "",
        "| PRD row | capability | assessment | highest evidence rung | blockers |",
        "|---|---|---:|---|---:|",
    ]

    for row in data["rows"]:
        lines.append(
            f"| {row['id']} | {row['capability']} | **{row['assessment'].upper()}** | "
            f"{row['highest_evidence_rung']} | {len(row['blocker_issues'])} |"
        )

    lines.extend(["", "## Capability evidence", ""])
    for row in data["rows"]:
        lines.extend(
            [
                f"### {row['id']} - {row['capability']}",
                "",
                f"**Assessment:** {row['assessment'].upper()}  ",
                f"**Highest evidence rung:** {row['highest_evidence_rung']} - {row['rung_basis']}  ",
                f"**Gap types:** {', '.join(row['gap_types'])}  ",
                f"**Blocking issues:** {_refs(repo, 'issue', row['blocker_issues'])}  ",
                f"**Related open evidence/issues:** {_refs(repo, 'issue', row['related_issues'])}  ",
                f"**Active candidate PRs:** {_refs(repo, 'pr', row['active_prs'])}",
                "",
                "Evidence:",
                "",
            ]
        )
        for item in row["evidence"]:
            ref = item["ref"]
            rendered_ref = f"[{ref}]({ref})" if ref.startswith("https://") else f"`{ref}`"
            lines.append(f"- **{item['kind']}:** {rendered_ref} - {item['claim']}")
        lines.extend(["", "UNKNOWN / not demonstrated:", ""])
        for unknown in row["unknowns"]:
            lines.append(f"- {unknown}")
        lines.append("")

    blockers = sorted({n for row in data["rows"] for n in row["blocker_issues"]})
    related = sorted({n for row in data["rows"] for n in row["related_issues"]} - set(blockers))
    prs = sorted({n for row in data["rows"] for n in row["active_prs"]})
    lines.extend(
        [
            "## Mechanical coordination index",
            "",
            "The JSON ledger is the editable source for this section. Its drift test requires every "
            "normative capability row, validates the evidence vocabulary, and regenerates these links.",
            "",
            f"- Distinct blocking issues referenced: {len(blockers)} - {_refs(repo, 'issue', blockers)}.",
            f"- Additional related open issues referenced: {len(related)} - {_refs(repo, 'issue', related)}.",
            f"- Distinct active candidate PRs referenced: {len(prs)} - {_refs(repo, 'pr', prs)}.",
            "- Scope warning: this is the PRD-readiness subset, not the complete research backlog or "
            "open-PR queue. GitHub remains authoritative for open/closed state.",
            "",
            "## Update procedure",
            "",
            "1. Fetch `origin/main` and record its exact full SHA in `docs/readiness_status.json`.",
            "2. Re-run or cite the exact evidence for every row whose source, deployment, or issue state moved.",
            "3. Update issue and PR numbers in the JSON ledger; do not close an evidence issue merely "
            "because it is indexed here.",
            "4. Run `python3 tools/readiness_status.py --write` and "
            "`python3 tools/readiness_status_test.py`.",
            "5. Publish the changed matrix through review, then update the release-readiness issue with "
            "the new baseline and review link.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write docs/STATUS_AUDIT_CURRENT.md")
    parser.add_argument("--check", action="store_true", help="fail when the rendered file drifts")
    args = parser.parse_args()
    rendered = render(load())
    if args.write:
        OUTPUT.write_text(rendered, encoding="utf-8")
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit("readiness status drift: run tools/readiness_status.py --write")
    if not args.write and not args.check:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
