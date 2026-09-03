#!/usr/bin/env python3
"""`primer_ttl_census.py` decides whether a retained work list is unrecoverable.

Its verdict costs agent wakes in one direction and, in the other, retires the only copy
of a consume-once list. So the arms that matter are the ones where the rule inverts
quietly: a broken read reading as "no notices owed", and `all` drifting to `any` so that
one aged notice condemns a list that still holds live mail. Both are pinned here with a
sabotage arm, because a green suite over a rule nobody can flip proves nothing.

Run bare: python3 plugins/member-mesh/tests/primer_ttl_census_test.py
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC = ROOT / "tools" / "primer_ttl_census.py"

FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        FAILURES.append(label)


def load(path: pathlib.Path, name: str, patch=None):
    text = path.read_text()
    if patch:
        before = text
        text = patch(text)
        assert text != before, "sabotage patch matched nothing — the arm is inert"
    tmp = pathlib.Path(tempfile.mkdtemp()) / f"{name}.py"
    tmp.write_text(text)
    spec = importlib.util.spec_from_file_location(name, tmp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_primer(d: pathlib.Path, name: str, ages_days: list[float],
                 attempts: int | None = None, raw: str | None = None) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    p = d / name
    if raw is not None:
        p.write_text(raw)
    else:
        p.write_text(json.dumps({"notices": [
            {"id": 1000 + i, "kind": "reply",
             "queued_at": (now - datetime.timedelta(days=a)).isoformat().replace(
                 "+00:00", "Z")}
            for i, a in enumerate(ages_days)]}))
    if attempts is not None:
        (d / (name + ".attempts")).write_text(str(attempts))


def fixture(root: pathlib.Path) -> pathlib.Path:
    seat = root / "primers" / "claude-code"
    seat.mkdir(parents=True)
    write_primer(seat, "notice-allold.json", [9.0, 12.0, 8.1], attempts=1)
    write_primer(seat, "notice-onelive.json", [9.0, 0.5])
    write_primer(seat, "notice-fresh.json", [0.2])
    write_primer(seat, "notice-broken.json", [], raw="{not json at all")
    write_primer(seat, "notice-empty.json", [], raw='{"notices": []}')
    write_primer(seat, "notice-badtime.json", [], raw=json.dumps(
        {"notices": [{"id": 1, "queued_at": "not-a-timestamp"}]}))
    write_primer(seat, "notice-spent.json", [30.0], attempts=9)
    return seat


def verdicts(mod, seat: pathlib.Path) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    c = mod.census(seat, mod.INBOX_TTL_SECS, now)
    return {r["primer"]: r for r in c["rows"]} | {"_": c}


def main() -> int:
    if not SRC.is_file():
        print(f"FAIL: {SRC} is missing — the tool moved and this test is now inert")
        return 1
    mod = load(SRC, "ttl_census")

    with tempfile.TemporaryDirectory() as td:
        seat = fixture(pathlib.Path(td))
        v = verdicts(mod, seat)
        c = v["_"]

        print("the rule")
        check(v["notice-allold.json"]["all_past_ttl"] is True,
              "every notice past the TTL -> unrecoverable")
        check(v["notice-onelive.json"]["all_past_ttl"] is False,
              "one live notice among aged ones -> still a live list")
        check(v["notice-fresh.json"]["all_past_ttl"] is False,
              "a fresh list is not expired")

        print("abstention (a broken read must never retire a work list)")
        check(v["notice-broken.json"]["all_past_ttl"] is False,
              "unparseable primer -> abstain, not expired")
        check(v["notice-empty.json"]["all_past_ttl"] is False,
              "zero notices -> abstain, not expired")
        check(v["notice-badtime.json"]["all_past_ttl"] is False,
              "unparseable queued_at -> abstain, not expired")
        check(c["unreadable"] == 3, f"unreadable counted, not hidden (got {c['unreadable']})")

        print("the budget")
        check(v["notice-allold.json"]["budget"] == 2, "3 attempts less 1 recorded = 2")
        check(v["notice-fresh.json"]["budget"] == 3, "no attempts file = full budget")
        check(v["notice-spent.json"]["budget"] == 0,
              "attempts over the cap clamps at 0, never negative")
        check(c["all_past_ttl"] == 2 and c["live_primers"] == 7,
              f"seat totals (got {c['all_past_ttl']}/{c['live_primers']}, want 2/7)")
        check(c["futile_budget_wakes"] == 2,
              f"futile budget counts only expired rows (got {c['futile_budget_wakes']})")

        print("sabotage: all -> any must flip the one-live-notice verdict")
        sab = load(SRC, "ttl_census_sab",
                   lambda t: t.replace("all(a > ttl for a in ages)",
                                       "any(a > ttl for a in ages)"))
        sv = verdicts(sab, seat)
        check(sv["notice-onelive.json"]["all_past_ttl"] is True,
              "sabotaged build condemns a list holding live mail (arm is live)")
        check(sv["notice-onelive.json"]["all_past_ttl"]
              != v["notice-onelive.json"]["all_past_ttl"],
              "and the shipped build does not")

        print("sabotage: a broken read must not become 'expired'")
        sab2 = load(SRC, "ttl_census_sab2",
                    lambda t: t.replace("        return None\n    if not notices:",
                                        "        return []\n    if not notices:"))
        s2 = verdicts(sab2, seat)
        check(s2["notice-broken.json"]["all_past_ttl"] is False,
              "even sabotaged, an empty age list is not expired (bool(ages) guard holds)")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
