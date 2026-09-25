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
  0.4503 -> "45%").
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


def test_verify_against_the_frozen_manifest():
    doc, reveal = _sealed()
    manifest = {"round": "pilot-1", "seats": ["reviewer-a", "reviewer-b"],
                "probes": [{"eid": "record-a",
                            "record_sha256": bc.record_digest(_RECORD)}]}
    check("manifest ok", bc.verify(doc, reveal, manifest),
          f"{bc.check(doc, reveal, manifest)}")
    wrong_round = dict(manifest, round="pilot-2")
    check("wrong round refused", not bc.verify(doc, reveal, wrong_round))
    no_seat = dict(manifest, seats=["reviewer-b"])
    check("seatless reviewer refused", not bc.verify(doc, reveal, no_seat))
    wrong_packet = {"round": "pilot-1", "seats": ["reviewer-a"],
                    "probes": [{"eid": "record-a",
                                "record_sha256": bc.record_digest(b"another packet")}]}
    check("wrong packet refused", not bc.verify(doc, reveal, wrong_packet),
          "the digest of the exact presented record is bound, not just the eid")


def test_stats_reproduces_the_arcs_blind_set():
    out = bc.stats(_arc_envelope())
    expect = {"n": 10, "agree": 6, "raw_agreement": 0.6, "independence_null": 0.4503,
              "excess_pts": 15.0, "round_internal_null": 0.6, "round_excess_pts": 0.0,
              "kappa": 0.0, "pabak": 0.2,
              "cells": {"both_dissent": 0, "a_only": 4, "b_only": 0, "neither": 6},
              "round_marginals": {"codex": 0.4, "kimi-code": 0.0, "claude-code": 0.0},
              "external_marginals": {"codex": round(96 / 162, 4),
                                     "kimi-code": round(49 / 186, 4),
                                     "claude-code": round(23 / 125, 4)},
              "round": "echo-arc-reconstruction"}
    for k, v in expect.items():
        check(f"arc[{k}]", out.get(k) == v, f"got {out.get(k)}, want {v}")
    check("source echoed", "codex 96/162" in out.get("marginals_source", ""))
    check("seat_note present", "seat_note" in out,
          "the arc's blind set rotates seats — the note must say pooling is not one "
          "fixed pair's")


def test_stats_homogeneous_seats_have_no_seat_note():
    env = {"pairs": [{"a_name": "kimi-code", "b_name": "codex",
                      "a_dissent": True, "b_dissent": False,
                      "marginals": {"kimi-code": 0.3, "codex": 0.5}}]}
    out = bc.stats(env)
    check("no seat_note", "seat_note" not in out)
    check("per-name marginals", out["round_marginals"] == {"kimi-code": 1.0,
                                                           "codex": 0.0})


def test_stats_documented_schema_is_the_schema_the_code_reads():
    lines = bc.__doc__.splitlines()
    i = next((n for n, l in enumerate(lines) if "pairs.json:" in l), None)
    check("schema documented", i is not None, "usage string lost the pairs.json schema")
    schema_block = "\n".join(lines[i:i + 7]) if i is not None else ""
    for key in ("pairs", "a_name", "b_name", "a_dissent", "b_dissent", "marginals",
                "marginals_source"):
        check(f"doc has {key}", key in schema_block)
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
    test_stats_documented_schema_is_the_schema_the_code_reads,
    test_stats_empty,
    test_stats_homogeneous_seats_have_no_seat_note,
    test_stats_refuses_invalid_inputs,
    test_stats_reproduces_the_arcs_blind_set,
    test_v2_seal_binds_the_assignment,
    test_verify_against_the_frozen_manifest,
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
