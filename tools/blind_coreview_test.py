#!/usr/bin/env python3
"""Contract tests for tools/blind_coreview.py — the blind co-review instrument.

The load-bearing ones:

- `test_v2_seal_binds_the_assignment` — codex's pre-seal review, reproduced as an
  executable pin: seal `concur` for reviewer-a on record-a, then change the doc's
  reviewer to reviewer-b, eid to record-b, and sealed_at to zero. v1 verified that
  tampered doc (only verdict+basis+nonce were committed); v2 must refuse it — the seal
  binds round, reviewer, probe, record digest and claimed time, not just the text.
- `test_seal_doc_never_carries_the_reveal` — the nonce, verdict and basis are what stop
  a terse basis from being brute-forced off the published hash before the reveal
  (claude-code's pre-seal review, reproduced: a ("concur" / "sound, concur") seal falls
  to a 40-candidate dictionary when the commitment is verdict+basis alone). The check is
  on the published doc's bytes.
- `test_stats_reproduces_the_arcs_blind_set` — the REAL 10-pair blind set from the echo
  measurement, rebuilt from /tmp/kimi-echo-factors.json by the arc's own walk
  (adjacent cross-reviewer factor pairs <=120 s apart; e1bc557f dropped as one vendor
  under two names), marginals codex 96/162, kimi-code 49/186, claude-code 23/125.
  Pins the published numbers at full precision (the findings table renders 2 dp:
  0.4503 -> "45%"), with the chance-corrected numbers now in per-pair blocks.
- `test_stats_kappa_is_not_a_statistic_of_the_encoding` — codex's follow-up (notice
  14563), their exact demonstration: the same three named reviews, one pair's encoding
  swapped, pooled positional kappa 0.0 vs -1.0. The pooled number is suppressed; the
  two encodings must now produce byte-identical reports.
- `test_stats_abstention_is_recorded_not_coerced` / `test_verify_freezes_the_per_probe_
  pair_and_encoding` — the rest of the follow-up: null dissent bits are counted as
  missingness and excluded from agreement math (never coerced boolean); the frozen
  manifest carries the question, the verdict encoding, and the TWO eligible reviewers
  per probe, and verify enforces all three.
- `test_stats_documented_schema_is_the_schema_the_code_reads` — regression for
  `KeyError: 'a_name'`: the usage string originally omitted a_name/b_name, so a
  pairs.json built to the documented schema crashed. Every key the stats() loop reads
  must appear in the module docstring's schema block.
- `test_stats_refuses_invalid_inputs` — codex's review, point 3: the old stats()
  accepted rates out of range and treated dissent values through Python equality.
  Literal booleans and finite rates in [0,1] are now validated before any calculation.

Run: python3 tools/blind_coreview_test.py   (or via pytest)
"""
import importlib.util
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("blind_coreview",
                                               os.path.join(_HERE, "blind_coreview.py"))
bc = importlib.util.module_from_spec(_spec)
sys.modules["blind_coreview"] = bc
_spec.loader.exec_module(bc)

_RECORD = b"# probe packet\nattempted act, rule that fired, the record as the decider saw it\n"


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


# The echo arc's provably-blind set, pair for pair: (eid head, earlier, later, a_dissent,
# b_dissent). Marginals are each reviewer's rate over ALL factors in the window.
_BLIND10 = [
    ("e9c5c19b", "codex", "kimi-code", False, False),
    ("5029f26d", "codex", "kimi-code", False, False),
    ("f9fa6e76", "codex", "claude-code", True, False),
    ("6d8b8991", "codex", "kimi-code", True, False),
    ("438bc2d2", "claude-code", "codex", False, False),
    ("bfc033c0", "codex", "claude-code", False, False),
    ("042c34a4", "codex", "claude-code", False, False),
    ("1d806c31", "codex", "kimi-code", True, False),
    ("a0f71efc", "codex", "kimi-code", True, False),
    ("66591064", "kimi-code", "codex", False, False),
]
_MARGINALS = {"codex": 96 / 162, "kimi-code": 49 / 186, "claude-code": 23 / 125}


def _arc_envelope():
    return {"round": "echo-arc-reconstruction",
            "marginals_source": "live-work factor rates over the echo window "
                                "(codex 96/162, kimi-code 49/186, claude-code 23/125)",
            "pairs": [{"a_name": a, "b_name": b, "a_dissent": da, "b_dissent": db,
                       "marginals": _MARGINALS} for _, a, b, da, db in _BLIND10]}


def _sealed(reviewer="reviewer-a", eid="record-a", verdict="concur",
            basis="the record is sound", record=_RECORD, round_id="pilot-1"):
    return bc.seal(reviewer, eid, verdict, basis, record, round_id)


def test_seal_verify_roundtrip():
    doc, reveal = _sealed(verdict="  Concur ", basis="  the record is sound  ")
    check("roundtrip", bc.verify(doc, reveal),
          f"canonicalization (strip/case) must round-trip: {bc.check(doc, reveal)}")


def test_seal_doc_never_carries_the_reveal():
    doc, reveal = _sealed(verdict="concur", basis="sound, concur — zzqx unique string")
    blob = json.dumps(doc)
    check("nonce absent", reveal["nonce"] not in blob,
          "the published doc must not contain the nonce")
    check("basis absent", "zzqx unique string" not in blob,
          "the published doc must not contain the basis")
    check("no verdict field", "verdict" not in doc,
          "the published doc must not carry the verdict")
    check("nonce looks random",
          len(reveal["nonce"]) == 32 and
          all(c in "0123456789abcdef" for c in reveal["nonce"]))


def test_v2_seal_binds_the_assignment():
    """codex's attack: reassign reviewer, eid and sealed_at on a sealed doc. v1 verified
    it (reproduced against the v1 code before it was replaced); v2 must refuse every
    piece."""
    doc, reveal = _sealed()
    tampered = dict(doc, reviewer="reviewer-b")
    check("reviewer rebound", not bc.verify(tampered, reveal))
    tampered = dict(doc, eid="record-b")
    check("eid rebound", not bc.verify(tampered, reveal))
    tampered = dict(doc, sealed_at=0)
    check("sealed_at zeroed", not bc.verify(tampered, reveal))
    tampered = dict(doc, round="pilot-2")
    check("round rebound", not bc.verify(tampered, reveal))
    check("record digest bound",
          bc.check(doc, reveal) == [] and
          doc["record_sha256"] == bc.record_digest(_RECORD))
    # a reveal that LIES about the assignment fails the commitment, not just the
    # field comparison
    lying = dict(reveal, reviewer="reviewer-b")
    check("lying reveal", not bc.verify(doc, lying))
    check("wrong nonce", not bc.verify(doc, dict(reveal, nonce="00" * 16)))
    check("tampered basis", not bc.verify(doc, dict(reveal, basis="sound, concur.")))
    check("tampered verdict", not bc.verify(doc, dict(reveal, verdict="dissent")))
    doc2, reveal2 = _sealed()
    check("nonce binds", doc["sha256"] != doc2["sha256"],
          "identical verdict+basis must seal differently under different nonces")


def _manifest(**over):
    """A complete frozen manifest: round, seats, the question as presented, the
    verdict encoding (with abstention as a verdict of its own), and per probe the
    TWO eligible reviewers."""
    m = {"round": "pilot-1", "seats": ["reviewer-a", "reviewer-b", "reviewer-c"],
         "question": "was the proposed action justified by the evidence available "
                     "at petition opening?",
         "verdicts": ["concur", "dissent", "abstain"],
         "probes": [{"eid": "record-a",
                     "record_sha256": bc.record_digest(_RECORD),
                     "reviewers": ["reviewer-a", "reviewer-b"]}]}
    m.update(over)
    return m


def test_verify_against_the_frozen_manifest():
    doc, reveal = _sealed()
    check("manifest ok", bc.verify(doc, reveal, _manifest()),
          f"{bc.check(doc, reveal, _manifest())}")
    check("wrong round refused",
          not bc.verify(doc, reveal, _manifest(round="pilot-2")))
    check("seatless reviewer refused",
          not bc.verify(doc, reveal, _manifest(seats=["reviewer-b"])))
    wrong_packet = _manifest(probes=[{"eid": "record-a",
                                      "record_sha256": bc.record_digest(b"another packet"),
                                      "reviewers": ["reviewer-a", "reviewer-b"]}])
    check("wrong packet refused", not bc.verify(doc, reveal, wrong_packet),
          "the digest of the exact presented record is bound, not just the eid")


def test_verify_freezes_the_per_probe_pair_and_encoding():
    """codex's follow-up (notice 14563): eligibility is per-probe, not round-wide, and
    the question + verdict encoding are frozen — a manifest missing any piece is not
    the manifest this round seals against."""
    doc, reveal = _sealed()
    # reviewer-a holds a seat, but the probe's frozen pair is (reviewer-b, reviewer-c)
    not_eligible = _manifest(probes=[{"eid": "record-a",
                                      "record_sha256": bc.record_digest(_RECORD),
                                      "reviewers": ["reviewer-b", "reviewer-c"]}])
    check("seat-holder not eligible for THIS probe refused",
          not bc.verify(doc, reveal, not_eligible))
    no_pair = _manifest(probes=[{"eid": "record-a",
                                 "record_sha256": bc.record_digest(_RECORD)}])
    check("probe without a frozen pair refused", not bc.verify(doc, reveal, no_pair))
    one_seat = _manifest(probes=[{"eid": "record-a",
                                  "record_sha256": bc.record_digest(_RECORD),
                                  "reviewers": ["reviewer-a", "reviewer-d"]}])
    check("pair naming a non-seat refused", not bc.verify(doc, reveal, one_seat))
    abstained = dict(reveal, verdict="defer")
    a_doc, _ = _sealed()
    check("verdict outside the frozen encoding refused",
          not bc.verify(a_doc, abstained, _manifest()) or True)
    # ^ the tampered verdict breaks the commitment first; the encoding check needs a
    #   REAL seal of an off-encoding verdict
    off_doc, off_reveal = _sealed(verdict="defer")
    check("sealed verdict outside the frozen encoding refused",
          not bc.verify(off_doc, off_reveal, _manifest()),
          f"{bc.check(off_doc, off_reveal, _manifest())}")
    abstain_doc, abstain_reveal = _sealed(verdict="abstain")
    check("abstention is a first-class verdict when the encoding names it",
          bc.verify(abstain_doc, abstain_reveal, _manifest()))
    check("manifest without the question refused",
          not bc.verify(doc, reveal, _manifest(question="")))
    no_q = _manifest(); del no_q["question"]
    check("manifest missing the question refused", not bc.verify(doc, reveal, no_q))
    check("manifest without the verdict encoding refused",
          not bc.verify(doc, reveal, _manifest(verdicts=[])))


def test_stats_reproduces_the_arcs_blind_set():
    out = bc.stats(_arc_envelope())
    expect = {"n": 10, "complete": 10, "missing": 0, "agree": 6,
              "raw_agreement": 0.6, "independence_null": 0.4503, "excess_pts": 15.0,
              "pabak": 0.2,
              "round_marginals": {"codex": 0.4, "kimi-code": 0.0, "claude-code": 0.0},
              "external_marginals": {"codex": round(96 / 162, 4),
                                     "kimi-code": round(49 / 186, 4),
                                     "claude-code": round(23 / 125, 4)},
              "round": "echo-arc-reconstruction"}
    for k, v in expect.items():
        check(f"arc[{k}]", out.get(k) == v, f"got {out.get(k)}, want {v}")
    check("source echoed", "codex 96/162" in out.get("marginals_source", ""))
    check("no pooled positional kappa", "kappa" not in out and
          "round_internal_null" not in out,
          "suppressed as a headline: representation-dependent under rotating seats")
    check("seat_note present", "seat_note" in out,
          "the arc's blind set rotates seats — the note must say chance-corrected "
          "statistics live per fixed pair")
    cc = out["by_pair"]["claude-code+codex"]
    check("arc cc pair", (cc["n"], cc["agree"], cc["raw_agreement"],
                          cc["round_internal_null"], cc["kappa"], cc["pabak"])
          == (4, 3, 0.75, 0.75, 0.0, 0.5), f"{cc}")
    check("arc cc cells", cc["cells"] == {"both_dissent": 0, "a_only": 0,
                                          "b_only": 1, "neither": 3})
    check("arc cc orientation", cc["orientation"] == ["claude-code", "codex"])
    ck = out["by_pair"]["codex+kimi-code"]
    check("arc ck pair", (ck["n"], ck["agree"], ck["raw_agreement"],
                          ck["round_internal_null"], ck["kappa"], ck["pabak"])
          == (6, 3, 0.5, 0.5, 0.0, 0.0), f"{ck}")
    check("arc ck cells", ck["cells"] == {"both_dissent": 0, "a_only": 3,
                                          "b_only": 0, "neither": 3})


def test_stats_kappa_is_not_a_statistic_of_the_encoding():
    """codex's follow-up (notice 14563), their exact demonstration: the same three
    named reviews, one pair's encoding swapped. The pooled positional kappa moved
    (0.0 vs -1.0) with no reviewer changing an answer — so the pooled number is
    gone from the output, and the two encodings now produce IDENTICAL reports."""
    rates = {"x": 0.5, "y": 0.5, "z": 0.5}

    def pair(a, b, da, db):
        return dict(a_name=a, b_name=b, a_dissent=da, b_dissent=db, marginals=rates)

    one = bc.stats({"pairs": [pair("x", "y", True, False),
                              pair("x", "z", True, False)]})
    two = bc.stats({"pairs": [pair("x", "y", True, False),
                              pair("z", "x", False, True)]})
    check("encoding-invariant", one == two,
          f"encoding 1: {one}\nencoding 2: {two}")
    check("no headline kappa", "kappa" not in one and "round_internal_null" not in one)
    check("per-pair blocks identical", one["by_pair"] == two["by_pair"])
    check("x+y block", one["by_pair"]["x+y"]["kappa"] == 0.0 and
          one["by_pair"]["x+y"]["n"] == 1)
    check("x+z block", one["by_pair"]["x+z"]["kappa"] == 0.0 and
          one["by_pair"]["x+z"]["cells"]["a_only"] == 1,
          "consistent orientation: the swapped pair normalizes to (x, z)")


def test_stats_abstention_is_recorded_not_coerced():
    """A null dissent bit is an abstention / insufficient-evidence / missing-reveal
    mark: counted in missingness, excluded from agreement and kappa, never coerced
    to a boolean (codex's follow-up: how abstentions are recorded)."""
    rates = {"x": 0.5, "y": 0.5, "z": 0.5}
    env = {"pairs": [
        dict(a_name="x", b_name="y", a_dissent=True, b_dissent=False, marginals=rates),
        dict(a_name="x", b_name="y", a_dissent=False, b_dissent=False, marginals=rates),
        dict(a_name="x", b_name="y", a_dissent=None, b_dissent=True, marginals=rates),
        dict(a_name="x", b_name="z", a_dissent=None, b_dissent=None, marginals=rates)]}
    out = bc.stats(env)
    check("counts", (out["n"], out["complete"], out["missing"]) == (4, 2, 2))
    check("raw over complete only", out["raw_agreement"] == 0.5, f"{out}")
    xy = out["by_pair"]["x+y"]
    check("xy missingness", (xy["n"], xy["complete"], xy["missing"]) == (3, 2, 1))
    check("xy stats over complete", xy["raw_agreement"] == 0.5 and xy["kappa"] == 0.0)
    xz = out["by_pair"]["x+z"]
    check("all-missing pair keeps the hole visible",
          (xz["n"], xz["complete"], xz["missing"]) == (1, 0, 1) and
          xz["raw_agreement"] is None and xz["kappa"] is None and
          xz["cells"] is None)


def test_stats_undefined_kappa_stays_undefined():
    """pe == 1 (both reviewers at 0% or 100% dissent within the pair) leaves kappa
    undefined; it is reported as null, never coerced to 0 or dropped."""
    rates = {"x": 0.5, "y": 0.5}
    env = {"pairs": [dict(a_name="x", b_name="y", a_dissent=False, b_dissent=False,
                          marginals=rates),
                     dict(a_name="x", b_name="y", a_dissent=False, b_dissent=False,
                          marginals=rates)]}
    block = bc.stats(env)["by_pair"]["x+y"]
    check("pe is 1", block["round_internal_null"] == 1.0)
    check("kappa undefined, present", "kappa" in block and block["kappa"] is None)
    check("pabak still defined", block["pabak"] == 1.0)


def test_stats_homogeneous_seats_have_no_seat_note():
    env = {"pairs": [{"a_name": "kimi-code", "b_name": "codex",
                      "a_dissent": True, "b_dissent": False,
                      "marginals": {"kimi-code": 0.3, "codex": 0.5}}]}
    out = bc.stats(env)
    check("no seat_note", "seat_note" not in out,
          "one fixed pair: by_pair IS the pair, nothing rotates")
    check("per-name marginals", out["round_marginals"] == {"kimi-code": 1.0,
                                                           "codex": 0.0})
    block = out["by_pair"]["codex+kimi-code"]
    check("single pair block", (block["n"], block["agree"], block["raw_agreement"],
                                block["round_internal_null"], block["kappa"],
                                block["pabak"]) == (1, 0, 0.0, 0.0, 0.0, -1.0),
          f"{block}")
    check("orientation normalized", block["orientation"] == ["codex", "kimi-code"])
    check("cells in the block's orientation",
          block["cells"] == {"both_dissent": 0, "a_only": 0, "b_only": 1,
                             "neither": 0})


def test_stats_documented_schema_is_the_schema_the_code_reads():
    lines = bc.__doc__.splitlines()
    i = next((n for n, l in enumerate(lines) if "pairs.json:" in l), None)
    check("schema documented", i is not None, "usage string lost the pairs.json schema")
    schema_block = "\n".join(lines[i:i + 7]) if i is not None else ""
    for key in ("pairs", "a_name", "b_name", "a_dissent", "b_dissent", "marginals",
                "marginals_source"):
        check(f"doc has {key}", key in schema_block)
    check("null encoding documented", "null" in schema_block,
          "the abstention mark is part of the schema — document it or the next "
          "pairs.json builder coerces it")
    check("per-pair reporting documented", "by_pair" in bc.__doc__)
    out = bc.stats({"pairs": _arc_envelope()["pairs"][:1]})
    check("no KeyError", out["n"] == 1)


def test_stats_refuses_invalid_inputs():
    def bad(pair):
        try:
            bc.stats({"pairs": [pair]})
        except ValueError:
            return True
        return False

    base = {"a_name": "x", "b_name": "y", "a_dissent": True, "b_dissent": False,
            "marginals": {"x": 0.3, "y": 0.5}}
    check("truthy int is not a bool", bad(dict(base, a_dissent=1)))
    check("string is not a bool", bad(dict(base, a_dissent="true")))
    check("a pair is two distinct reviewers", bad(dict(base, b_name="x",
                                                       marginals={"x": 0.3})))
    check("null is a recorded abstention, not a refusal",
          bc.stats({"pairs": [dict(base, a_dissent=None)]})["missing"] == 1)
    check("rate above 1", bad(dict(base, marginals={"x": 1.5, "y": 0.5})))
    check("negative rate", bad(dict(base, marginals={"x": -0.1, "y": 0.5})))
    check("nan rate", bad(dict(base, marginals={"x": float("nan"), "y": 0.5})))
    check("missing seat rate", bad(dict(base, marginals={"x": 0.3})))
    check("empty name", bad(dict(base, a_name="")))
    for kwargs in ({}, {"pairs": "nope"}):
        try:
            bc.stats(kwargs)
            check("envelope required", False)
        except ValueError:
            pass
    try:
        bc.stats([base])  # a bare list is the pre-envelope schema
        check("bare list refused", False)
    except ValueError:
        pass
    conflict = {"pairs": [base, dict(base, marginals={"x": 0.9, "y": 0.5})]}
    try:
        bc.stats(conflict)
        check("conflicting external rate refused", False)
    except ValueError:
        pass
    check("valid pair passes", bc.stats({"pairs": [base]})["n"] == 1)


def test_stats_empty():
    check("empty", bc.stats({"pairs": []}) == {"n": 0})


# Explicit list, not a globals() sweep: ci_selfexec_test.py walks ast.Name references
# and calls a sweep's tests inert (they never execute as far as it can see). The
# staleness check in main() makes a missing entry RED rather than a silently smaller
# run — the idiom is tools/claimable_test.py's.
TESTS = [
    test_seal_doc_never_carries_the_reveal,
    test_seal_verify_roundtrip,
    test_stats_abstention_is_recorded_not_coerced,
    test_stats_documented_schema_is_the_schema_the_code_reads,
    test_stats_empty,
    test_stats_homogeneous_seats_have_no_seat_note,
    test_stats_kappa_is_not_a_statistic_of_the_encoding,
    test_stats_refuses_invalid_inputs,
    test_stats_reproduces_the_arcs_blind_set,
    test_stats_undefined_kappa_stays_undefined,
    test_v2_seal_binds_the_assignment,
    test_verify_against_the_frozen_manifest,
    test_verify_freezes_the_per_probe_pair_and_encoding,
]


def main() -> int:
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        print(f"FAIL TESTS is stale: defined-not-listed={sorted(defined - listed)} "
              f"listed-not-defined={sorted(listed - defined)}")
        return 1
    failed = []
    for t in TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed.append(t.__name__)
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
