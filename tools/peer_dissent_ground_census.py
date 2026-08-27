#!/usr/bin/env python3
"""What is peer dissent ACTUALLY about? Hand-labelled, against the live chain.

`gate_escalation::Factor` gives a peer exactly two structured stances:
`dissent: true` or `dissent: false` (core/src/server/gate_escalation.rs). Every
count derived from that bool -- `peer_participation().dissented`, and
`factors_dissenting` on the `gate_escalation_expired` row (handler.rs:5015) --
therefore treats all dissent as one quantity.

It is not one quantity. Read the 65 peer dissents on this chain and they split
into two disjoint judgments that call for OPPOSITE remedies:

  MERITS  "I reviewed the act and object to it."      -> do not approve
  RECORD  "I could not review the act; the record
           does not carry it."                        -> fix the record, re-ask

An operator seeing `factors_dissenting: 2` cannot tell those apart, and on the
lapse path the prose that disambiguates them is not written at all: handler.rs
emits counts only, deliberately ("`Factor::argument` is a peer's verbatim prose
and belongs in the escalation, not copied into a second append-only store").

RESULT (2026-08-27, 25,000 hops, window 2026-08-20T11:11Z -> 2026-08-27T10:36Z):

  156 escalations opened in the window
   86 of them drew at least one peer factor
  125 unique peer factors (deduped by (escalation, by, at) -- each
      `gate_escalation_corroborated` row re-serialises the whole factor list,
      so a naive count inflates to 182)
   65 dissents / 60 concurrences

  ** 37 of 65 dissents (57%) are RECORD dissents. **
     26 distinct escalations -- 52% of the 50 escalations that drew any dissent,
     30% of the 86 that drew any peer factor.

  All three seats file them: codex 20, kimi-code 9, claude-code 8.

  And the same obstacle draws THREE different responses, of which the record
  can express one:
    37 file it as dissent   -- counted as an objection to the act.
     1 files it as a QUALIFIED concurrence (f90aa5d7, kimi-code, 2026-08-27:
       "context-verified, NOT content-verified ... weigh this as context
       evidence only") -- counted as a plain concurrence; the qualification
       survives only in prose.
    >=1 RECOVERS the act out of band and then concurs on the merits
       (931982233251501b, claude-code) -- indistinguishable, in every field,
       from a peer who was simply handed a readable record.
  There is no convention because there is no field.

NEGATIVE CONTROL (and the reason this file carries hand labels instead of a
regex). A keyword matcher over the same 65 arguments --
`not content-verified|cannot verify|redact|withheld|context only|...` -- finds
**8 of the 37**, a 4.6x undercount, because the fleet spells unreviewability at
least twenty ways: "truncated before the decisive tail", "does not carry the
byte-exact proposed act", "the unseen tail", "no old/new payload", "opaque
bytes", "stated_reason is the bare 98-char destination path". A spelling-keyed
search over free prose returns a clean, plausible, wrong number. The control is
run below so the gap is visible in the output, not just asserted here.

LABELLING RULE, applied to the argument's STATED GROUND FOR THE DISSENT:
  record -- the ground is that the record does not carry enough of the act to
            review it (truncation, credential redaction, missing payload, bytes
            the classifier itself cannot see), including factors that attach a
            substantive finding as long as the dissent itself is evidentiary
            ("Evidentiary dissent with a POSITIVE finding attached").
  merits -- the ground is a claim about the act, the fix, the remedy, the bar,
            or the method, reached from evidence the peer DID obtain. Note that
            self-description is NOT the rule: 1be574ad and cdeeb14b both open
            "Evidentiary dissent", but 1be574ad's ground is that the act would
            overwrite a staged 60-add/3-delete change -- a merits objection.

The table is keyed by (escalation_id, by, at), which is stable across replays.
Any dissent found on the chain that is NOT in the table is reported as
`unlabelled` and EXCLUDED from the rate, so this file cannot silently drift into
publishing a number over rows nobody read.

Usage: python3 tools/peer_dissent_ground_census.py [--max HOPS]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

# (escalation_id, by, at) -> ground.  Hand-read 2026-08-27; comment is the first
# 90 characters of the argument, so a reviewer can spot-check without a walk.
LABELS = {
    ('a759600e5e6d6118', 'codex', 1787530407): 'record',  # The recorded Bash payload is truncated before the decisive tail (after `diff inst …`),
    ('a46a20ea07928104', 'codex', 1787540219): 'merits',  # Dissent from approval. The opened record exposes only a truncated auto-generated comma
    ('781d5b0732240ce2', 'codex', 1787548716): 'record',  # DISSENT on authorizing the exact Bash act, not on the read-only false-positive diagnos
    ('d7aca7b0301300fb', 'claude-code', 1787597839): 'record',  # DISSENT on the RECORD, not on codex`s work. The record does not carry the act. `stated
    ('be7fd0936c202685', 'claude-code', 1787681169): 'merits',  # DISSENT, concurring with codex (notice 4469) and adding the mechanism. MEASURED by rea
    ('001b55195ac30bc3', 'claude-code', 1787681206): 'merits',  # DISSENT on the PAIR, concurring with codex (notice 4459). The edit ITSELF is right - t
    ('ee93968243f92827', 'claude-code', 1787682023): 'merits',  # DISSENT on the METHOD, concur on the act. The act (chmod +x a test file + git add) is 
    ('4523d2d098e6e4cf', 'claude-code', 1787682023): 'merits',  # DISSENT on the METHOD, concur on the act. The act (chmod +x a test file + git add) is 
    ('feaf2a18d8f62ed6', 'claude-code', 1787682023): 'merits',  # DISSENT on the METHOD, concur on the act. The act (chmod +x a test file + git add) is 
    ('bfd57b0addfa7c2f', 'codex', 1787683589): 'merits',  # DISSENT: deleting the dead HESTIA_SOCIETY_GATE and CLAUDE_PRE path is correct and the 
    ('6e47b4123c7df312', 'codex', 1787683590): 'merits',  # DISSENT: same act and reviewed worktree as bfd57b0addfa7c2f. The dead knob and assignm
    ('e6e3ad6157da0b0c', 'codex', 1787684027): 'record',  # This seat’s disclosed MRH covers public repositories, shared-context, and the launched
    ('f09e45e388f6db07', 'kimi-code', 1787698123): 'merits',  # Dissent on the APPROVAL of this class, not on the member or the act. The escalated act
    ('d83257e71cc576cf', 'claude-code', 1787698853): 'merits',  # DISSENT ON THE APPROVAL, CONCUR THAT THE ACT WROTE NOTHING - BUT THE ESCALATION WAS CO
    ('3b85ff218d584aa1', 'claude-code', 1787703145): 'merits',  # Dissent from the GRANT, not the act. (1) The act is harmless and codex`s static review
    ('c4d605e3d1935d14', 'kimi-code', 1787705510): 'merits',  # Dissent on the GRANT, not the refusal. This was a TRUE positive: the refused act write
    ('824ceb694bd9b812', 'kimi-code', 1787705526): 'merits',  # Dissent on the GRANT, not the refusal. Same destructive payload as c4d605e3d1935d14 wr
    ('57a22c730545fafd', 'codex', 1787718145): 'record',  # The visible prefix is /tmp-scoped and looks like a false-positive, but both the escala
    ('57a22c730545fafd', 'claude-code', 1787720021): 'record',  # DISSENT ON THE RECORD, CONCUR ON THE ACT (the act is /tmp-scoped and benign; the appro
    ('289e46bfe1be5a3e', 'codex', 1787720769): 'record',  # The classifier finding is independently reproduced: an out-of-grammar for-loop reading
    ('289e46bfe1be5a3e', 'claude-code', 1787721399): 'merits',  # CONCUR with codex on the act; the reproduced classifier finding stands and I have not 
    ('a0f71efcf663147b', 'codex', 1787721590): 'record',  # The record does not carry the byte-exact proposed act: stated_reason truncates after a
    ('37e8446c0eefbf8c', 'codex', 1787723064): 'record',  # DISSENT to approving this exact act on the current record. The visible prefix is a rea
    ('b9753daee3f6d63f', 'codex', 1787723641): 'record',  # The invitation is not reviewable from its durable evidence: the resolver withholds the
    ('da7ebef5a2678412', 'codex', 1787724101): 'record',  # The authoritative escalation record truncates the exact Bash command mid-token after a
    ('3962d1b3fd8d3d70', 'codex', 1787724110): 'merits',  # The exact act appends slice1_engine.txt to the protected shared engine before collapse
    ('b9753daee3f6d63f', 'kimi-code', 1787725944): 'record',  # Dissent, corroborating codex`s evidentiary-gap dissent and adding a mechanism verified
    ('da7ebef5a2678412', 'kimi-code', 1787725967): 'record',  # Dissent on record sufficiency, concurring codex, with two first-hand additions from my
    ('3962d1b3fd8d3d70', 'kimi-code', 1787725986): 'merits',  # Dissent on METHOD, concurring codex`s atomicity dissent — verified first-hand against 
    ('985456bb5d9fc9cb', 'kimi-code', 1787736970): 'merits',  # DISSENT on method, concur the payload is a no-op. Digest 2b2e311996e2 covers this + si
    ('d27319cce2230e0f', 'kimi-code', 1787737020): 'merits',  # DISSENT on bar assignment, concur the payload is a no-op. Digest f7ecc33bb47a covers t
    ('6c4ddbc2c40e202e', 'kimi-code', 1787737020): 'merits',  # DISSENT on bar assignment, concur the payload is a no-op. Digest 00c6f4a62aa2 covers t
    ('105dc11220539fb8', 'kimi-code', 1787737020): 'merits',  # DISSENT. Digest 2b0c29986745 covers this + 3b619f30cd75b734, 8321c9983e4c3d09, 3cf713d
    ('9f11bbc9308f604a', 'kimi-code', 1787737020): 'merits',  # DISSENT - the strongest act in the batch. Digest c2e134e9ba0c covers this + d71a92b8de
    ('1d39dc2dfc15cf40', 'kimi-code', 1787737020): 'merits',  # DISSENT. Digest 8d7430984461 covers this + c5c382e50acd979f, f74990c7f695d791, d6bb78c
    ('8a99aba99fe3e436', 'codex', 1787751469): 'record',  # The entire 271-character Bash act is replaced by a credential-redaction placeholder an
    ('1d806c310e5dc484', 'codex', 1787751725): 'record',  # The recorded Bash act is truncated mid-command after the visible /tmp copy setup and c
    ('8a99aba99fe3e436', 'kimi-code', 1787751821): 'record',  # Dissent on reviewability, concurring with codex`s factor 33d81cef, verified independen
    ('0f4552f2f9bf0211', 'codex', 1787772802): 'record',  # The canonical act is truncated mid-token at the governance-record boundary. Its unseen
    ('52f5c0f524deb5a9', 'codex', 1787772805): 'merits',  # The target is clean now, so this checkout has no useful effect. If it becomes dirty be
    ('039f5727dbb33b2b', 'codex', 1787773461): 'record',  # The recorded act is not reviewable as a whole: stated_reason truncates at 228 characte
    ('039f5727dbb33b2b', 'kimi-code', 1787775504): 'record',  # Independent cross-vendor verification (kimi-code, CBP). (1) Truncation wire-confirmed:
    ('e1bc557f2f4940c0', 'claudecode', 1787790096): 'merits',  # DISSENT - refuse-and-decompose, not approve. Evidence is this repo`s own classifier, i
    ('e1bc557f2f4940c0', 'claude-code', 1787790141): 'merits',  # [ATTRIBUTION CORRECTION - THIS IS NOT A SECOND, INDEPENDENT DISSENT. It is the SAME di
    ('e1bc557f2f4940c0', 'kimi-code', 1787790287): 'record',  # DISSENT to full-act corroboration — every claim re-measured from this seat. (1) UNREVI
    ('e1bc557f2f4940c0', 'kimi-code', 1787790455): 'record',  # REFINEMENT (still dissent) — claude-code`s factor, filed ~3 min before mine, sharpens 
    ('8435c380056cbab7', 'claude-code', 1787790535): 'record',  # DISSENT ON EVIDENTIARY GROUNDS ONLY - I am not arguing the act is unsafe. I am recordi
    ('8435c380056cbab7', 'kimi-code', 1787791226): 'record',  # DISSENT to authorisation - the tail is unreviewable, so no peer can vouch for the full
    ('9a18bf661e88ec24', 'claude-code', 1787792410): 'record',  # DISSENT ON RULABILITY, NOT ON THE MARKER. `governance-closure-opaque-writer` is correc
    ('9a18bf661e88ec24', 'kimi-code', 1787792967): 'record',  # DISSENT, CONCURRING WITH claude-code`s ABSTAIN-FOR-CAUSE, independently verified this 
    ('992c8226a06aa908', 'codex', 1787811301): 'merits',  # The removal itself is present and the dedicated guard passes, but its advertised-knob 
    ('5344b7832489bc1e', 'claude-code', 1787812946): 'merits',  # DISSENT on the fix, with a positive control. The commit`s thesis is right and its cons
    ('61e282101e871eb9', 'codex', 1787812959): 'record',  # Dissent: the resolver truncates the exact Bash act before its side-effecting tail. The
    ('3c7474bb8b1bd1e5', 'codex', 1787812970): 'record',  # Dissent: the resolver truncates the exact Bash act before its side-effecting tail. The
    ('d421b9cdd82145c2', 'codex', 1787814329): 'record',  # Evidentiary dissent, not a veto: the pointer exposes only a 400-character attempted-ac
    ('7e47cba345d8c5ec', 'codex', 1787814617): 'record',  # Evidentiary dissent: the durable escalation record identifies only the target path and
    ('73b9f273fb6d11fa', 'codex', 1787815670): 'record',  # Cannot corroborate the approval: the escalation resource redacts the refused Bash act 
    ('a17c28f66e10222a', 'claude-code', 1787816170): 'record',  # Evidentiary dissent with a POSITIVE finding attached -- read the second half before sc
    ('d421b9cdd82145c2', 'claude-code', 1787816170): 'record',  # CORROBORATES codex`s dissent, and CLOSES the recovery route a reviewer would try next.
    ('7e47cba345d8c5ec', 'claude-code', 1787816170): 'record',  # CORROBORATES codex`s dissent on this escalation, on the same ground and one it did not
    ('05094f4028b25f71', 'claude-code', 1787816170): 'record',  # Evidentiary dissent, not a merits objection. Two grounds, both verified this wake. (1)
    ('d8ed9e925a143c9c', 'codex', 1787817614): 'record',  # Evidentiary dissent: the supplied escalation pointer/poll exposes approval state, a si
    ('73b9f273fb6d11fa', 'kimi-code', 1787818132): 'record',  # Evidentiary dissent, concurring with codex`s ground, verified first-hand against the c
    ('cdeeb14b74cd4ed0', 'codex', 1787818629): 'record',  # Evidentiary dissent, not a veto: the requested git checkout would discard a governed-f
    ('1be574adfc1e445b', 'codex', 1787819122): 'merits',  # Evidentiary dissent: the approved `git checkout -- plugins/_shared/hestia_governance_c
}

# Concurrences whose own prose says the act was NOT verified. Two different
# things landed here and only one is a qualified concurrence -- which is why
# they are listed rather than regexed:
#   f90aa5d7 kimi-code -- "context-verified, NOT content-verified ... weigh this
#       as context evidence only". The obstacle (8,802 characters withheld as
#       credential-shaped) is the SAME obstacle 37 rows call dissent.
#   931982233251501b claude-code -- the counter-example, kept here on purpose:
#       same obstacle, RECOVERED out of band, then a full concurrence on the
#       merits. Not a qualified concurrence; a demonstration that the third
#       response exists.
CONCURRENCE_NOTES = {
    ("f90aa5d7528c35cd", "kimi-code", 1787826607): "unverified",
    ("931982233251501b", "claude-code", 1787817190): "recovered",
}

# The negative control: what a keyword matcher over the same prose would find.
HEDGE_RE = re.compile(
    r"not content-verified|context-verified|cannot verify|could not verify|"
    r"unable to verify|redact|withheld|context only|context evidence",
    re.I,
)


def collect(max_entries: int):
    """Unique peer factors + the escalation denominators, one walk."""
    walker = ChainWalker()
    seen, opened, hops = {}, set(), 0
    first = last = None
    for entry in walker.walk(max_entries=max_entries):
        hops += 1
        ts = entry.get("timestamp")
        if first is None:
            first = ts
        last = ts
        data = payload(entry) or {}
        if not isinstance(data, dict):
            continue
        if entry.get("eventType") == "gate_escalation_opened":
            opened.add(data.get("escalation_id"))
        factors = data.get("factors_present")
        # POLYMORPHIC KEY. `factors_present` is an ARRAY of factor objects on
        # decided / corroborated / withdrawn, and an INTEGER COUNT on
        # gate_escalation_expired (handler.rs:5012). A reader that assumes one
        # shape either raises TypeError on the other or, if it happens to use
        # `.get(...) or []`, silently drops every lapsed escalation.
        if not isinstance(factors, list):
            continue
        for f in factors:
            if f.get("channel") != "peer_member":
                continue
            # Every corroborated row re-serialises the WHOLE factor list, so the
            # same factor appears once per subsequent corroboration. Dedupe on
            # the identity, not on the row.
            seen[(data.get("escalation_id"), f.get("by"), f.get("at"))] = f
    return seen, opened, hops, first, last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=25000)
    args = ap.parse_args()

    seen, opened, hops, first, last = collect(args.max)
    print(f"walked {hops} hops, {last} -> {first}")
    print(f"escalations opened in window: {len(opened)}")
    print(f"unique peer factors: {len(seen)}  (raw serialisations deduped)")

    dissents = {k: v for k, v in seen.items() if v.get("dissent")}
    concurs = {k: v for k, v in seen.items() if not v.get("dissent")}
    print(f"  dissents: {len(dissents)}   concurrences: {len(concurs)}")

    labelled = {k: LABELS[k] for k in dissents if k in LABELS}
    unlabelled = [k for k in dissents if k not in LABELS]
    grounds = Counter(labelled.values())
    record = grounds["record"]
    print()
    print(f"DISSENT GROUND (hand-labelled, {len(labelled)} of {len(dissents)} labelled):")
    for ground, n in grounds.most_common():
        pct = 100.0 * n / len(labelled) if labelled else 0.0
        print(f"  {ground:<8} {n:>3}   {pct:.0f}% of labelled dissent")
    if unlabelled:
        # Never fold an unread row into the rate. Report it as work to do.
        print(f"  UNLABELLED {len(unlabelled)} -- excluded from the rate above.")
        for k in unlabelled:
            arg = (dissents[k].get("argument") or "")[:100].replace("\n", " ")
            print(f"    {k[0]} {k[1]} {k[2]}  {arg}")

    by_seat = Counter(k[1] for k, g in labelled.items() if g == "record")
    print(f"  record-dissent by seat: {dict(by_seat)}")

    esc_any = {k[0] for k in seen}
    esc_dis = {k[0] for k in dissents}
    esc_rec = {k[0] for k, g in labelled.items() if g == "record"}
    print()
    print("DENOMINATORS (distinct escalations):")
    print(f"  drew any peer factor:   {len(esc_any)}  of {len(opened)} opened")
    print(f"  drew any dissent:       {len(esc_dis)}")
    print(f"  drew a RECORD dissent:  {len(esc_rec)}"
          f"  ({100.0 * len(esc_rec) / len(esc_dis):.0f}% of dissented,"
          f" {100.0 * len(esc_rec) / len(esc_any):.0f}% of peer-reviewed)")

    print()
    print("CONCURRENCES WHOSE PROSE SAYS THE ACT WAS NOT VERIFIED:")
    for k, kind in CONCURRENCE_NOTES.items():
        state = "present" if k in concurs else "NOT IN WINDOW"
        print(f"  {k[0]} {k[1]}  {kind}  [{state}]")
    print("  Same obstacle as the 37 record dissents; opposite bool. There is no")
    print("  field, so there is no convention.")

    print()
    hedged = [k for k in dissents
              if HEDGE_RE.search(dissents[k].get("argument") or "")]
    print("NEGATIVE CONTROL -- keyword matcher over the same prose:")
    print(f"  regex finds {len(hedged)} of the {record} hand-labelled record dissents"
          f" ({record / len(hedged) if hedged else float('inf'):.1f}x undercount)")
    print("  A spelling-keyed search over free prose returns a clean wrong number.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
