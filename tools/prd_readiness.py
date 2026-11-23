#!/usr/bin/env python3
"""Generate and validate Hestia's evidence-ranked PRD readiness ledger.

Usage:
  python3 tools/prd_readiness.py generate
  python3 tools/prd_readiness.py check
  python3 tools/prd_readiness.py check --remote

The JSON is the editable source. The Markdown report and its blocker index are derived
artifacts. A rung names the strongest evidence, not a product-completion verdict. A successful
`check --remote` stamps that verification into the JSON and rewrites the report; a failed check
changes nothing. Offline `check` requires the baseline to be an ancestor of HEAD; `generate`
and `check --remote` also require it to equal current origin/main (a re-measure is claimed).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = pathlib.Path("docs/PRD_READINESS.json")
REPORT = pathlib.Path("docs/PRD_READINESS.md")
RUNGS = ("source", "merged", "installed", "restarted", "live", "observed", "public")
REQUIRED_ROWS = (
    "5.1", "5.2", "5.3", "5.4", "5.5", "5.6", "5.7", "5.8", "5.9",
    "6.seamless", "6.robust", "6.secure", "6.small-fast", "6.cross-platform",
    "6.offline", "6.app-contract", "7.1", "7.2", "7.3", "9.public-release",
)
COVERAGES = ("partial", "demonstrated", "unknown")
GAP_TYPES = {
    "product functionality", "security/governance correctness", "deployment truth",
    "UX", "evidence-only",
}


def load(root: pathlib.Path | None = None) -> dict:
    if root is None:
        root = REPO
    return json.loads((root / DATA).read_text(encoding="utf-8"))


def _positive_ints(value: object) -> bool:
    return (isinstance(value, list)
            and all(type(number) is int and number > 0 for number in value)
            and len(set(value)) == len(value))


def _git(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def baseline_problems(baseline: dict, root: pathlib.Path = REPO) -> list[str]:
    """Offline baseline check: well-formed, and an existing ancestor of HEAD.

    Freshness against origin/main is not checked here: main moves after every merge, and a
    shallow CI checkout has no origin/main. When history is shallow and the commit is absent,
    ancestry is skipped with a note on stderr rather than failed.
    """
    problems = []
    if baseline.get("ref") != "origin/main":
        problems.append("baseline.ref must be origin/main")
    commit = baseline.get("commit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        return problems + ["baseline.commit must be a full lowercase Git commit id"]
    if _git(root, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        if _git(root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true":
            print(f"SKIP baseline.commit {commit[:12]} is not in this shallow history; "
                  "ancestry unchecked", file=sys.stderr)
        else:
            problems.append("baseline.commit does not exist")
    elif _git(root, "merge-base", "--is-ancestor", commit, "HEAD").returncode != 0:
        problems.append("baseline.commit is not an ancestor of HEAD")
    return problems


def freshness_problems(baseline: dict, root: pathlib.Path = REPO) -> list[str]:
    """Re-measure check, run only by `generate` and `check --remote`."""
    head = _git(root, "rev-parse", "--verify", "-q", "origin/main^{commit}")
    if head.returncode != 0:
        return ["origin/main could not be resolved"]
    if baseline.get("commit") != head.stdout.strip():
        return ["baseline.commit is not current origin/main"]
    return []


def validate(data: dict, root: pathlib.Path = REPO) -> list[str]:
    problems = []
    baseline = data.get("baseline", {})
    problems.extend(baseline_problems(baseline, root))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", baseline.get("measured_at", "")):
        problems.append("baseline.measured_at must be a UTC ISO timestamp")

    rows = data.get("rows")
    if not isinstance(rows, list):
        return problems + ["rows must be a list"]
    by_id = {}
    for index, row in enumerate(rows):
        row_id = row.get("id", f"row[{index}]")
        if row_id in by_id:
            problems.append(f"{row_id}: duplicate row id")
        by_id[row_id] = row
        if not row.get("title"):
            problems.append(f"{row_id}: title is required")
        if row.get("coverage") not in COVERAGES:
            problems.append(f"{row_id}: invalid requirement coverage")
        gaps = row.get("gaps")
        if not isinstance(gaps, list) or not gaps or any(gap not in GAP_TYPES for gap in gaps):
            problems.append(f"{row_id}: gaps must use the declared gap vocabulary")
        for field in ("issues", "pull_requests"):
            if not _positive_ints(row.get(field)):
                problems.append(f"{row_id}: {field} must be unique positive integers")

        evidence = row.get("evidence")
        if not isinstance(evidence, list):
            problems.append(f"{row_id}: evidence must be a list")
            continue
        evidenced_rungs = []
        for item in evidence:
            rung = item.get("rung")
            if rung not in RUNGS:
                problems.append(f"{row_id}: invalid evidence rung {rung!r}")
            else:
                evidenced_rungs.append(rung)
            if not item.get("text"):
                problems.append(f"{row_id}: every evidence item needs exact text")
            path = item.get("path")
            url = item.get("url")
            if not path and not url:
                problems.append(f"{row_id}: evidence needs a repo path or GitHub URL")
            if path:
                candidate = pathlib.Path(path)
                if candidate.is_absolute() or ".." in candidate.parts:
                    problems.append(f"{row_id}: evidence path must stay inside the repo: {path}")
                elif not (root / candidate).exists():
                    problems.append(f"{row_id}: evidence path does not exist: {path}")
            if url and not url.startswith("https://github.com/dp-web4/hestia/"):
                problems.append(f"{row_id}: evidence URL must name this Hestia repository")
        expected = "UNKNOWN"
        if evidenced_rungs:
            expected = max(evidenced_rungs, key=RUNGS.index)
        if row.get("rung") != expected:
            problems.append(f"{row_id}: rung {row.get('rung')!r} exceeds or understates evidence; expected {expected!r}")
        if expected == "UNKNOWN" and not row.get("unknown"):
            problems.append(f"{row_id}: UNKNOWN rung requires an explicit unknown field")
        if row.get("coverage") == "demonstrated" and not evidence:
            problems.append(f"{row_id}: demonstrated coverage needs evidence")

    for row_id in REQUIRED_ROWS:
        if row_id not in by_id:
            problems.append(f"missing required PRD row: {row_id}")
    return problems


def _work_links(row: dict, key: str, kind: str) -> list[str]:
    label = "PR " if kind == "pull" else ""
    return [f"[{label}#{number}](https://github.com/dp-web4/hestia/{kind}/{number})"
            for number in row[key]]


def render(data: dict) -> str:
    baseline = data["baseline"]
    lines = [
        "# PRD readiness ledger",
        "",
        "<!-- Generated by tools/prd_readiness.py from docs/PRD_READINESS.json. -->",
        "<!-- Edit the JSON, regenerate this file, and run tools/prd_readiness_test.py. -->",
        "",
        f"- **Baseline:** `{baseline['ref']}` commit `{baseline['commit']}`",
        f"- **Measured:** `{baseline['measured_at']}`",
        f"- **Open work remotely verified:** `{data.get('remote_verified_at', 'NOT CHECKED')}`",
        "",
        "A rung is the strongest named evidence for a row, **not** a claim that the whole requirement is complete.",
        "`partial` coverage can coexist with a high evidence rung. `UNKNOWN` means the current rung was not measured; it is not zero implementation.",
        "",
        "The PRD ladder is `source → merged → installed → restarted → live → observed → public`.",
        "Historical audits remain useful evidence, but only the artifacts named on each row advance this current snapshot.",
        "",
        "## Capability and release rows",
        "",
    ]
    for row in data["rows"]:
        lines.extend([
            f"### {row['id']} — {row['title']}",
            "",
            f"- **Highest evidenced rung:** `{row['rung']}`",
            f"- **Requirement coverage:** `{row['coverage']}`",
            f"- **Gap class:** {', '.join(row['gaps'])}",
        ])
        if row.get("unknown"):
            lines.append(f"- **UNKNOWN:** {row['unknown']}")
        work = _work_links(row, "issues", "issues") + _work_links(row, "pull_requests", "pull")
        lines.append("- **Open work:** " + (", ".join(work) if work else "none linked"))
        lines.extend(["- **Evidence:**"])
        if not row["evidence"]:
            lines.append("  - No current rung-advancing artifact was measured in this sweep.")
        for item in row["evidence"]:
            artifact = f"`{item['path']}`" if item.get("path") else item["url"]
            if item.get("path") and item.get("url"):
                artifact += f" ([run]({item['url']}))"
            lines.append(f"  - **{item['rung']}** — {artifact}: {item['text']}")
        lines.append("")

    blockers = {}
    for row in data["rows"]:
        for kind, field in (("issues", "issues"), ("pull", "pull_requests")):
            for number in row[field]:
                key = (kind, number)
                blockers.setdefault(key, []).append(row["id"])
    lines.extend([
        "## Mechanical open-work index",
        "",
        "This index is derived from the row references above; it is not a hand-maintained release-blocker list.",
        "Run `python3 tools/prd_readiness.py check --remote` to reject references that are no longer open.",
        "",
        "| Reference | Kind | Ledger rows |",
        "|---|---|---|",
    ])
    for (kind, number), row_ids in sorted(blockers.items(), key=lambda item: (item[0][0], item[0][1])):
        label = f"PR #{number}" if kind == "pull" else f"#{number}"
        lines.append(f"| [{label}](https://github.com/dp-web4/hestia/{kind}/{number}) | {kind} | {', '.join(row_ids)} |")
    lines.extend([
        "",
        "## Update procedure",
        "",
        "1. Update only the affected rows in `docs/PRD_READINESS.json`; name exact artifacts and keep unmeasured rungs `UNKNOWN`.",
        "2. Run `python3 tools/prd_readiness.py generate`.",
        "3. Run `python3 tools/prd_readiness_test.py` and `python3 tools/prd_readiness.py check --remote`.",
        "4. Link newly discovered blocking work from the relevant row instead of creating a second status index.",
        "",
    ])
    return "\n".join(lines)


def _open_numbers(root: pathlib.Path, noun: str, runner) -> tuple[set[int], str | None]:
    result = runner(
        ["gh", noun, "list", "--state", "open", "--limit", "1000", "--json", "number",
         "--jq", "[.[].number]"],
        cwd=root, capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode != 0:
        return set(), f"gh {noun} list failed: {result.stderr.strip()}"
    try:
        return set(json.loads(result.stdout)), None
    except (json.JSONDecodeError, TypeError) as error:
        return set(), f"gh {noun} list returned invalid JSON: {error}"


def remote_problems(data: dict, root: pathlib.Path = REPO, runner=subprocess.run) -> list[str]:
    open_issues, issue_error = _open_numbers(root, "issue", runner)
    open_prs, pr_error = _open_numbers(root, "pr", runner)
    problems = [error for error in (issue_error, pr_error) if error]
    if problems:
        return problems
    for row in data["rows"]:
        for number in row["issues"]:
            if number not in open_issues:
                problems.append(f"{row['id']}: issue #{number} is closed or missing")
        for number in row["pull_requests"]:
            if number not in open_prs:
                problems.append(f"{row['id']}: PR #{number} is closed or missing")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "check"))
    parser.add_argument("--remote", action="store_true", help="also require every linked issue and PR to be open")
    args = parser.parse_args(argv)
    data = load()
    problems = validate(data)
    if args.remote or args.command == "generate":
        problems.extend(freshness_problems(data["baseline"]))
    if args.remote:
        problems.extend(remote_problems(data))
    if args.remote and not problems:
        data["remote_verified_at"] = (datetime.now(timezone.utc).replace(microsecond=0)
                                      .isoformat().replace("+00:00", "Z"))
    rendered = render(data)
    report = REPO / REPORT
    if args.remote and not problems:
        (REPO / DATA).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        report.write_text(rendered, encoding="utf-8")
    if args.command == "generate" and not problems:
        report.write_text(rendered, encoding="utf-8")
    elif args.command == "check":
        if not report.exists() or report.read_text(encoding="utf-8") != rendered:
            problems.append(f"{REPORT} is stale; run tools/prd_readiness.py generate")
    if problems:
        for problem in problems:
            print(f"FAIL {problem}")
        return 1
    print(f"OK {len(data['rows'])} PRD rows; {REPORT} is current" if args.command == "check"
          else f"OK generated {REPORT} from {len(data['rows'])} PRD rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
