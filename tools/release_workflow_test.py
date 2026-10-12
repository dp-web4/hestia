#!/usr/bin/env python3
"""Structural guards on .github/workflows/release.yml that a dry run cannot exercise.

1. ONE LOCK PER TAG (Codex, hestia#1283). The concurrency group is evaluated for a tag push and
   for a dispatch of the same tag, and the two keys must be equal (and bare: `release-v0.3.0`).
   The old expression used github.ref, which is `refs/tags/v0.3.0` on push and so gave the two
   triggers two different locks; the evaluator is checked to tell those apart, so a pass here is
   not an evaluator that returns the same string for everything.
2. NO SILENT EMPTY PUBLISH. The publish job's artifact download is fatal whenever assemble
   succeeded, nothing in that job is continue-on-error: true, the publish job never PATCHes
   draft=false itself (only tools/release_publish.py does, after its manifest checks), and
   assemble enforces the exact manifest with check-dir.
3. RC TAGS reach the workflow: the push trigger's glob matches vX.Y.Z-rc.N, and the version job
   takes the kind from version_sync.py --tag-kind and hands it to publish.

Text-level on purpose: the bare test job has no YAML library guaranteed, and every check below is
about a specific line, not the document's shape.

Run: python3 tools/release_workflow_test.py   (bare; exit 1 on failure)
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
WF = (HERE.parent / ".github" / "workflows" / "release.yml").read_text()

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        FAILS.append(name + (f"\n    {detail}" if detail else ""))


def lookup(ctx: dict, dotted: str):
    cur = ctx
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def evaluate(template: str, ctx: dict) -> str:
    """GitHub expression subset: `${{ a.b || c.d }}` with context lookups; falsy is ''/None."""
    def one(m: re.Match) -> str:
        for alt in m.group(1).split("||"):
            v = lookup(ctx, alt.strip())
            if v:
                return str(v)
        return ""
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", one, template)


def job_block(name: str) -> str:
    m = re.search(rf"^  {name}:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)", WF, re.M | re.S)
    return m.group(1) if m else ""


def github_glob(pattern: str, ref: str) -> bool:
    """GitHub filter glob: `*` matches any run of characters except `/`."""
    rx = "".join("[^/]*" if c == "*" else re.escape(c) for c in pattern)
    return re.fullmatch(rx, ref) is not None


def push(tag: str) -> dict:
    return {"github": {"event_name": "push", "ref": f"refs/tags/{tag}", "ref_name": tag,
                       "event": {}}}


def dispatch(tag: str, branch: str = "main") -> dict:
    return {"github": {"event_name": "workflow_dispatch", "ref": f"refs/heads/{branch}",
                       "ref_name": branch, "event": {"inputs": {"tag": tag}}}}


def main() -> int:
    # 1. concurrency
    m = re.search(r"^concurrency:\n\s+group:\s*(.+)$", WF, re.M)
    check("1 a top-level concurrency group exists", m is not None)
    group = m.group(1).strip() if m else ""
    check("1 concurrency never cancels a release mid-flight",
          re.search(r"^concurrency:\n.*\n\s+cancel-in-progress:\s*false", WF, re.M) is not None)
    for tag in ("v0.3.0", "v0.3.0-rc.1"):
        kp, kd = evaluate(group, push(tag)), evaluate(group, dispatch(tag))
        check(f"1 push and dispatch of {tag} share one lock", kp == kd, f"push={kp!r} dispatch={kd!r}")
        check(f"1 the lock for {tag} is the bare tag", kp == f"release-{tag}", kp)
    check("1 two different tags get two locks",
          evaluate(group, push("v0.3.0")) != evaluate(group, push("v0.3.0-rc.1")))
    old = "release-${{ github.event.inputs.tag || github.ref }}"
    check("1 the evaluator distinguishes the old (broken) key",
          evaluate(old, push("v0.3.0")) != evaluate(old, dispatch("v0.3.0")))
    check("1 a dispatched tag must be bare (no refs/tags/ prefix to dodge the lock)",
          '[[ "$INPUT_TAG" =~ ^v[0-9] ]]' in WF)

    # 2. no silent empty publish
    pub = job_block("publish")
    asm = job_block("assemble")
    check("2 publish job found", bool(pub))
    check("2 publish download is fatal when assemble succeeded",
          "continue-on-error: ${{ needs.assemble.result != 'success' }}" in pub, pub[:400])
    check("2 nothing in publish is continue-on-error: true",
          re.search(r"continue-on-error:\s*true", pub) is None)
    check("2 publish runs tools/release_publish.py publish",
          "hestia/tools/release_publish.py publish" in pub)
    check("2 the publish job never flips draft=false itself", "draft=false" not in pub)
    check("2 publish hands the script the assemble result",
          "ASSEMBLE: ${{ needs.assemble.result }}" in pub and '--assemble "$ASSEMBLE"' in pub)
    check("2 assemble enforces the exact manifest", "release_publish.py check-dir" in asm)
    check("2 nothing else in the file publishes a release",
          WF.count("draft=false") == 0 and "softprops/action-gh-release" not in WF)

    # 3. rc tags
    tags = re.search(r"^  push:\n    tags:\n((?:      - .+\n)+)", WF, re.M)
    pats = re.findall(r"- '([^']+)'", tags.group(1)) if tags else []
    for t in ("v0.3.0", "v0.3.0-rc.1", "v0.3.0-rc.12"):
        check(f"3 the push trigger fires on {t}", any(github_glob(p, t) for p in pats), pats)
    ver = job_block("version")
    check("3 version takes the kind from version_sync --tag-kind", "--tag-kind" in ver)
    check("3 version exports kind", "kind: ${{ steps.label.outputs.kind }}" in ver)
    check("3 publish passes the kind to the script",
          "KIND: ${{ needs.version.outputs.kind }}" in pub and '--kind "$KIND"' in pub)

    for f in FAILS:
        print("FAIL", f)
    print(f"release_workflow: {'FAILED' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
