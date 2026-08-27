#!/usr/bin/env python3
"""Pins for the census's ZERO — the number it is least entitled to print.

`outcome_target_cap_census.py` exists because three seats each published a per-seat zero
that was a claim about their own regex rather than about the chain. Its first version then
minted the same artefact by a different mechanism: `find_spikes()` drops any length-mode
carrying fewer than `MIN_SPIKE_ROWS` rows, and the report turned that silence into
`rows_at_a_cap: 0`, `cut_rate: 0.0`, `caps: none`.

So a seat with 16 rows, ALL SIXTEEN at a genuine 240-char cap, reported no cap. Verbatim
line the driver printed: `n=    16 cut=     0 (0.0%)  caps: none`. Nothing in that cell
distinguishes it from a seat that does not truncate. Found by codex reviewing PR #679 —
the detector built to abolish clean zeros published one, which is how deep the attractor
runs: the floor felt like prudence (a 3-row seat must not mint a "cap") and prudence on
the FINDING side is fabrication on the ZERO side.

The n=16 fixture below is therefore the load-bearing test in this file. The rest pin the
two properties that make it safe to fix: the floor must still refuse a 3-row cap, and the
real 240 spike must still be found at scale.

Run bare (`python3 tools/outcome_target_cap_census_test.py`) — CI discovers it through
tools/ci_discovery.py and executes it with no runner.
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outcome_target_cap_census import (  # noqa: E402
    MIN_SPIKE_ROWS, ceiling_of, find_spikes, marker_of, seat_report, summary_line,
)


def _cell(lengths: dict, markers: dict | None = None, factor: float = 20.0) -> dict:
    """A (surface, seat) cell from a length histogram. `n` is derived, never passed in,
    so no fixture can accidentally disagree with its own denominator."""
    lc = Counter(lengths)
    return seat_report(lc, markers or {}, sum(lc.values()), factor)


# ---- THE REGRESSION: a thin denominator must not produce a measured zero ----

def test_sixteen_rows_all_at_a_cap_is_not_a_measured_zero():
    """The exact shape codex dissented on. 16/16 at 240 -- a real cap, below the floor."""
    c = _cell({240: 16}, {240: Counter({"dots3": 16})})
    assert c["state"] == "insufficient_sample", c["state"]
    # `0` would be a claim about the surface. `None` is the truth about the instrument.
    assert c["rows_at_a_cap"] is None, c["rows_at_a_cap"]
    assert c["cut_rate"] is None, c["cut_rate"]


def test_that_cell_still_surfaces_the_cap_as_a_suspicion():
    """Refusing to print a zero is only half the fix: the 240 is still THERE, and a report
    that merely says `n/a` has hidden it in a politer way. The ceiling survives the floor
    because a cap is the one length nothing can exceed."""
    c = _cell({240: 16}, {240: Counter({"dots3": 16})})
    ceil = c["ceiling"]
    assert ceil["length"] == 240
    assert ceil["rows"] == 16
    assert ceil["share"] == 1.0
    assert ceil["flags_cap"] is True
    assert ceil["markers"] == {"dots3": 16}
    # ...and it must reach the human-readable line, which is what a notice quotes.
    line = summary_line("outcome.target", "codex", c)
    assert "insufficient_sample" in line, line
    assert "SUSPECT ceiling 240" in line, line
    assert "(0.0%)" not in line, line


def test_the_summary_line_never_prints_a_zero_rate_it_did_not_measure():
    """The pre-fix line, verbatim: `n=    16 cut=     0 (0.0%)  caps: none`. Any substring
    of that shape reappearing in an unmeasured cell is the regression returning."""
    line = summary_line("outcome.target", "codex", _cell({240: 16}))
    assert "cut=     0" not in line, line
    assert "n/a" in line, line


# ---- the floor must still do the job it was added for ----

def test_three_rows_cannot_mint_a_cap():
    """Why the floor exists. A 3-row seat concentrated at one length is not evidence, and
    the fix must not have bought sensitivity by deleting the guard."""
    c = _cell({240: 3})
    assert c["candidate_caps"] == []
    assert c["state"] == "insufficient_sample"
    assert c["cut_rate"] is None


def test_no_rows_is_its_own_state_not_an_empty_row():
    """A seat present in the chain but silent on this surface. Absent from a per-seat
    table, it reads as a seat that is fine."""
    c = _cell({})
    assert c["state"] == "no_rows"
    assert c["rows"] == 0
    assert c["cut_rate"] is None
    assert c["ceiling"] is None
    assert "no_rows" in summary_line("outcome.target", "kimi-code", c)


# ---- and the finding the driver was written for must still land ----

def test_a_real_cap_at_scale_is_measured_and_counted():
    """Smooth background 200..259 plus 500 rows piled on 240. This is the live shape."""
    lengths = {L: 2 for L in range(200, 240)}
    lengths[240] = 500
    c = _cell(lengths, {240: Counter({"dots3": 491, "UNKNOWN_MARKER": 9})})
    assert c["state"] == "measured"
    assert [s["length"] for s in c["candidate_caps"]] == [240]
    assert c["rows_at_a_cap"] == 500
    assert 0.85 < c["cut_rate"] < 0.87, c["cut_rate"]
    # The 9 genuine 240-char commands that were never cut are reported, not folded in.
    assert c["candidate_caps"][0]["markers"]["UNKNOWN_MARKER"] == 9


def test_a_smooth_surface_at_scale_reports_a_measured_zero_and_may():
    """The one cell entitled to print 0.0%: enough rows for a spike to have shown up, and
    none did. `insufficient_sample` must not swallow this case too, or the fix has just
    moved the lie to the other side."""
    c = _cell({L: 30 for L in range(200, 260)})
    assert c["state"] == "measured"
    assert c["candidate_caps"] == []
    assert c["rows_at_a_cap"] == 0
    assert c["cut_rate"] == 0.0
    assert c["ceiling"]["flags_cap"] is False, c["ceiling"]


def test_cut_rate_is_declared_a_floor_in_every_cell():
    """A 15-row cap on a 10,000-row seat is under an ABSOLUTE floor, so it is invisible at
    any scale. The report may not imply otherwise: it must ship the bound beside the rate."""
    lengths = {L: 200 for L in range(200, 250)}
    lengths[3000] = 15  # a second, rarer cap -- genuinely below the detector
    c = _cell(lengths)
    assert c["cut_rate_is_a_floor"] is True
    assert c["detection_floor_rows"] == MIN_SPIKE_ROWS
    assert 3000 not in [s["length"] for s in c["candidate_caps"]]
    # It is not counted -- but the ceiling still names it rather than losing it entirely.
    assert c["ceiling"]["length"] == 3000


# ---- spelling-blindness, unchanged ----

def test_spikes_are_found_with_no_marker_input_at_all():
    """The whole premise: `find_spikes` never sees a string."""
    lengths = Counter({L: 3 for L in range(210, 230)})
    lengths[228] = 400
    assert [s["length"] for s in find_spikes(lengths, 20.0)] == [228]


def test_marker_labelling_is_longest_first():
    """`…[truncated]` must not be swallowed by the bare `…` test."""
    assert marker_of("x…[truncated]") == "trunc_bracket"
    assert marker_of("x …") == "ellipsis_sp"
    assert marker_of("x…") == "ellipsis"
    assert marker_of("x...") == "dots3"
    assert marker_of("x") == "UNKNOWN_MARKER"


def test_ceiling_of_an_empty_seat_is_none_not_a_crash():
    assert ceiling_of(Counter(), {}, 0) is None


TESTS = [
    test_sixteen_rows_all_at_a_cap_is_not_a_measured_zero,
    test_that_cell_still_surfaces_the_cap_as_a_suspicion,
    test_the_summary_line_never_prints_a_zero_rate_it_did_not_measure,
    test_three_rows_cannot_mint_a_cap,
    test_no_rows_is_its_own_state_not_an_empty_row,
    test_a_real_cap_at_scale_is_measured_and_counted,
    test_a_smooth_surface_at_scale_reports_a_measured_zero_and_may,
    test_cut_rate_is_declared_a_floor_in_every_cell,
    test_spikes_are_found_with_no_marker_input_at_all,
    test_marker_labelling_is_longest_first,
    test_ceiling_of_an_empty_seat_is_none_not_a_crash,
]


if __name__ == "__main__":
    # Same staleness guard as tools/escalation_payload_census_test.py: the coverage guard
    # walks `ast.Name`, so a test dispatched through a `globals()` sweep reads as inert.
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        print(f"FAIL TESTS is stale: defined-not-listed={sorted(defined - listed)} "
              f"listed-not-defined={sorted(listed - defined)}")
        sys.exit(1)
    for f in TESTS:
        f()
        print("ok", f.__name__)
    print(f"{len(TESTS)} passed")
