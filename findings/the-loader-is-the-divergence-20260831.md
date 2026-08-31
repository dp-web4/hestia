# The differential drives the predicate; the divergence lives in the loader

**2026-08-31 · claude-code on CBP · PR #739 · escalation `7659ed7f114d2eac` (approved, claimed)**

## What was owed

My review of #739 claimed, from a *static* read of each seat's `sys.path` setup, that
`SEAT DISAGREEMENTS: none` measures byte-identity rather than agreement — and that codex's
loader is the one genuinely per-seat thing the differential does not drive. I flagged the
instrument as weak and said the dynamic confirmation was owed and blocked on a gate refusal.

The operator approved `7659ed7f114d2eac` at `1788156773`. This is the confirmation, plus what
running it turned up that the static read had wrong.

## 1. The dynamic read confirms the static one

Loading each seat hook and asking where its `_closure_classify` came from:

| seat | resolved file | sha256 |
|---|---|---|
| claude-code | `~/.hestia/shared/…` (installed) | `f648556d4cd1b46d` |
| codex | `…/hestia/plugins/_shared/…` (**shared working tree**) | `f648556d4cd1b46d` |
| kimi | `~/.hestia/shared/…` (installed) | `f648556d4cd1b46d` |

One engine, **two distinct files on disk**, three loaders. A disagreement between seats is
possible iff those two files differ; today they do not, so the differential's `none` is
tautological, exactly as claimed.

## 2. The static read had the mechanism wrong

I wrote that codex "resolves the repo working tree and never the installed copy." The *reason*
was wrong, and finding it required running the entry point rather than the hunk.

Codex's invoked hook is `~/.codex/hooks/pre_tool_use.py`, not the repo copy. (It happens to be
byte-identical — `75698b0e…` — so the measurement above is sound, but that is luck, and the
differential loads the repo copy for every seat without checking.)

That hook does not *pin* the shared dir, it **searches** two candidates:

1. `~/.codex/_shared` — this directory **exists**, so `os.path.isdir` passes and it is inserted
   at `sys.path[0]`. It contains only `hestia_gate_mechanism.py`.
2. `$HESTIA_WORKSPACE/hestia/plugins/_shared` — the live shared working tree.

The closure import therefore falls through candidate 1 and lands on candidate 2. Codex reads the
shared tree not by design but because a directory exists without the module in it. Codex's gate
engine is a function of **whatever branch that tree has checked out**.

## 3. The divergence is live, and it has a demonstrated bad state

54 copies of the engine sit on this disk in **three** distinct versions:

| sha256 | copies | example |
|---|---|---|
| `f648556d4cd1b46d` | 51 | installed + `main` + this tree |
| `b5bd35e70f644970` | 2 | `.wt/528-turnover` |
| `5417d588ff73fec2` | 1 | `codex/2584-chain-window-cutover` (**unmerged**) |

`5417d588` is 186 lines behind `main` and is missing the #463/#496 tokenizer fixes. It is not
cosmetically stale — it is behaviourally regressed, and it is convicted by the regression cases
its own successor's comments cite:

```
                                     verdict   write targets seen
f648556d (installed / main)
  positive control                   write     1
  #463 newline-as-separator          write     1
  #496 fused blank line              write     1
5417d588 (codex/2584 tip)
  positive control                   write     1
  #463 newline-as-separator          read      0
  #496 fused blank line              read      0
```

The positive control still denies, so the engine is not broken; the write behind a newline is
simply **invisible** to it.

## 4. Why this is a seat disagreement the differential cannot see

Codex is pinned to a fixed `HESTIA_WORKSPACE`, so `.wt/*` is never on its path — the regressed
bytes are *not* reachable through a worktree, and I am not claiming they are. They are reachable
the ordinary way: `git checkout codex/2584-chain-window-cutover` in the shared tree, an unmerged
live branch, in a tree this fleet checks out routinely (a checkout there re-deploys the mesh).

After that one checkout, codex classifies those writes `read` while claude-code and kimi — still
reading the installed `f648556d` — correctly deny. **That is a real, reachable seat disagreement,
and #739's differential reports `none` for it**, because it samples one instant of a predicate
and never drives the loader that chooses which predicate runs.

## 5. What this changes for #739

Nothing in the PR's argument, and one thing in its instrument.

The argument holds and is now dynamically confirmed: the seven agreed-but-wrong cases are one
engine wrong seven times, deduplication cannot close them, and the corpus is the spec.

The instrument should not be cited as a four-seat behavioural acceptance test. It compares a
shared predicate under identical inputs. The two things that are actually per-seat — the
**loader** (this finding) and the **extraction domain** (#734) — are both outside it. A
differential that drove the loader would fail on a checkout the current one passes.

The cheap fix for the specific hazard is to make candidate 1 real: putting the engine in
`~/.codex/_shared` alongside `hestia_gate_mechanism.py` would pin codex to an installed copy
like the other two seats, and the loader would stop being branch-dependent. That is a
suggestion, not part of this review.

## 6. The escalation

`read.for-loop` fired at the reviewer during the review of the PR about `read.for-loop` — third
in nine hours. codex dissented correctly in 242s and prescribed "recast it as a read-only
inspection," which the act already was and which the law scores below plain compliance. The
operator broke the deadlock 661s later. The act, run verbatim under the grant, was read-only and
produced §1 above. **Peer review detected the FP class in four minutes and had no verb that
released it; only a human did.**

Driver: `tools/worktree_engine_divergence_739.py` (read-only; imports engines, writes
nothing).
