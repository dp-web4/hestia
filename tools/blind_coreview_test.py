#!/usr/bin/env python3
"""Contract tests for tools/blind_coreview.py — the blind co-review instrument.

The load-bearing ones:

- `test_seal_doc_never_carries_the_nonce` — the nonce is what stops a terse basis from
  being brute-forced off the published hash before the reveal (claude-code's pre-seal
  review, reproduced: a ("concur" / "sound, concur") seal falls to a 40-candidate
  dictionary when the commitment is verdict+basis alone). If the nonce ever leaks into
  the published doc, that protection is zero, so the check is on the doc's bytes.
- `test_stats_reproduces_the_arcs_blind_set` — the REAL 10-pair blind set from the echo
  measurement, rebuilt from /tmp/kimi-echo-factors.json by the arc's own walk
  (adjacent cross-reviewer factor pairs <=120 s apart; e1bc557f dropped as one vendor
  under two names), marginals codex 96/162, kimi-code 49/186, claude-code 23/125.
  Pins the published numbers at full precision (the findings table renders 2 dp:
  0.4503 -> "45%").
- `test_stats_documented_schema_is_the_schema_the_code_reads` — regression for
  `KeyError: 'a_name'`: the usage string originally omitted a_name/b_name, so a
  pairs.json built to the documented schema crashed. Every key the stats() loop reads
  must appear in the module docstring's schema line.

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


def _arc_pairs():
    return [{"a_name": a, "b_name": b, "a_dissent": da, "b_dissent": db,
             "marginals": _MARGINALS} for _, a, b, da, db in _BLIND10]


def test_seal_verify_roundtrip():
    doc, nonce = bc.seal("kimi-code", "e" * 16, "Concur", "  the record is sound  ")
    check("roundtrip", bc.verify(doc, "concur", "the record is sound", nonce),
          "canonicalization (strip/case) must round-trip")


def test_seal_doc_never_carries_the_nonce():
    doc, nonce = bc.seal("kimi-code", "e" * 16, "concur", "sound, concur")
    check("nonce absent", nonce not in json.dumps(doc),
          "the published doc must not contain the nonce")
    check("nonce looks random", len(nonce) == 32 and all(c in "0123456789abcdef" for c in nonce))


def test_wrong_nonce_or_tampered_text_fails():
    doc, nonce = bc.seal("kimi-code", "e" * 16, "concur", "sound, concur")
    check("wrong nonce", not bc.verify(doc, "concur", "sound, concur", "00" * 16))
    check("tampered basis", not bc.verify(doc, "concur", "sound, concur.", nonce))
    check("tampered verdict", not bc.verify(doc, "dissent", "sound, concur", nonce))
    doc2, nonce2 = bc.seal("kimi-code", "e" * 16, "concur", "sound, concur")
    check("nonce binds", doc["sha256"] != doc2["sha256"],
          "identical verdict+basis must seal differently under different nonces")


def test_stats_reproduces_the_arcs_blind_set():
    out = bc.stats(_arc_pairs())
    expect = {"n": 10, "agree": 6, "raw_agreement": 0.6, "independence_null": 0.4503,
              "excess_pts": 15.0, "round_internal_null": 0.6, "round_excess_pts": 0.0,
              "kappa": 0.0, "pabak": 0.2,
              "marginals": {"a_dissent": 0.4, "b_dissent": 0.0}}
    for k, v in expect.items():
        check(f"arc[{k}]", out.get(k) == v, f"got {out.get(k)}, want {v}")


def test_stats_documented_schema_is_the_schema_the_code_reads():
    lines = bc.__doc__.splitlines()
    i = next((n for n, l in enumerate(lines) if "pairs.json:" in l), None)
    check("schema documented", i is not None, "usage string lost the pairs.json schema")
    schema_block = "\n".join(lines[i:i + 3]) if i is not None else ""
    for key in ("a_name", "b_name", "a_dissent", "b_dissent", "marginals"):
        check(f"doc has {key}", key in schema_block)
    out = bc.stats(_arc_pairs()[:1])  # a pairs.json built to the docstring must not raise
    check("no KeyError", out["n"] == 1)


def test_stats_empty():
    check("empty", bc.stats([]) == {"n": 0})


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok: {fn.__name__}")
    print(f"ok: 0 failure(s), {len(fns)} test(s)")
