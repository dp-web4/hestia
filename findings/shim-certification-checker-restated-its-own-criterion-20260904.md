# The certification checker restated its own criterion, and the two copies disagreed

**Date:** 2026-09-04 · **Seat:** claude-code · **Branch:** `cbp/shim-certification` (PR #932)
**Status:** defect CONFIRMED empirically in my own PR; repair half-landed, half-blocked on escalation `74a79f8928c25202`.

## What happened

PR #932 ships shim certification: criteria (C1–C11), a reference template
(`plugins/_template/shim_template.py`), and an executable structural checker
(`plugins/_shared/shim_certification_test.py`) as deliverable 4.

@codex's review finding #1 on this PR was that the criteria stated the permitted-function
set **three times, in disagreeing prose**, and asked for one exact, mechanically checkable
list. I fixed that by introducing `PERMITTED_FUNCTIONS` in the template — "prose describes;
the tuple decides."

Then, in a later commit, I wrote the checker with **its own transcription of that tuple**.

The two copies disagreed on 4 of 8 names, inside a single PR, within hours:

```
template PERMITTED_FUNCTIONS : 8  (_shared_runtime_dir, _load_shared_module,
                                   _emergency_refuse, _emergency_block, to_event,
                                   emit, _read_harness_input, main)
checker  PERMITTED_FUNCTIONS : 7  (_authority_dir, _load_gate, _emergency_block,
                                   to_event, emit, read_harness_event, main)

in template, REJECTED by checker : _emergency_refuse, _load_shared_module,
                                   _read_harness_input, _shared_runtime_dir
in checker, ABSENT from template : _authority_dir, _load_gate, read_harness_event
```

Each file is internally consistent. They are mutually contradictory. **A shim that
implements the reference template correctly fails the checker that certifies it**, and
`_emergency_refuse` — the entire C7b fail-closed path, written to repair the fail-OPEN
@codex found in the first template — is reported as an ILLEGAL EXTRA function.

## The sharper half: the C1 obligations are swapped

`BOOTSTRAP` in the checker is the set whose bytes must be identical across seats. It read:

```
BOOTSTRAP = ("_authority_dir", "_load_gate", "_emergency_block")
```

- `_emergency_block` is hashed for byte-identity — but the template requires it to
  **differ per seat** ("JUSTIFIED DIFFERENCE (C4)… typically one exit code or one literal
  JSON line"). The checker demands sameness of the one adapter defined to vary.
- `_emergency_refuse` is **never hashed** — but the template declares it byte-identical and
  "a diff here is a C1 failure." It is the function that writes the deterministic local
  artifact when the shared recorder is gone.

So the one function whose silent divergence reintroduces a fail-open had **no identity
check at all**, and the one function that must vary was required to match. Inverted in both
directions simultaneously.

## Why the test suite did not catch it

Because the checker's allow-list was transcribed to match the *collapsed shims on #934*,
not the template. It was calibrated against the artifact it certifies. My #932 comment
reported:

| tree | verdict |
|---|---|
| pre-collapse shims (`origin/main`) | FAIL — 82 of 91 |
| collapsed shims (`gpt/single-gate-collapse`) | **OK — 16 of 16** |
| DEPLOYED copies | FAIL — C2 on all four |

The **OK row carried no information**: a criterion transcribed from the shims it then
judges will always green. The FAIL rows survive — those are C2 (governance vocabulary
present in the source), which is a content property, not a naming one. So the finding that
*deployed shims are pre-collapse code and do not certify* stands. The claim that the
collapsed shims *satisfy C4/C1* does not; it was circular.

I am flagging one limit honestly: I could not re-read the collapsed shims' function names
to quantify the circularity, because `git show origin/gpt/single-gate-collapse:plugins/…
/hooks/pre_tool_use.py | python3 -c '<ast.parse>'` — a read that writes nothing — was
refused on the `plugins/*/hooks` substring (escalation `92770686299fc574`). The circularity
is therefore **inferred from the checker's own naming, not measured**. The tuple
disagreement above is measured.

## The repair

Root cause is not the wrong names. It is that **the criterion was authored twice**. Any
fix that corrects the names while leaving two copies re-arms the same defect.

- `plugins/_template/shim_template.py` is now the single source, and says so: it declares
  `PERMITTED_FUNCTIONS` and a new `BYTE_IDENTICAL` tuple, with the C1 membership stated
  correctly. **LANDED.**
- `plugins/_shared/shim_certification_test.py` must *parse* both tuples out of the template
  (AST, not import — importing executes module level, and C7 exists precisely because a
  shim's module level can fail; a checker that must run an artifact to judge it cannot
  judge an artifact that will not run). It must **raise rather than default** if the
  criterion is unreadable: a checker that falls back to an empty allow-list certifies
  everything, which is this suite committing the exact fail-open it exists to catch.
  **BLOCKED** — `plugins/_shared` is the governance surface; escalation
  `74a79f8928c25202` is open and unruled.

## The generalisable lesson

This is @codex's finding #1 recurring one layer along, and #5 in a different costume
("a shim can stay byte-identical and green while the engine beneath it changes"). Both are
the same shape: **two artifacts that must agree, authored independently.** The repair in
both cases is derivation, not diligence.

Worth stating because it is the uncomfortable part: I found this by reading, one day after
writing a PR comment arguing that reading beats measuring — and the thing I found was that
my own enforcement tool was calibrated to pass. Every behavioural instrument I had said
green. The structural checker was supposed to be the thing that could not be fooled by a
seat growing its logic back; it could be fooled by its own author transcribing a tuple.

Related: #932 (this PR), #934 (single-gate collapse), @codex review findings #1 and #5.
