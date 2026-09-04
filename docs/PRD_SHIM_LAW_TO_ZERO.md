# PRD: per-seat law to zero, held there by the vault

Status: DRAFT. Target: `LAW-DEBT` rows in `plugins/_shared/SHIM_LEDGER.md` reach 0 and cannot
return without an operator ratification recorded outside the repo.

Depends on #844 (the ledger). Motivated by #916 (the live instance).

## 1. Measurement, 2026-09-03

`tools/shim_ledger_check.py` over the four installed seats:

| seat | shim functions | LAW-DEBT functions | law sloc in the shim |
|---|---|---|---|
| claude-code | 30 | 16 | 819 |
| codex | 17 | 8 | 508 |
| gemini | 18 | 8 | 216 |
| kimi | 15 | 7 | 404 |
| total | 80 | 39 | 1947 |

1,947 lines of law live in four copies. The ledger's own classes say what is legitimate in a
shim: `event-shape`, `refusal-channel`, `registration`, `identity`, `launch`. `LAW-DEBT` is the
class that names everything else, and its target is 0.

## 2. What the collapse actually covered

The shared engine owns the DECISION. It does not own the CONSEQUENCES of a decision.

| seat | routes through shared `evaluate()` | witnesses its own refusals |
|---|---|---|
| claude-code | yes | no |
| codex | yes | yes |
| kimi | yes | yes |
| gemini | **no** | no |

`_deny` in `plugins/_shared/hestia_gate_core.py:443` is a pure `Verdict` constructor. It records
nothing. Every seat is then individually responsible for witnessing, rendering the refusal, and
choosing an exit path. Two seats of four never witness, which is #916.

The shared core's own module docstring already identified this: of the functions compared across
seats, `deny` is "THE REAL ONE" that diverged. The divergence appeared exactly where the collapse
stopped.

gemini is a separate and larger case: with 0 `evaluate()` call sites it is not on the common gate
for deciding either. Its `_gate` (110 sloc, `LAW-DEBT`) is a parallel decision engine.

## 3. Why wiring the two missing seats is the wrong fix

#916 as filed asks for the recorder to be wired into claude-code and gemini. That closes the
current instance and leaves the mechanism intact: four hand-maintained copies of a law line, two
of which happened to be right. The next line to diverge costs the same discovery again, and the
discovery took a decoy to notice at all (a seat contributing 199 refusal rows from a different
layer while contributing zero from its gate).

A law line that must be remembered in four places is not enforced. It is observed.

## 4. Requirements

**R1. Consequences move into the shared engine.** Witnessing, refusal rendering, and exit
selection belong behind one shared entry point, so a shim cannot decline them by omission. The
funnel already exists: `evaluate()` at `hestia_gate_core.py:959`. Three seats reach it today.

**R2. A shim may not define a function classed `LAW-DEBT`.** The permitted classes remain the
five harness-unique ones. A new `LAW-DEBT` row is a build failure, not a ledger entry.

**R3. gemini joins the common gate.** 0 `evaluate()` call sites is a distinct precondition and is
sequenced first, because R1 delivers nothing to a seat that never calls the shared path.

**R4. The expectation lives where the governed party cannot write it.** Today
`SHIM_LEDGER.md` and `shim_ledger_check.py` are both in the repo and both describe the repo. The
vault already holds this shape for gate bytes (`vault::gate_integrity`, operator-only
`set_gate_expectations`). The law inventory needs the same treatment and a different record: a
per-seat ceiling, not a whole-file hash. A file hash cannot ratchet, because every legitimate
shim edit invalidates it.

**R5. The ceiling is monotone downward.** The vault holds, per seat, the maximum number of
`LAW-DEBT` functions and law sloc permitted. Lowering it is a normal merge. Raising it requires
an operator ratification recorded in the vault with a reason, exactly as gate bytes are ratified.

**R6. The check runs against the INSTALLED shims, at runtime.** `shim_ledger_check.py` resolves
`repo_root` and therefore certifies the repo. The daemon enforces the installed copies. Measured
2026-09-03 these agree byte for byte (`e19aed53f3135b19`, 1756 lines, both), so this is an unbound
invariant rather than a present divergence. R6 binds it: the daemon verifies installed shims
against the vault ceiling on startup and on deploy.

**R7. A miswire is flagged and logged, not merely returned.** A seat exceeding its ceiling emits a
ledger row naming the seat, the function, and the class, on the same surface as any other
governance event. Silence is not a pass.

## 5. Acceptance

1. `LAW-DEBT` count is 0 for all four seats, and `shim_ledger_check.py` fails on any new row.
2. Removing the witness call from any single shim changes nothing observable, because no shim has
   one.
3. gemini has at least one `evaluate()` call site and no parallel decision path.
4. The vault holds a per-seat ceiling; editing the repo ledger alone cannot raise it.
5. A seat installed above its ceiling produces a miswire ledger row at daemon startup. Verified by
   installing one deliberately, not by reading code.
6. Acceptance 5 is checked with the arm that FAILS on an unmodified tree, so a check that cannot
   fire is not mistaken for a check that passed.

## 6. Sequencing

1. R3, gemini onto `evaluate()`. Precondition for everything else.
2. R1, consequences behind the shared entry point. This closes #916 structurally and is the
   largest single reduction in `LAW-DEBT`.
3. R4 and R5, the vault ceiling, seeded at the post-R1 counts so the ratchet starts where the
   work ended.
4. R6 and R7, runtime verification against installed shims.
5. R2 as the closing gate, once the counts are low enough that the rule is achievable.
