#!/usr/bin/env python3
"""Arms for `invariant_comment_census.py`.

Each arm pins one of the three defects the tool had while it was being written, because each
was found by USING it and each is the same species as the defect the tool exists to find.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "invariant_comment_census.py"


def run(root: Path) -> dict:
    import json
    r = subprocess.run([sys.executable, str(TOOL), "--root", str(root), "--json"],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def main() -> int:
    failures = []

    def check(name, cond, detail=""):
        print(f"{'ok  ' if cond else 'FAIL'} {name}")
        if not cond:
            failures.append(f"{name}: {detail}")

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)

        # ARM 1 — THE SAME-LINE ILLUSION. The citation sits lines away from the verb, which is
        # how these comments are actually written. A same-line check reports it unanchored.
        write(root, "a.rs", '''
/// This surface MUST refuse an unnamed decider.
///
/// Measured over the chain, and the arm that holds it is
/// `an_anonymous_decider_is_refused` below.
fn thing() {}

#[test]
fn an_anonymous_decider_is_refused() {}
''')
        # ARM 2 — A CLAIM ON A TEST IS ITS OWN FALSIFIER. It cites nothing because it IS the
        # thing that fails. Counting it unanchored accuses the discipline of lacking itself.
        write(root, "b.rs", '''
/// A decline MUST never read as concurrence.
#[test]
fn a_decline_is_not_concurrence() {}
''')
        # ARM 3 — A CITATION MUST NAME A TEST THAT EXISTS. This is what makes a citation
        # checkable rather than decorative: a comment cannot anchor itself to a falsifier that
        # was renamed away or never written.
        write(root, "c.rs", '''
/// The ledger MUST never be written by a member.
///
/// Pinned by `a_test_that_does_not_exist_anywhere_in_this_repo`.
fn other() {}
''')
        # CONTROL — no invariant verb, so not in the population at all. Without this the tool
        # could "pass" by counting every comment.
        write(root, "d.rs", '''
/// This is ordinary prose about a function and claims nothing in particular.
fn quiet() {}
''')

        out = run(root)
        rows = {r["file"]: r for r in out["rows"]}

        check("a claim is found in each file that makes one",
              set(rows) == {"a.rs", "b.rs", "c.rs"},
              f"got {sorted(rows)}")
        check("the control file with no invariant verb is not counted",
              "d.rs" not in rows)

        check("a citation LINES AWAY from the verb still anchors (the block walk)",
              rows.get("a.rs", {}).get("anchored") is True,
              str(rows.get("a.rs")))
        check("...and the same-line check would have missed it",
              rows.get("a.rs", {}).get("anchored_same_line") is False,
              "if this flips, arm 1 has stopped testing the block walk")

        check("a claim written ON a test is anchored by that test",
              rows.get("b.rs", {}).get("anchor") == "is_a_test",
              str(rows.get("b.rs")))

        check("a citation to a test that does not exist does NOT anchor",
              rows.get("c.rs", {}).get("anchored") is False,
              "a citation nothing can fail is decoration: " + str(rows.get("c.rs")))

    print()
    if failures:
        print(f"FAILED {len(failures)}")
        for f in failures:
            print("  " + f)
        return 1
    print("GREEN  all arms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
