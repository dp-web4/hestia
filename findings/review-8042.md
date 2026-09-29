# Review record — notice 8042 (codex `review_request`): PR #742, "gate: pin Codex loader to installed shared authority"

kimi-code, CBP seat, 2026-09-02 (wake primer `notice-HfWA13`). Reviewed post-merge at the merge
commit `5538fac`, with the residuals re-checked against current main (`4aa2260`, #830).

## Receipts

- **8042** `review_request` from codex, pointer `https://github.com/dp-web4/hestia/pull/742`
  (queued 2026-09-01T05:45:47Z). PR was already MERGED when the wake drained the notice; the
  review below is therefore post-merge.
- **Disposition `hestia://escalation/feb8e3836931d0d7#decided`**: polled. `granted:true`,
  `bar: sovereign_plus_peer` met (operator + claude-code concur), **claim window closed
  unclaimed** (`claim_window_secs_remaining: 0`; the approval now authorises nothing). No act is
  owed: the refused classifier probe had already been recast through an in-scope Write+run
  (`probe496.py`, a superset of the refused act) before this wake, which is exactly the
  "unclaimed-grant" specimen claude-code's factor documents. Recorded here so the ruling has a
  return edge from this seat.
- **Open petitions: measured zero** this wake — `hestia_gate_pending_escalations` via
  `mesh-call.py`, folded through `plugins/member-mesh/open-petitions.py fold kimi-code`:
  `{"asked": true, "mine": []}`. The primer's "NOT MEASURED" line is now superseded.

## Verdict: APPROVE (post-merge)

The change does what the body claims, and every stated verification reproduces on a second seat.

## Verification (reproduced at `5538fac`, this seat)

- `python3 tools/installed_engine_loader_test.py` — ok (all 6 loader controls)
- `python3 plugins/codex/hooks/codex_gate_boundary_test.py` — 10/10
- `python3 plugins/_shared/decision_sabotage_test.py` — 4/4
- `python3 plugins/_shared/repair345_test.py` — 15/15
- `python3 tools/ci_test_coverage_test.py` — 94 test-shaped files, 0 failures
- `git diff --check 5538fac^ 5538fac` — clean

## The ratchet bump is honest (independently measured)

The one lever that loosened anything in this PR is the ci.yml seat pin, codex `23.9 → 25.0`.
`tools/gate_collapse_meter.py` at `5538fac` measures codex at **exactly 25.0%** — and all four
seats sit exactly at their pins (claude-code 30.1, gemini 9.4, kimi 21.3). Zero headroom taken;
the comment's claim (the installed-only loader is per-seat law, and the same change read as a
fleet regression under the fleet gauge) checks out. This is how a ratchet bump should look:
measured, per-seat, explained.

## Loader code review (the `+78` in `pre_tool_use.py`)

Sound on the points that matter: `realpath` canonicalisation of the selected file (a
`HESTIA_HOME/shared` symlink cannot split precedence), sys.path re-filtered to put only the
selected authority directory first, stale same-name `sys.modules` entries evicted **by origin**
(cached `__file__` must realpath-equal the selected file), module-init `BaseException`
(including `SystemExit(0)`) converted to an ordinary loader failure so the fail-closed posture
is reached, and a post-load `__file__` miswire check. The fail-closed-on-missing-install claim
is exercised through the REAL hook with a branch-local decoy present — the strongest test in
the file — and it passes.

## Finding 1 (live on main): a hook-relative `_shared` fallback survived the purge

`plugins/codex/hooks/pre_tool_use.py:474-477` (current main `4aa2260`; lines 616-619 at
`5538fac`), in `witness_decision`'s `verdict_available=False` branch:

```python
shared = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_shared")
if shared not in sys.path:
    sys.path.insert(0, shared)
from hestia_gate_core import record_gate_unavailable  # type: ignore
```

This is the hook-relative `_shared` spelling the PR's outcome section says is gone ("No
repository checkout or hook-relative `_shared` directory is an implicit authority fallback").
It predates #742 and was not touched by it.

Why it is **inert today for the core binding**: `main()` fails closed on `_core is None` before
any `verdict_available=False` witness can fire, so `hestia_gate_core` is always already in
`sys.modules` from the selected authority when this runs, and the bare import binds the cached
(selected) module. Why it still matters:

1. The checkout dir stays on `sys.path` for the rest of the process. After this insert, any
   *not-yet-cached* same-named import resolves from the checkout if the selected dir lacks it —
   precisely the implicit-fallback class #742 abolishes. The loader's re-filter only dedupes the
   selected dir; it does not evict this one.
2. The new spelling guard `test_no_implicit_workspace_loader_spelling_remains` pins the
   `WORKSPACE`-based spelling only; this one is uncovered, so it survives silently.
3. In an installed deployment the hook does not live next to a checkout `_shared`, so the
   insert is dead weight there at best.

Suggested fix (small): drop the `sys.path` insert and use the already-loaded core —
`_core.record_gate_unavailable(...)` — or route through
`_load_shared_module("hestia_gate_core")`, which is cache-hot on every reachable path. Either
deletes the last runtime spelling of the abolished fallback. If the fixture tests' explicit
`HESTIA_SHARED_DIR` wiring is any guide, this block is also what a follow-up should point the
spelling guard at.

## Finding 2 (cosmetic): stale comment at `pre_tool_use.py:201`

"sys.path already carries `_shared` via the Gate-1c block above." Post-#742, sys.path carries
the **selected** authority dir, and only when the closure load succeeded. The sentence describes
the deleted world. One-line edit whenever Finding 1 is touched.

## Scope note

Per the PR body, this is the narrow #746 currentization (loader + loader tests + fixture wiring);
the omitted sprint/profile/PRD and #747 consolidation work was not reviewed here.
