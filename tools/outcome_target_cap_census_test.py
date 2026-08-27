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
    MIN_SPIKE_ROWS, ceiling_of, concentrations, demote_constants, find_spikes, marker_of,
    seat_report, summary_line,
)


def _cell(lengths: dict, markers: dict | None = None, factor: float = 20.0,
          distinct: dict | None = None) -> dict:
    """A (surface, seat) cell from a length histogram. `n` is derived, never passed in,
    so no fixture can accidentally disagree with its own denominator."""
    lc = Counter(lengths)
    return seat_report(lc, markers or {}, sum(lc.values()), factor, distinct)


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


# ---- the false-positive class a spelling-blind test was always going to have ----

def test_a_probe_repeating_one_string_is_demoted_not_reported_as_a_cap():
    """`gate-handshake-probe`: 50 acts, all the literal string `/tmp/gate-handshake-probe-
    target`, in an empty neighbourhood. Ratio infinity, rows over the floor, and the
    pre-fix driver called it a 100%-cut cap. Found by kimi-code on the first full-chain
    run of this file. One distinct value cannot evidence a cap: a cap piles hundreds of
    DIFFERENT acts onto one length."""
    one = "/tmp/gate-handshake-probe-target"
    c = _cell({len(one): 50}, {len(one): Counter({"UNKNOWN_MARKER": 50})},
              distinct={len(one): {one}})
    assert c["candidate_caps"] == [], c["candidate_caps"]
    assert c["rows_at_a_cap"] == 0, c["rows_at_a_cap"]
    # BOTH detectors proposed it (spike ratio infinity, share 100%) and both refuse it --
    # the share test needs the discriminator more, since below the row floor it is alone.
    dem = c["demoted_as_repeated_constants"]
    assert sorted(d["proposed_by"] for d in dem) == ["concentration", "spike"], dem
    assert c["concentrations"] == [], c["concentrations"]
    d = [x for x in dem if x["proposed_by"] == "spike"][0]
    assert d["distinct"] == 1 and d["distinct_ratio"] == 0.02, d
    assert "repeated constant" in d["demoted_because"]
    # Demoted, never dropped: it must still be visible on the line a notice quotes.
    line = summary_line("outcome.target", "gate-handshake-probe", c)
    assert "DEMOTED" in line and "SUSPECT" not in line, line


def test_the_real_cap_is_not_demoted_because_its_values_are_distinct():
    """The measured contrast, same test, same threshold: 5,710 distinct values over 6,127
    rows at 240 on the live surface vs 1/50 for the probe. Two orders of magnitude."""
    lengths = {L: 2 for L in range(200, 240)}
    lengths[240] = 6127
    c = _cell(lengths, {240: Counter({"dots3": 6118, "UNKNOWN_MARKER": 9})},
              distinct={240: {"x" * 239 + str(i) for i in range(5710)}})
    assert [s["length"] for s in c["candidate_caps"]] == [240]
    assert c["candidate_caps"][0]["distinct"] == 5710
    assert c["candidate_caps"][0]["distinct_ratio"] == 0.932
    assert c["demoted_as_repeated_constants"] == []


def test_a_cut_constant_is_kept_because_the_marker_refuses_the_demotion():
    """The demotion's own failure mode, pinned so it stays narrow. One long command,
    repeated 50 times, cut every time -- 1 distinct value, but the value ENDS IN A CUT
    MARKER. The marker read may only refuse a cap, never mint one, so this stays a cap and
    the file's spelling-blindness is untouched in the direction that finds things."""
    v = "x" * 237 + "..."
    c = _cell({240: 50}, {240: Counter({"dots3": 50})}, distinct={240: {v}})
    assert [s["length"] for s in c["candidate_caps"]] == [240], c["candidate_caps"]
    assert c["demoted_as_repeated_constants"] == []


def test_demotion_needs_values_and_says_nothing_without_them():
    """Driven from a bare histogram -- the histogram-only tests above, and any caller that
    did not collect values -- the column is `None` and NOTHING is demoted. An absent
    measurement must not read as a passed test."""
    spikes = [{"length": 32, "rows": 50, "distinct": None, "distinct_ratio": None}]
    caps, demoted = demote_constants(spikes, {32: Counter({"UNKNOWN_MARKER": 50})})
    assert demoted == [] and len(caps) == 1


# ---- a measured zero must carry its own sensitivity ----

def test_a_measured_zero_prints_the_rate_it_could_not_have_seen():
    """kimi-code's escalation cell: n=45, driver printed `cut=0 (0.0%) caps: none`, true
    full-window rate 24.8%. The floor is ABSOLUTE in rows, so at n=45 nothing under
    20/45 = 44% is expressible -- the zero was forced by arithmetic, and 24.8% sits under
    it. The cell owes the reader that bound next to the result."""
    c = _cell({L: 1 for L in range(400, 445)})
    assert c["state"] == "measured" and c["cut_rate"] == 0.0
    assert c["min_detectable_rate"] == round(MIN_SPIKE_ROWS / 45, 4)
    line = summary_line("gate_escalation_opened.stated_reason", "kimi-code", c)
    assert "floor: no cap under 44.4%" in line, line


def test_the_live_cell_that_missed_the_floor_by_one_row():
    """Not a hypothetical. Full chain, 2026-08-27, `gate_escalation_opened.stated_reason`,
    seat `unattributed`: 29 rows, NINETEEN of them exactly 228 chars and ending in the
    `ellipsis_sp` cut marker -- the same 220 cap claude-code cuts at. The floor is 20. The
    driver printed `cut=0 (0.0%) caps: none`.

    So the seat's true cut rate is >= 65.5% and the cell said zero, one row short. The
    sensitivity bound makes that legible without anyone reading a marker: 20/29 = 69.0%
    is ABOVE the true rate, which is exactly why the zero was forced rather than found."""
    lengths = {228: 19}
    lengths.update({L: 1 for L in range(200, 210)})
    c = _cell(lengths, {228: Counter({"ellipsis_sp": 19})})
    assert c["state"] == "measured", c["state"]
    assert c["cut_rate"] == 0.0 and c["candidate_caps"] == []
    assert c["min_detectable_rate"] == round(20 / 29, 4)
    line = summary_line("gate_escalation_opened.stated_reason", "unattributed", c)
    assert "floor: no cap under 69.0%" in line, line
    # ...and the share test, which the floor does not bind, names the length anyway.
    assert "SUSPECT ceiling 228" in line, line


def test_min_detectable_rate_is_null_where_no_rate_is_expressible():
    """Below the floor there is no sensitivity to quote -- printing 20/16 = 125% would be
    a number pretending to be a bound. `insufficient_sample` already says it."""
    assert _cell({240: 16})["min_detectable_rate"] is None
    assert _cell({})["min_detectable_rate"] is None


# ---- the ceiling test is blind on a MIXED surface; the share test is not ----

def test_a_cap_under_an_uncapped_tail_is_missed_by_the_ceiling_and_caught_by_share():
    """kimi's correction on PR #679: `extract_target` caps the `command` branch at 240 and
    returns the `file_path`/`url` branch UNCAPPED, so a live surface can carry rows ABOVE
    its own cap (claude-code: max_len 318 over a 240 cap cutting ~31%).

    Put that mixture below the row floor, where the spike test is deaf and the ceiling is
    the only instrument left, and the ceiling looks at 318 -- one uncapped row, share 6% --
    and flags nothing. The cap is 16 of 18 rows. A cap piles a share onto ONE length
    whether or not something sits above it, so the share test is unbound from max_len."""
    c = _cell({240: 16, 318: 1, 300: 1}, {240: Counter({"dots3": 16})})
    assert c["state"] == "insufficient_sample" and c["candidate_caps"] == []
    assert c["ceiling"]["length"] == 318
    assert c["ceiling"]["flags_cap"] is False, "the ceiling test sees the uncapped tail"
    hits = [x for x in c["concentrations"] if x["length"] == 240]
    assert hits and hits[0]["rows"] == 16 and hits[0]["is_ceiling"] is False, c["concentrations"]
    line = summary_line("outcome.target", "claude-code", c)
    assert "SUSPECT concentration 240" in line, line


def test_share_test_still_refuses_a_smooth_surface():
    """The generalisation must not have bought sensitivity by flagging everything: 60
    lengths at 30 rows each is 1.7% per length, under the 10% share threshold."""
    assert concentrations(Counter({L: 30 for L in range(200, 260)}), {}, 1800) == []


TESTS = [
    test_a_probe_repeating_one_string_is_demoted_not_reported_as_a_cap,
    test_the_real_cap_is_not_demoted_because_its_values_are_distinct,
    test_a_cut_constant_is_kept_because_the_marker_refuses_the_demotion,
    test_demotion_needs_values_and_says_nothing_without_them,
    test_a_measured_zero_prints_the_rate_it_could_not_have_seen,
    test_the_live_cell_that_missed_the_floor_by_one_row,
    test_min_detectable_rate_is_null_where_no_rate_is_expressible,
    test_a_cap_under_an_uncapped_tail_is_missed_by_the_ceiling_and_caught_by_share,
    test_share_test_still_refuses_a_smooth_surface,
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
