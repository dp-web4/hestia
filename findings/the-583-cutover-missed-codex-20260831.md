# The #583 shared-dir cutover landed on 2 of 3 seats — and my own proposed remedy was inert

**Date:** 2026-08-31 · **Seat:** claude-code (CBP) · **Driver:** `tools/codex_loader_cutover_probe.py`

## Claim

`#583` replaced the per-vendor shared-engine search with one fleet path,
`$HESTIA_HOME/shared`. It landed on **claude-code** and **kimi**. It did **not** land on
**codex**, which still runs the pre-cutover loader — on `main`, deployed, and executing
right now.

Two consequences, one of them live and unconditional:

1. **codex binds a `hestia_gate_mechanism` that is 8 days stale.** Not contingent on any
   checkout. Every codex wake, today.
2. **codex binds its closure and core from the live shared working tree**, so those two
   are a function of whatever branch that tree has checked out.

And the finding that cost me the most: **the remedy I recommended last wake does not
work.** See "What I got wrong."

## Measured

Three arms, all in the driver. Run:
`HESTIA_WORKSPACE=/mnt/c/exe/projects/ai-agents python3 tools/codex_loader_cutover_probe.py`

### Arm 1 — static: who is cut over?

Counting the cutover marker `_HESTIA_HOME` in each seat's `PreToolUse` hook:

| seat | deployed | canonical | same bytes? |
|---|---|---|---|
| claude-code | 5 | 5 | yes |
| kimi | 2 | 2 | yes |
| **codex** | **0** | **0** | yes |

`0` is the pre-cutover loader. Deployed and canonical are byte-identical for all three
(`75698b0e153e55cc…` for codex), and `main` carries the same bytes — so this is **not** a
deployment lag. The source was never changed. *Shipped ≠ in force* does not apply here;
nothing was shipped.

### Arm 2 — vintage: which bytes sit where?

| module | verdict |
|---|---|
| `hestia_gate_mechanism.py` | **DIVERGE (2 versions)** — `93e02c180e846b27` installed + live tree (Aug 25) vs `faa5178853c8d124` in `~/.codex/_shared` (Aug 17) |
| `hestia_gate_core.py` | AGREE `9f33c9ca10a80ed8` — **absent** from `~/.codex/_shared` |
| `hestia_governance_closure.py` | AGREE `f648556d4cd1b46d` — **absent** from `~/.codex/_shared` |

The two `AGREE` rows are a **load-bearing accident**, not a property. They agree because
the shared tree currently sits on a branch whose bytes match `main`. A checkout changes
them; nothing in the loader prevents it.

### Arm 3 — driven: what does the real loader bind?

Importing codex's actual hook (it has a `__main__` guard) and reading resolved `__file__`:

```
sys.path added at import: ['<workspace>/hestia/plugins/_shared']
hestia_governance_closure -> <workspace>/hestia/plugins/_shared/hestia_governance_closure.py
hestia_gate_core          -> <workspace>/hestia/plugins/_shared/hestia_gate_core.py
hestia_gate_mechanism     -> /home/dp/.codex/_shared/hestia_gate_mechanism.py
```

Exactly **one** directory goes on `sys.path` at import: the live working tree.
`~/.codex/_shared` is never added there — yet the mechanism still resolves out of it.

## Mechanism — two blocks, two different bugs

codex's hook has two `sys.path` search blocks that disagree with each other.

**Block B** (module level, binds closure + core) searches, in order:

```python
os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  + "/_shared"
os.path.join(WORKSPACE, "hestia", "plugins", "_shared")
```

Three `dirname`s from `~/.codex/hooks/pre_tool_use.py` is **`/home/dp/_shared`** — which
does not exist (verified). It should be two. So candidate 1 is dead, and the closure and
core load from the working tree. **The per-vendor pin never engages at all.**

**Block A** (inside a lazily-called function, binds the mechanism) searches the *opposite*
order — working tree first, `~/.codex/_shared` second — with two `dirname`s, which is
correct. But it `sys.path.insert(0, …)` in a loop, so the **last** candidate inserted ends
up at position 0. Iterating (tree, codex_shared) and inserting each at 0 leaves
`~/.codex/_shared` winning. That directory holds exactly one module, frozen Aug 17, and
nothing redeploys it.

So codex runs a **split-vintage engine**: mechanism from a frozen private copy, closure and
core from a live branch. Neither half is the installed fleet copy the other two seats use.

## What I got wrong

My memory recorded this as: *"`~/.codex/_shared` EXISTS (so `isdir` passes,
`sys.path[0]`) but holds no closure module → the import falls through onto the live tree."*

**The conclusion was right and the mechanism was wrong.** `~/.codex/_shared` is not on
`sys.path` when the closure is imported. The fall-through is caused by the off-by-one
`dirname`, not by a missing file.

That distinction is the whole finding, because the remedy I recommended last wake —
*"put `hestia_governance_closure.py` in `~/.codex/_shared`; candidate 1 becomes real"* —
**is inert.** The file would sit there unread and the closure would still come from the
working tree. I would have shipped a no-op and recorded the loader as pinned.

Worse is the near-miss: had someone "completed" the fix by also correcting the `dirname`,
it would have pinned closure and core to a directory with the same no-redeploy property
that already froze the mechanism at Aug 17 — converting a *branch-dependence* bug into a
*silent-staleness* bug, and reporting success either way.

This is the second time in two wakes that running the entry point corrected a mechanism I
had read statically and gotten wrong. The static read is not converging on the mechanism;
it is converging on a plausible story that predicts the same observation.

## Remedy

**Not** a file copy. Apply the #583 cutover to codex's hook — the same resolution the
other two seats already carry:

```python
_HESTIA_HOME = os.environ.get("HESTIA_HOME") or os.path.join(os.path.expanduser("~"), ".hestia")
_SHARED_DIR  = os.environ.get("HESTIA_SHARED_DIR") or os.path.join(_HESTIA_HOME, "shared")
_LEGACY_SHARED_DIR = os.path.join(WORKSPACE, "hestia", "plugins", "_shared")
if not os.path.isdir(_SHARED_DIR) and os.path.isdir(_LEGACY_SHARED_DIR):
    _SHARED_DIR = _LEGACY_SHARED_DIR
```

— used for **all three** modules, replacing both blocks, so the mechanism stops resolving
separately from the closure. That deletes the off-by-one, the loop-inversion, and the
split vintage in one change, and lands codex on the identical installed bytes the other
two seats load. It is the "one gate, thin shims" architecture applied to the surface that
was left out of it.

This touches the governance closure, so it is a self-protection write and needs human
approval. Proposed here rather than attempted.

## Why this matters to the current direction

The gate-consolidation work is aimed at the **predicate**. The predicate is the part that
has already converged — `hestia_gate_core` and `hestia_governance_closure` agree byte-for-byte
across every location that has them. What has *not* converged is the **loader**: which bytes
a seat binds, and whether that answer is stable across a `git checkout`. A differential that
samples one instant of a shared predicate reports `none` here, and it is right about the
predicate and blind to the seat disagreement.

Two seats out of three agreeing is also not agreement — it is one installed copy read twice.
The third seat reads two other things.
