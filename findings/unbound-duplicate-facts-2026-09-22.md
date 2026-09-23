# The unbound duplicate: five findings in one PR, one defect class

**2026-09-22, cbp-claude, from the review of #1104 (Stage 0 of harvesting #934).**
Reviewers: chatgpt-gpt5.6-sol, five findings over four review rounds.

## The class

> The same fact represented twice, with no mechanical relationship between the copies.

Every one of the five findings on #1104 was an instance. None was a logic error, none would
have been caught by a type checker, and every copy was individually plausible — which is
exactly why they survived. Two copies of a fact do not disagree *visibly*; they disagree
only when something forces them to be compared, and nothing did.

Four of the five were introduced or propagated **while fixing the previous one**. That is
the signature of the class: fixing one copy of an unbound pair is indistinguishable, at the
time, from fixing the fact.

## The five

| # | fact | copy A (authority) | copy B (drifted) |
|---|---|---|---|
| 1 | which functions a shim may define | `PERMITTED_FUNCTIONS` in the template | the PRD's numbered table — 4 of 8 names stale |
| 2 | which of them must be byte-identical | `BYTE_IDENTICAL_FUNCTIONS` / `ADAPTER_FUNCTIONS` | the table's *kind* column — inverted C4's split to 3/5 |
| 3 | how many of each | the two tuples' lengths | C4's prose, "Three of them … the other five" |
| 4 | the certification scalars | `SHIM_CERTIFICATION_SCHEMA`, `CERTIFICATION_CRITERIA`, `REQUIRED_GATE_API` | a third copy re-typed in `tools/shim_certification.py` |
| 5 | **the criteria themselves** | `docs/PRD_SHIM_CERTIFICATION.md` contents | the label `PRD_SHIM_CERTIFICATION.md@2026-09-04` in the preimage |

Finding 5 is the one worth remembering. The PRD's own formula specifies
`sha256(criteria_version + shim bytes + runtime set + gate API version + justified
difference declaration)`, and its vault record carries a `criteria_version` field. The
implementation supplied a criteria **name**. The spec asked for a version; a hand-maintained
string cannot be one.

**The demonstration was free, because this PR had already performed the experiment.** In
`5fd0440` and `8867d75` I changed the normative criteria four times — the function names,
their kinds, C4's split, C4's worked example — and reported, as reassurance, that every
certification digest was unchanged: `39a843e5`, `c7851095`, `a2842e92`, `2dd43377`. Those
unchanged digests were not reassurance. They were the defect, printed twice, by me, in the
commit messages that caused it. After binding the bytes, the same four moved to `4aae5f19`,
`97efa337`, `f0e0a22d`, `0eeb15c8` — with the label still reading `@2026-09-04`.

## Why "be careful" is not the fix

Findings 1–3 are the same document drifting from the same tuple, three times, and the third
time was *after* a fix whose commit message explained the hazard. The document even carries
a parenthetical recording that its **first** draft had three enumerations disagreeing with
each other. So the score is: four drifts, one of them committed by an author who had just
finished writing a paragraph about the drift.

Care does not scale across authors, sessions or months. A mechanical relation does.

## The fix that generalizes

For each duplicated fact, name which copy is authoritative and add a falsifier that fails
when the copies disagree. On #1104 that is 11 arms, of which 7 exist purely to bind copies:
the PRD's names, its kinds, C4's counts and named sets, the scalars, the criteria bytes, and
the missing-criteria case.

**Then break each one on purpose.** A falsifier that passes against the defect it names is
decoration. Each was verified by reintroducing the defect in a throwaway tree:

| reintroduced | caught by |
|---|---|
| stale PRD names | *"PRD table and PERMITTED_FUNCTIONS disagree"* |
| kind column back to per-seat | *"PRD calls `_emergency_block` per-seat; the template declares it byte-identical"* |
| C4 counts back to three/five | *"C4 says 'Three' byte-identical; the template declares 5"* |
| scalars re-typed in the tool | subject ignored a change to the canonical schema |
| preimage carries the label only | *"the criteria document changed and the certification did not"* |
| missing criteria doc | *"a missing criteria document still produced a certification"* |
| verifier defaults home to `~/.hestia` | silently searched a guessed tree |

Seven reintroduced, seven caught.

## The pattern done right, already in this repo

`plugins/_shared/RUNTIME_MANIFEST.txt` is the counter-example and predates all of this. Its
header says the engine set is *"a DECLARATION, one filename per line"* rather than a glob,
and `tools/installer_shared_engine_test.py` enforces it **in both directions**: every
declared entry must exist and not be a test, and every `_shared` module any hook imports
must be declared. That is a duplicated fact — "what the engine is" lives in the manifest and
in the import graph — held equal by a test. It has not drifted.

The difference is not that its author was more careful. It is that the pair is bound.

## Candidate unbound pairs, untested

Named so the next reader can check rather than re-derive. **None of these is measured — they
are suspects, not findings:**

- `ci.yml`'s gate-collapse pin vs. what `tools/gate_collapse_meter.py` measures (the pin was
  raised three times in one day on #1084, which is the drift smell).
- The published law text vs. the classifier that implements it — the `.env`-inside-
  `os.environ` false positive is a live instance of prose and matcher disagreeing.
- `SHIM_LEDGER.md`'s 8-hex source digests vs. the functions they name (`tools/shim_ledger_check.py`
  exists; whether it binds *content* or only presence is unverified here).
- The PRD's *"the runtime set bound must be the DEPLOYED one, not the repository's"* vs. what
  `shim_certification.py` puts in a vault record. Raised on #1104, agreed as a real
  integration question and deferred to the #1085 handoff, not a Stage-0 blocker.

## The question to ask

When writing or reviewing anything normative:

> **What is the other copy of this fact, and what breaks when they disagree?**

If the answer to the second half is "nothing", the copies will diverge. Not might.
