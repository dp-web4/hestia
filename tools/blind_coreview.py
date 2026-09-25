#!/usr/bin/env python3
"""blind_coreview: seal / reveal / stats for blind co-review rounds.

The mesh's echo measurement (findings/echo-or-independence-the-mesh-measured-2026-09-23.md)
bottomed out at n=10 provably-blind pairs in five weeks of chain. Retrospective mining is
exhausted; this instrument manufactures blindness prospectively:

  seal   — a reviewer commits BEFORE reading any peer factor. The commitment is sha256
           over a canonical JSON payload that binds the ASSIGNMENT as well as the text:
           round id, reviewer, probe id, the digest of the exact record presented,
           verdict, basis, nonce, and the sealer's claimed time. (v1 committed over
           verdict+basis+nonce only; codex's pre-seal review reassigned reviewer, eid
           and sealed_at on a sealed doc and verification still passed — the seal bound
           the text but not its assignment. Superseded pre-deployment: no v1 seal ever
           left a test.) The nonce is generated at seal time, lives only in the private
           reveal payload, and is published with the text at the reveal: a terse basis
           ("sound, concur") is otherwise brute-forceable from the published hash
           (claude-code's pre-seal review, reproduced: recovered in a 40-candidate
           search)
  reveal — both commitments are published BEFORE either reveal; the whole payload
           follows; nothing can be revised or reassigned after. verify recomputes the
           commitment AND checks the revealed assignment against the published doc and,
           when given, the frozen round manifest (round id, seats, probe digests)
  stats  — counts, raw agreement and missingness overall; the 2-by-2 table, the
           within-sample null and Cohen's kappa PER FIXED REVIEWER PAIR (by_pair);
           the external-rate independence null overall. There is deliberately NO
           pooled positional kappa: when a round rotates seats, pooling the a/b
           positions makes kappa a statistic of the ENCODING, not of any reviewer
           pair — codex's follow-up, reproduced: the same three named reviews
           encode to kappa 0.0 or -1.0 depending only on which seat is written
           first. Undefined kappa (pe == 1) is preserved as null, never coerced.
           The independence null comes from the reviewers' LIVE-work marginals
           (external rates; their source window is echoed as `marginals_source`).
           On a stratified probe set it carries the sampling caveat. Round
           marginals are keyed by reviewer NAME, never pooled positionally.

Canonical form (so any seat can reimplement): json.dumps(payload, sort_keys=True,
separators=(",", ":"), ensure_ascii=True), UTF-8 encoded.

Probe records are terminal historical escalations — nothing to authorize, so the probe
is cheap and safe, and a reviewer's seal cannot leak into a ruling. The probe PACKET
carries the attempted act, the rule that fired, and the record as the decider saw it —
never the ruling: a seal settles order, not source, and two reviewers who can both see
the outcome anchor on it (claude-code's review, change 1).

Usage:
  blind_coreview.py seal  --reviewer kimi-code --eid <id> --round <round-id>
                          --verdict concur --basis-file f.md --record-file packet.md
                          --reveal-out private.json
                          # public seal JSON on stdout (publishable); the reveal payload
                          # (verdict+basis+nonce) written mode-0600 to --reveal-out —
                          # keep private until both seals are published
  blind_coreview.py verify --seal-file s.json --reveal-file r.json [--manifest m.json]
                          # m.json (the frozen round manifest — frozen before the first
                          # seal; when given, every piece is enforced):
                          #   {"round": str, "seats": [name, ...],
                          #    "question": str,        # the question as presented
                          #    "verdicts": [str, ...], # the frozen encoding; an
                          #                            # abstention / insufficient-
                          #                            # evidence mark is a verdict of
                          #                            # its own, never coerced boolean
                          #    "probes": [{"eid": str, "record_sha256": hex,
                          #                "reviewers": [name, name]}, ...]}
                          #                            # the TWO eligible reviewers for
                          #                            # THIS probe — eligibility is
                          #                            # per-probe, not round-wide
  blind_coreview.py stats --pairs pairs.json
                          # pairs.json: {"round": str, "marginals_source": str,   (both
                          #              optional, echoed into the output)
                          #              "pairs": [{a_name: str, b_name: str,
                          #                         a_dissent: bool | null,
                          #                         b_dissent: bool | null,
                          #                         marginals: {name: live-work
                          #                                     dissent_rate in [0,1]}}]}
                          # null dissent bit = abstain / insufficient evidence /
                          # missing reveal: counted in missingness, excluded from
                          # agreement and kappa — recorded, never coerced.
"""
import argparse
import hashlib
import json
import math
import os
import secrets
import sys
import time

SEAL_VERSION = 2

# The fields a published seal doc shares with its reveal payload. verify checks them for
# equality: this is what turns "the hash matches SOME text" into "the hash matches THIS
# reviewer, THIS probe, THIS record". sealed_at is inside the commitment too — it stays
# claimed time (the auditable ordering evidence is the daemon's queued_at on the
# publishing notice), but tampering with it now fails verification (codex's attack
# changed it to zero without breaking the seal). It is an int of seconds: a float's
# decimal spelling is implementation-defined, and the commitment must reproduce from
# ANY JSON stack.
_PUBLIC_FIELDS = ("v", "round", "reviewer", "eid", "record_sha256", "sealed_at")


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def commitment(payload: dict) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


def record_digest(record: bytes) -> str:
    return hashlib.sha256(record).hexdigest()


def seal(reviewer: str, eid: str, verdict: str, basis: str, record: bytes,
         round_id: str) -> tuple:
    """Returns (public seal doc, reveal payload). The reveal payload carries the
    verdict, basis and nonce; it never enters the published doc, and is published only
    after BOTH seats' seals are on the mesh."""
    payload = {"v": SEAL_VERSION, "round": round_id, "reviewer": reviewer, "eid": eid,
               "record_sha256": record_digest(record),
               "verdict": verdict.strip().lower(), "basis": basis.strip(),
               "nonce": secrets.token_hex(16), "sealed_at": int(time.time())}
    doc = {k: payload[k] for k in _PUBLIC_FIELDS}
    doc["sha256"] = commitment(payload)
    doc["note"] = ("commitment over (v, round, reviewer, eid, record_sha256, verdict, "
                   "basis, nonce, sealed_at); verdict+basis+nonce revealed only after "
                   "both seals publish. sealed_at is the sealer's claimed time — the "
                   "ordering evidence is the daemon's queued_at on the publishing notice")
    return doc, payload


def check(seal_doc: dict, reveal: dict, manifest: dict = None) -> list:
    """The verification, as a list of failures ([] = verified)."""
    failures = []
    if seal_doc.get("v") != SEAL_VERSION or reveal.get("v") != SEAL_VERSION:
        failures.append(f"version: want v{SEAL_VERSION} doc and reveal "
                        f"(got doc v{seal_doc.get('v')}, reveal v{reveal.get('v')})")
    if commitment(reveal) != seal_doc.get("sha256"):
        failures.append("commitment mismatch: the reveal does not hash to the "
                        "published sha256")
    for f in _PUBLIC_FIELDS:
        if seal_doc.get(f) != reveal.get(f):
            failures.append(f"assignment mismatch on {f}: published doc has "
                            f"{seal_doc.get(f)!r}, reveal has {reveal.get(f)!r}")
    if manifest is not None:
        if reveal.get("round") != manifest.get("round"):
            failures.append(f"manifest: round {reveal.get('round')!r} is not the "
                            f"frozen round {manifest.get('round')!r}")
        seats = manifest.get("seats", [])
        if reveal.get("reviewer") not in seats:
            failures.append(f"manifest: {reveal.get('reviewer')!r} holds no seat in "
                            f"this round")
        # The frozen question and verdict encoding (codex's follow-up, notice 14563):
        # a manifest that does not freeze them is not the manifest this round seals
        # against. An abstention / insufficient-evidence mark is a verdict of its own
        # in the encoding — recorded, never coerced into a boolean.
        if not isinstance(manifest.get("question"), str) or not manifest["question"]:
            failures.append("manifest: the frozen round must carry the question as "
                            "presented (a non-empty \"question\")")
        verdicts = manifest.get("verdicts")
        if (not isinstance(verdicts, list) or not verdicts
                or not all(isinstance(v, str) and v for v in verdicts)):
            failures.append("manifest: the frozen round must carry the verdict "
                            "encoding (a non-empty \"verdicts\" list, including how "
                            "abstention is recorded)")
        elif reveal.get("verdict") not in verdicts:
            failures.append(f"manifest: verdict {reveal.get('verdict')!r} is not in "
                            f"the frozen encoding {verdicts!r}")
        probe = (reveal.get("eid"), reveal.get("record_sha256"))
        entry = next((p for p in manifest.get("probes", [])
                      if (p.get("eid"), p.get("record_sha256")) == probe), None)
        if entry is None:
            failures.append(f"manifest: probe {reveal.get('eid')!r} with record digest "
                            f"{reveal.get('record_sha256')!r} is not in the frozen "
                            f"manifest — not the packet this round presented")
        else:
            reviewers = entry.get("reviewers")
            if (not isinstance(reviewers, list) or len(reviewers) != 2
                    or not all(isinstance(r, str) and r for r in reviewers)):
                failures.append(f"manifest: probe {reveal.get('eid')!r} names no "
                                f"eligible reviewer PAIR — the manifest freezes the "
                                f"two eligible reviewers per probe")
            else:
                if any(r not in seats for r in reviewers):
                    failures.append(f"manifest: probe {reveal.get('eid')!r} names a "
                                    f"reviewer holding no seat in this round")
                if reveal.get("reviewer") not in reviewers:
                    failures.append(f"manifest: {reveal.get('reviewer')!r} holds a "
                                    f"round seat but is not eligible for probe "
                                    f"{reveal.get('eid')!r} — eligibility is "
                                    f"per-probe, not round-wide")
    return failures


def verify(seal_doc: dict, reveal: dict, manifest: dict = None) -> bool:
    return not check(seal_doc, reveal, manifest)


def _validate_pair(i: int, p: dict) -> None:
    """Refuse invalid inputs before calculating (codex's review, point 3): literal
    booleans for the dissent bits — or null, the abstention / insufficient-evidence /
    missing-reveal mark that is recorded rather than coerced to a boolean (codex's
    follow-up, notice 14563); finite rates in [0,1]; names as non-empty strings; a
    pair is two DISTINCT reviewers."""
    where = f"pairs[{i}]"
    for key in ("a_name", "b_name"):
        if not isinstance(p.get(key), str) or not p[key]:
            raise ValueError(f"{where}.{key}: want a non-empty string, got {p.get(key)!r}")
    if p["a_name"] == p["b_name"]:
        raise ValueError(f"{where}: a pair is two distinct reviewers, got "
                         f"{p['a_name']!r} twice")
    for key in ("a_dissent", "b_dissent"):
        if type(p.get(key)) is not bool and p.get(key) is not None:
            raise ValueError(f"{where}.{key}: want a literal boolean or null "
                             f"(abstain / insufficient evidence / missing reveal), "
                             f"got {p.get(key)!r}")
    marginals = p.get("marginals")
    if not isinstance(marginals, dict):
        raise ValueError(f"{where}.marginals: want an object, got {marginals!r}")
    for name in (p["a_name"], p["b_name"]):
        if name not in marginals:
            raise ValueError(f"{where}.marginals: no rate for {name!r}")
    for name, rate in marginals.items():
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise ValueError(f"{where}.marginals[{name!r}]: want a number, got {rate!r}")
        if not math.isfinite(rate) or not 0 <= rate <= 1:
            raise ValueError(f"{where}.marginals[{name!r}]: want a finite rate in "
                             f"[0, 1], got {rate!r}")


def stats(round_doc) -> dict:
    """counts, raw agreement and missingness overall; the 2x2 table, within-sample
    null and Cohen's kappa per FIXED reviewer pair; the external-rate null overall.

    Input is the round envelope {"pairs": [...]}; each pair carries its seats' names,
    the two dissent bits (true/false, or null — abstain / insufficient evidence /
    missing reveal, recorded and counted, never coerced), and the reviewers' live-work
    marginals (the external rates the independence null is built from).

    There is deliberately no pooled positional kappa: when a round rotates seats,
    pooling the a/b positions makes the number a statistic of the ENCODING — codex's
    follow-up, reproduced as test_stats_kappa_is_not_a_statistic_of_the_encoding: the
    same named reviews encode to kappa 0.0 or -1.0 depending only on which seat is
    written first. Chance-corrected numbers live in by_pair, keyed by the pair's
    sorted names, with a consistent orientation inside each block. An aggregate
    chance-corrected statistic across varying pairs wants its own specified estimand
    and weighting, which relabeling a pooled output is not (codex, ibid.)."""
    if isinstance(round_doc, list):
        raise ValueError("pairs.json is a round envelope: {\"pairs\": [...], ...}, "
                         "not a bare list — the envelope is what carries "
                         "marginals_source, the external rates' provenance")
    pairs = round_doc.get("pairs")
    if not isinstance(pairs, list):
        raise ValueError("pairs.json: want a \"pairs\" list")
    for i, p in enumerate(pairs):
        if not isinstance(p, dict):
            raise ValueError(f"pairs[{i}]: want an object, got {p!r}")
        _validate_pair(i, p)
    n = len(pairs)
    if not n:
        return {"n": 0}

    complete = [p for p in pairs
                if p["a_dissent"] is not None and p["b_dissent"] is not None]
    nc = len(complete)
    missing = n - nc
    agree = sum(1 for p in complete if p["a_dissent"] == p["b_dissent"])
    po = agree / nc if nc else None

    # External null: the reviewers' live-work marginals, as supplied per pair. One rate
    # per reviewer per round — a name with two rates across pairs is a provenance
    # conflict, refused rather than silently averaged. Keyed by NAME, so it is
    # representation-independent; computed over the complete pairs, the same
    # denominator raw agreement carries.
    external = {}
    for i, p in enumerate(pairs):
        for name in (p["a_name"], p["b_name"]):
            rate = p["marginals"][name]
            if name in external and external[name] != rate:
                raise ValueError(f"pairs[{i}].marginals: {name!r} has rate {rate} here "
                                 f"but {external[name]} earlier — one external rate per "
                                 f"reviewer per round; per-stratum rates want per-stratum "
                                 f"runs")
            external[name] = rate
    null = None
    if nc:
        null = sum(external[p["a_name"]] * external[p["b_name"]]
                   + (1 - external[p["a_name"]]) * (1 - external[p["b_name"]])
                   for p in complete) / nc

    # Per fixed unordered pair: sorted names are the key, the orientation inside each
    # block is those names in sorted order, and the 2x2 / within-sample null / kappa
    # are computed inside the block only. Kappa stays null when pe == 1 (undefined),
    # never coerced.
    groups = {}
    for p in pairs:
        (n1, b1), (n2, b2) = sorted(((p["a_name"], p["a_dissent"]),
                                     (p["b_name"], p["b_dissent"])))
        g = groups.setdefault(f"{n1}+{n2}", {"orientation": [n1, n2], "bits": []})
        g["bits"].append((b1, b2))
    by_pair = {}
    for key in sorted(groups):
        g = groups[key]
        bits = [(b1, b2) for b1, b2 in g["bits"] if b1 is not None and b2 is not None]
        m, mc = len(g["bits"]), len(bits)
        block = {"n": m, "complete": mc, "missing": m - mc,
                 "orientation": g["orientation"]}
        if mc:
            ga = sum(1 for b1, b2 in bits if b1 == b2)
            gpo = ga / mc
            d1 = sum(b1 for b1, _ in bits) / mc
            d2 = sum(b2 for _, b2 in bits) / mc
            pe = d1 * d2 + (1 - d1) * (1 - d2)
            kappa = (gpo - pe) / (1 - pe) if pe < 1 else None
            block.update({
                "agree": ga, "raw_agreement": round(gpo, 4),
                "cells": {"both_dissent": sum(1 for b1, b2 in bits if b1 and b2),
                          "a_only": sum(1 for b1, b2 in bits if b1 and not b2),
                          "b_only": sum(1 for b1, b2 in bits if not b1 and b2),
                          "neither": sum(1 for b1, b2 in bits if not b1 and not b2)},
                "round_internal_null": round(pe, 4),
                "round_excess_pts": round(100 * (gpo - pe), 1),
                "kappa": round(kappa, 3) if kappa is not None else None,
                "pabak": round(2 * gpo - 1, 3)})
        else:
            block.update({"agree": 0, "raw_agreement": None, "cells": None,
                          "round_internal_null": None, "round_excess_pts": None,
                          "kappa": None, "pabak": None})
        by_pair[key] = block

    # Round marginals keyed by NAME (each reviewer's whole round, either seat, complete
    # pairs only) — never pooled positionally.
    dissents, appearances = {}, {}
    for p in complete:
        for name, bit in ((p["a_name"], p["a_dissent"]), (p["b_name"], p["b_dissent"])):
            dissents[name] = dissents.get(name, 0) + int(bit)
            appearances[name] = appearances.get(name, 0) + 1
    round_marginals = {name: round(dissents[name] / appearances[name], 4)
                       for name in appearances}

    out = {"n": n, "complete": nc, "missing": missing,
           "agree": agree,
           "raw_agreement": round(po, 4) if po is not None else None,
           "independence_null": round(null, 4) if null is not None else None,
           "excess_pts": round(100 * (po - null), 1) if nc else None,
           "pabak": round(2 * po - 1, 3) if po is not None else None,
           "round_marginals": round_marginals,
           "external_marginals": {k: round(v, 4) for k, v in sorted(external.items())},
           "by_pair": by_pair}
    if round_doc.get("marginals_source"):
        out["marginals_source"] = round_doc["marginals_source"]
    if round_doc.get("round"):
        out["round"] = round_doc["round"]
    if len(by_pair) > 1:
        out["seat_note"] = ("seats vary by pair: chance-corrected statistics are per "
                            "fixed reviewer pair (by_pair); a pooled positional kappa "
                            "is a statistic of the encoding, not of any pair, and is "
                            "deliberately not reported")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seal")
    s.add_argument("--reviewer", required=True)
    s.add_argument("--eid", required=True)
    s.add_argument("--round", dest="round_id", required=True)
    s.add_argument("--verdict", required=True)
    s.add_argument("--basis-file", required=True)
    s.add_argument("--record-file", required=True)
    s.add_argument("--reveal-out", required=True,
                   help="private reveal payload (verdict+basis+nonce), written 0600")
    v = sub.add_parser("verify")
    v.add_argument("--seal-file", required=True)
    v.add_argument("--reveal-file", required=True)
    v.add_argument("--manifest")
    st = sub.add_parser("stats")
    st.add_argument("--pairs", required=True)
    a = ap.parse_args()

    try:
        if a.cmd == "seal":
            doc, payload = seal(a.reviewer, a.eid, a.verdict, open(a.basis_file).read(),
                                open(a.record_file, "rb").read(), a.round_id)
            fd = os.open(a.reveal_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=1)
            print(json.dumps(doc, indent=1))
            print(f"reveal payload (PRIVATE until both seals publish): {a.reveal_out}",
                  file=sys.stderr)
        elif a.cmd == "verify":
            manifest = json.load(open(a.manifest)) if a.manifest else None
            failures = check(json.load(open(a.seal_file)),
                             json.load(open(a.reveal_file)), manifest)
            if failures:
                print("SEAL MISMATCH")
                for f in failures:
                    print(f"  - {f}")
                return 1
            print("VERIFIED")
        else:
            print(json.dumps(stats(json.load(open(a.pairs))), indent=1))
    except (ValueError, KeyError) as e:
        print(f"INVALID: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
