#!/usr/bin/env python3
r"""A `path:line` citation is a claim about a REF. This counts the refs it holds on.

WHY THIS EXISTS. `PRD_GOVERNANCE.md` cited `presets.rs:94-98` for the appeal
instruction. That was true -- in the working tree of the seat that wrote it, and
nowhere else in the shared history. A second reader at a different ref caught it.
Every check available from the writing seat had passed, because every one of them
resolved the citation against the same tree that produced it.

The first correction moved the number to `:89-93` and called the class closed on the
ground that the other two cited files were byte-identical "across my tree, main, and
this branch". That is a population of three refs, chosen because they agree. Run over
all 71 remote refs, `handler.rs` carries 27 distinct blobs and the cited construct
lands on the cited line on 17 of them -- FEWER refs than the citation that was called
broken. The bound was computed from the same seat as the defect.

So: this is the instrument that answers the question from outside one checkout.

WHAT IT MEASURES, and what each number is a bound on.

  * blob agreement (always available). For each cited file, the share of remote refs
    whose blob equals the baseline's. A ref with the same blob resolves the citation
    iff the baseline does, so this is a LOWER bound on the citation's validity share:
    edits below a cited line leave it correct, so a differing blob may still resolve.
    Reported as `>= n/N`.

  * anchor agreement (only where an --anchor is supplied). The share of refs on which
    a named grep-able construct is actually on the cited line. This is the real
    number, and supplying the anchor is the conversion this tool exists to motivate:
    once a citation names its construct, the anchor and the citation are the same
    string, and the census stops needing to be told anything.

ABSENCE IS A THIRD OUTCOME, and it is the one that argues for conversion. On 12 of 71
refs the appeal-instruction sentence is not in `presets.rs` at all -- those branch tips
predate the text (one says "appeal it through the witnessed channel", naming no tool).
Converting the citation does not make it resolve there. It makes the failure LEGIBLE:
grep returns nothing, instead of a line number resolving to plausible adjacent code.
That is the argument for grep-able pointers, and it is stronger than "line numbers
drift".

THE COUNT IS A CLAIM ABOUT A REF TOO -- and the first version of this tool did not
pin it. It read the document with `open()`, from the working tree, while measuring the
cited files across 71 refs: rigorous about the citations, single-seat about the number
of them. The consequence landed immediately. The commit that added the "a line number
is a claim about a ref" bullet recorded its producer as `... | wc -l  # 35 at this
commit's parent`; the parent holds 31, and 35 is the count at the commit itself. The
number came from a tree and the ref came from prose, and nothing in between checked
that they agreed. So the header now prints the doc's REF and BLOB, always, and
`--doc-ref` reads the document out of git instead of off the disk. A count you cannot
re-derive at a named ref is the same defect as a line number you cannot resolve there.

A QUOTED CITATION IS NOT A CITATION. A document that describes its own citation defect
must spell the broken citation to describe it -- `presets.rs:94-98` appears in the
PRD's own post-mortem bullet. A regex cannot tell a claim from a report of a claim, so
"convert every citation" would be unmeetable while the finding is written down. Append
`<!--cite:quoted-->` directly after such a citation and it is counted separately. The
marker ABUTS what it exempts, deliberately, and at the grain of one citation: an
exemption held anywhere else -- a doc line number in a flag, a list in a config -- can
drift away from its subject, which is the failure this file exists to measure. Line
granularity was tried and rejected for a narrower reason, recorded at `quoted_at`.

WHAT IT DOES NOT DO. It reads refs, not installed copies -- a seat may run a build
from none of them (see the PRD's plane on installed-vs-committed). It never fails; a
census that goes red on a fleet where every seat lives on an unmerged branch would be
red permanently and would teach nobody anything. Its output is a distribution, and the
reader decides what share is tolerable for the claim being cited.

USAGE
    tools/citation_ref_census.py docs/PRD_GOVERNANCE.md
    tools/citation_ref_census.py docs/PRD_GOVERNANCE.md --doc-ref origin/main
    tools/citation_ref_census.py docs/PRD_GOVERNANCE.md \
        --anchor 'core/src/policy/presets.rs:89=If the act is legitimate' \
        --anchor 'core/src/server/handler.rs:2379=require_string\(args, "deny_hash"\)'
"""

from __future__ import annotations

import argparse
import collections
import re
import subprocess
import sys

CITATION = re.compile(r"`([A-Za-z0-9_./-]+\.(?:rs|py|toml|json|md|sh)):(\d+)(?:-(\d+))?`")
# A citation may also be spelled as a bare continuation -- `:1347` -- which a reader
# resolves against the nearest preceding path. Counting only the qualified spelling
# undercounts the document's exposure by a third (24 vs 35 in PRD_GOVERNANCE.md), so
# both are counted, and the continuation inherits the file it continues.
CONTINUATION = re.compile(r"`:(\d+)(?:-(\d+))?`")
# A citation immediately followed by this marker is being quoted, not made. It abuts
# what it exempts on purpose -- see the docstring.
QUOTED = "<!--cite:quoted-->"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def blob_at(ref: str, path: str) -> str | None:
    """Blob hash of `path` at `ref`, or None when the ref does not carry it.

    `git rev-parse` ECHOES ITS ARGUMENT on failure, so the exit code -- not the
    stdout -- is the signal. Reading stdout alone counts one distinct "blob" per ref
    for a path that exists nowhere, which reads as total divergence and is in fact
    a typo in the path.
    """
    r = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", f"{ref}:{path}"],
        capture_output=True,
        text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else None


def remote_refs(pattern: str) -> list[str]:
    return git("for-each-ref", "--format=%(refname:short)", pattern).split()


def resolve(path: str, tracked: set[str]) -> tuple[str | None, str]:
    """Cited paths are often written short (`handler.rs`, `presets.rs`).

    Returns (path, reason). A short spelling that matches TWO tracked files is
    reported as ambiguous rather than silently bound to one of them: `types.rs` is
    both `core/src/policy/types.rs` and `plugin-sdk/rust/src/types.rs`, and picking
    either would answer a question the document did not ask.
    """
    if path in tracked:
        return path, "exact"
    tail = sorted(p for p in tracked if p.endswith("/" + path))
    if len(tail) == 1:
        return tail[0], "suffix"
    return None, ("ambiguous: " + ", ".join(tail)) if tail else "no such path"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc")
    ap.add_argument("--baseline", default="origin/main")
    ap.add_argument("--refs", default="refs/remotes/origin")
    ap.add_argument(
        "--doc-ref",
        default=None,
        metavar="REF",
        help="read the document at REF instead of from the working tree, so the "
        "count is re-derivable by a second reader",
    )
    ap.add_argument(
        "--anchor",
        action="append",
        default=[],
        metavar="PATH:LINE=REGEX",
        help="assert REGEX is on LINE of PATH; measured exactly, not bounded",
    )
    args = ap.parse_args()

    refs = remote_refs(args.refs)
    tracked = set(git("ls-tree", "-r", "--name-only", args.baseline).split("\n"))

    # Pin the document the same way the tool demands citations be pinned. `--doc-ref`
    # reads it out of git; without one the read is the author's working tree and the
    # header says so, loudly, next to the blob a second reader would need to reproduce
    # the count.
    if args.doc_ref:
        blob = blob_at(args.doc_ref, args.doc)
        if blob is None:
            print(
                f"{args.doc}: ABSENT at {args.doc_ref}. A count of zero here would "
                "mean 'no such file', not 'no citations' -- the two read alike and "
                "only one is a result.",
                file=sys.stderr,
            )
            return 2
        text = git("cat-file", "blob", blob)
        doc_pin = f"{args.doc_ref} blob {blob[:7]}"
    else:
        with open(args.doc, encoding="utf-8") as fh:
            text = fh.read()
        blob = git("hash-object", "--", args.doc).strip()
        dirty = bool(git("status", "--porcelain", "--", args.doc).strip())
        doc_pin = (
            f"WORKING TREE blob {blob[:7]}"
            f"{' (uncommitted)' if dirty else ''} -- pass --doc-ref to pin it"
        )

    def quoted_at(end: int) -> bool:
        """The marker must abut the citation it exempts -- no gap, same line.

        Line granularity was tried first and is wrong here: the PRD's post-mortem
        bullet is one paragraph on one line and carries BOTH the citation it is
        reporting as broken and a live pointer to the corrected lines. A per-line
        exemption would have hidden the live one, which is how a caveat becomes a
        blanket. Per-citation is the grain the claim is made at.
        """
        return text.startswith(QUOTED, end)

    cited: dict[str, list[str]] = collections.defaultdict(list)
    unresolved: dict[str, tuple[int, str]] = {}
    continuations = 0
    quoted = 0
    quoted_spellings: list[str] = []
    last_path: str | None = None
    # One pass over both spellings, in document order, so a continuation inherits the
    # path that precedes it the way a reader would read it.
    events = sorted(
        [(m.start(), "q", m) for m in CITATION.finditer(text)]
        + [(m.start(), "c", m) for m in CONTINUATION.finditer(text)]
    )
    for _, kind, m in events:
        if quoted_at(m.end()):
            # Still resolve the path so a later live continuation keeps its anchor;
            # just do not count a report of a citation as one.
            quoted += 1
            quoted_spellings.append(m.group(0))
            if kind == "q":
                path, _ = resolve(m.group(1), tracked)
                if path is not None:
                    last_path = path
            continue
        if kind == "q":
            raw, start, end = m.group(1), m.group(2), m.group(3)
            path, why = resolve(raw, tracked)
            if path is None:
                n, _ = unresolved.get(raw, (0, why))
                unresolved[raw] = (n + 1, why)
                last_path = None
                continue
            last_path = path
        else:
            start, end = m.group(1), m.group(2)
            continuations += 1
            if last_path is None:
                continue
            path = last_path
        cited[path].append(f"{start}-{end}" if end else start)

    total = sum(len(v) for v in cited.values())
    qualified = total - continuations + sum(n for n, _ in unresolved.values())
    print(f"{args.doc} @ {doc_pin}")
    print(f"  {qualified + continuations} live citations "
          f"({qualified} path-qualified + {continuations} bare `:NNN` continuations); "
          f"{total} resolved over {len(cited)} files, "
          f"against {len(refs)} refs under {args.refs}")
    # Name them, do not merely count them. The marker exempts whatever it abuts, so a
    # prose mention of the marker landing right after a real citation would exempt it
    # silently. Printing the spellings is the control that makes that visible.
    print(f"  {quoted} quoted, not counted (each marked {QUOTED}) -- a document "
          "reporting a broken citation must spell it"
          + (": " + ", ".join(quoted_spellings) if quoted_spellings else ""))
    print(f"  qualified regex : {CITATION.pattern}")
    print(f"  continuation    : {CONTINUATION.pattern}\n")

    for path in sorted(cited):
        base = blob_at(args.baseline, path)
        blobs = [b for b in (blob_at(r, path) for r in refs) if b is not None]
        same = sum(1 for b in blobs if b == base)
        print(f"  {path}")
        print(f"    lines cited : {', '.join(sorted(set(cited[path])))}")
        print(f"    blobs       : {len(set(blobs))} distinct over {len(blobs)} refs "
              f"carrying the file")
        print(f"    resolves on : >= {same}/{len(refs)} refs "
              f"(lower bound -- blob agreement with {args.baseline})")

    if unresolved:
        print("\n  citations whose path does not resolve at the baseline:")
        for raw, (n, why) in sorted(unresolved.items()):
            print(f"    {raw}  x{n}  -- {why}")

    for spec in args.anchor:
        head, _, regex = spec.partition("=")
        path, _, line_s = head.rpartition(":")
        line = int(line_s)
        rx = re.compile(regex)
        on, elsewhere, absent = 0, 0, 0
        for ref in refs:
            blob = blob_at(ref, path)
            if blob is None:
                absent += 1
                continue
            lines = git("cat-file", "blob", blob).split("\n")
            hits = [i + 1 for i, t in enumerate(lines) if rx.search(t)]
            if not hits:
                absent += 1
            elif line in hits:
                on += 1
            else:
                elsewhere += 1
        print(f"\n  anchor {path}:{line} /{regex}/")
        print(f"    on the cited line : {on}/{len(refs)}")
        print(f"    on another line   : {elsewhere}/{len(refs)}")
        print(f"    construct ABSENT  : {absent}/{len(refs)}  "
              "(conversion makes this legible, not correct)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
