#!/usr/bin/env python3
"""Reviewer role — discover what needs review, and who may review it.

dp, 2026-07-28: *"make sure this is integrated as a hestia role not a standalone."*

WHAT THIS REPLACES. `private-context/supervisor/scripts/autonomous-legion-reviewer.sh` is a
good script and most of it should survive — fresh context per session, worktree isolation,
schedule offset from the workers, separate account routing. Its one structural flaw is a
**hardcoded three-repo array** from an earlier sprint. Measured 2026-07-28: those three
(`4-life`, `hardbound`, `web4`) held **zero** open PRs, while **17** sat unreviewed across six
repos the reviewer could not see. HUB's census puts the long-run shape on it — 1,528 PRs
across 72 repos, **one** approved review ever.

So the reviewer worked. It was aimed at an empty room.

WHY A ROLE AND NOT A CRON JOB. A standalone script reviews and leaves no trace in the trust
record: its judgment accrues to nobody, its liveness is invisible, and it is subject to no
law. As a hestia role it connects declaring `role:constellation:reviewer`, so every act lands
on the reviewer grain rather than defaulting to `member` (the split #89 fixed), its decisions
are witnessed, and its standing as a reviewer becomes the thing that selection reads — which
is what the reviewer-role proposal needs and cannot get from a script.

NOT-SAME IS A PREFERENCE, NOT A FILTER — and the first cut of this file got that wrong.

dp, 2026-07-28: *"i don't think we need to reject on not-same. earlier we discussed the
selection process — prefer others, if available, but accept same if that's all we have. many
installations will only have one vendored agent."* And: *"the entire fleet has run on just
you (claude) for a year now. we've only had external participants via forum until a week
ago."*

That reframes the whole thing. Same-member review is not a degraded edge case to be refused —
it is the mode that **built this system**, for a year, and it is the only mode available to a
single-agent installation. A reviewer that refuses it does not get independence; it gets **no
review at all**, which is strictly worse. The independence that matters comes from the ROLE's
constructed context (a fresh session reviewing an artifact, blind to the authoring session's
reasoning), not from the substrate differing.

So the queue is RANKED, never filtered:

    tier 0  different member  — preferred
    tier 1  attribution unknown — reviewed, and the doubt is stated
    tier 2  same member, fresh role context — admissible, ranked last, RECORDED as such

Nothing is dropped. A reader of the review can see which tier produced it and weigh it
accordingly, which is the evidence-not-declaration posture the rest of the stack uses.

Authorship itself is recovered from commit trailers (`Web4-Member:`, then `Co-Authored-By:`)
and failing those a body signature. GitHub cannot help — every PR in this org is authored by
one shared account. Measured today: of 21 trailers on recent main, 17 name a MODEL
("Claude Opus 5") and 4 name a member, so tier 1 is currently the common case rather than the
exception. That is a fact about the record, reported rather than papered over.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any, Optional

ORG = os.environ.get("REVIEWER_ORG", "dp-web4")
# The reviewing member, so it can exclude its own work. Set by the launcher from
# the member's identity, never inferred from the host.
SELF_MEMBER = os.environ.get("HESTIA_MESH_PLUGIN") or os.environ.get("REVIEWER_MEMBER") or ""
TIMEOUT = 45


def gh(*args: str, default: Any = None) -> Any:
    """Run gh; return parsed JSON, or the RAW TEXT when it is not JSON.

    The first version did `json.loads(out.stdout)` unconditionally. Two of the three
    call sites pass `--jq`, whose output is raw text — so both raised JSONDecodeError,
    fell to `default`, and the entire attribution pipeline became dead code: `blob` was
    always "", the commit-trailer path never ran, and the body fallback never saw a body.

    The instrument then reported "16/16 author-undetermined" and I wrote that up as a
    measurement of the record. It was a measurement of the probe. kimi-code, reviewing:
    "an absence produced by a broken probe, reported as a fact about the world" — the
    fleet's own named class, landing on the role built to hunt it.

    Worse than the bug: I "verified" the extraction with a separate `git log` command and
    reported that the extraction works. I tested the concept and shipped the code.
    """
    try:
        out = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
        if out.returncode != 0:
            return default
        text = out.stdout.strip()
        if not text:
            return default
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text  # --jq output: raw, and meant to be
    except (subprocess.TimeoutExpired, OSError):
        return default


MEMBER_RE = re.compile(
    r"^(?:Web4-Member|Co-Authored-By):\s*([A-Za-z0-9._-]+)", re.MULTILINE | re.IGNORECASE
)
SIGNOFF_RE = re.compile(r"^\s*—\s*([a-z0-9-]+(?:-code)?)\s*$", re.MULTILINE)
# Trailers naming a MODEL rather than a member carry no attribution — the distinction
# this fleet keeps rediscovering. "Claude Opus 5" is not a member; "claude-code" is.
#
# EXACT match on the bare family name, deliberately. The first version used `^claude\s`,
# but MEMBER_RE captures `([A-Za-z0-9._-]+)` which stops AT the space — so the captured
# token is "Claude" with nothing after it and the pattern never fired. Fixing the probe
# above exposed it immediately: every PR began attributing to "Claude". A guard written
# against a string shape the capture cannot produce is a guard that has never run.
_MODEL_WORDS = {"claude", "opus", "sonnet", "haiku", "gpt", "gemini", "kimi", "noreply", "anthropic"}


def _is_model_not_member(token: str) -> bool:
    """A BARE family name is a model. A hyphenated id is a member.

    `kimi` is in the set and `kimi-code` is not, which is the correct split — but note
    the imprecision it leaves: a trailer reading exactly `Co-Authored-By: Kimi` (one such
    exists on recent main) is discarded rather than resolved to `kimi-code`. Guessing the
    mapping would manufacture attribution, which is the thing this file exists to stop
    doing. It is reported as undetermined, and the fix is at the writing end."""
    return token.strip().lower() in _MODEL_WORDS


def author_member(repo: str, number: int, body: str) -> tuple[Optional[str], str]:
    """Best available attribution for a PR, with the basis reported.

    Returns (member_or_None, basis). The basis is carried so a reader can weigh
    the claim — a trailer is stronger than a signature, and both are weaker than
    an authenticated identity we do not yet have (HST-005)."""
    commits = gh(
        "pr", "view", str(number), "--repo", f"{ORG}/{repo}",
        "--json", "commits", "--jq", ".commits[].messageBody", default=None,
    )
    blob = ""
    if isinstance(commits, str):
        blob = commits
    elif isinstance(commits, list):
        blob = "\n".join(str(c) for c in commits)
    for m in MEMBER_RE.finditer(blob or ""):
        cand = m.group(1).strip()
        if cand and not _is_model_not_member(cand):
            return cand, "commit-trailer"
    # The PR BODY carries trailers too — `Web4-Member:` lands there as often as in a
    # commit (kimi, reviewing: #70 carried it exactly there). Searching only commits
    # missed the field this whole mechanism was proposed around.
    for m in MEMBER_RE.finditer(body or ""):
        cand = m.group(1).strip()
        if cand and not _is_model_not_member(cand):
            return cand, "body-trailer"
    sig = SIGNOFF_RE.findall(body or "")
    if sig:
        return sig[-1].strip(), "body-signature"
    return None, "undetermined"


def open_prs() -> list[dict[str, Any]]:
    """Every open PR in the org, in ONE call.

    DISCOVERED, never hardcoded — a fixed list is a claim about the world that stops being
    true silently, which is how three empty repos became the entire review surface while
    seventeen PRs went unseen.

    `gh search prs --owner` rather than enumerating repos and querying each: the per-repo
    walk made ~145 API calls over 72 repos and took minutes, which is long enough that a
    launcher times out and the whole role looks broken. This is one call, ~1.5s, same
    result. A discovery step slower than the work it schedules does not get run.
    """
    rows = gh(
        "search", "prs", "--owner", ORG, "--state", "open", "--limit", "200",
        "--json", "number,title,repository,createdAt,isDraft,url",
        default=[],
    )
    out = []
    for r in rows or []:
        if r.get("isDraft"):
            continue
        repo = (r.get("repository") or {}).get("name")
        if not repo:
            continue
        out.append({
            "repo": repo,
            "number": r.get("number"),
            "title": r.get("title"),
            "created_at": r.get("createdAt"),
            "url": r.get("url"),
        })
    return out


def main() -> int:
    reviewable: list[dict[str, Any]] = []
    for pr in open_prs():
        repo, number = pr["repo"], pr["number"]
        # The body is only needed for the signature fallback, so it is fetched per PR
        # rather than in the search — one extra call only for PRs that reach it.
        body = gh("pr", "view", str(number), "--repo", f"{ORG}/{repo}",
                  "--json", "body", "--jq", ".body", default="") or ""
        member, basis = author_member(repo, number, body if isinstance(body, str) else "")
        row = {
            "repo": repo,
            "number": number,
            "title": pr.get("title"),
            "url": pr.get("url"),
            "created_at": pr.get("created_at"),
            "author_member": member or "unknown",
            "author_basis": basis,
        }
        # RANK, never drop. tier 0 = different member, 1 = unknown, 2 = own work.
        if SELF_MEMBER and member and member == SELF_MEMBER:
            row["independence"] = "same-member-fresh-context"
            row["tier"] = 2
        elif member:
            row["independence"] = "different-member"
            row["tier"] = 0
        else:
            row["independence"] = "author-undetermined"
            row["tier"] = 1
        reviewable.append(row)

    # Preferred work first; own work last but PRESENT. Stable within tier by age,
    # so the oldest unreviewed PR surfaces first rather than the loudest.
    reviewable.sort(key=lambda r: (r["tier"], r.get("created_at") or ""))

    report = {
        "org": ORG,
        "reviewer": SELF_MEMBER or "(unset)",
        "repos_scanned": "discovered",
        "reviewable": reviewable,
        "counts": {
            "reviewable": len(reviewable),
            "different_member": sum(1 for r in reviewable if r["tier"] == 0),
            "author_undetermined": sum(1 for r in reviewable if r["tier"] == 1),
            "own_work_last_resort": sum(1 for r in reviewable if r["tier"] == 2),
        },
        "caveat": (
            "author_member is recovered from commit trailers or a body signature. Every PR in "
            "this org is authored by one shared GitHub account, so this is the best available "
            "attribution and NOT an authenticated one (HST-005). Nothing is skipped: the queue "
            "is ranked so a different member's work is reviewed first, and own work is "
            "admissible last with its tier recorded."
        ),
    }
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
