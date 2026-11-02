# held: #1347 gate half (read-only floor admission), re-cut on main 656b147e

**Patch:** `32c9f5f86ccb34ca96441d76a47060aa24aa9b7f1093a3d86f53d88d51816eba.patch`

It touches 9 files:
- `plugins/_shared/hestia_gate_core.py`
- `plugins/_shared/hestia_gate_mechanism.py`
- the hooks-gt copies of both
- the 5 manifests

**Not applied.** It needs an operator-approved escalation for the governed write, the same as the 2026-10-19 landing.

## What it is

This is the gate change Codex reviewed and dp approved on 2026-10-19. On the old branch it landed as `d6f4e0c2`:
- `hestia_gate_core.py` 28fcf12e, escalation `d0f489cc9a2d2f8c`
- `hestia_gate_mechanism.py` 5616d4a1, escalation `cbbdd0e325cd5fa6`

The hunks are unchanged. Only the base moved: main has had #1363, #1370 and #1377 since then. Each reviewed hunk applied exactly once to main's blobs, with no hand edits.

- **Mechanism:** passes a floor entry's `recursive` through, and maps `society_floor_read` into `in_scope_read`.
- **Core:** adds `AgentPolicy.read_scope`, parsed from `in_scope_read`.
  - `evaluate` admits a path under a read-only root only for a reader tool (`READ_ONLY_PATH_TOOLS`, pinned to the closure's reader list).
  - For a command, it admits only `READ_ONLY_ROOT_VERBS` = `cat head tail grep wc ls stat`, as bare verbs joined by `|` `&&` `||` `;`.
  - Any redirect, substitution, newline, background `&`, environment prefix or path-qualified verb is refused. This answers Codex's HOLD 28057.

## Why the gate needs nothing new for the floor-modes rework

The daemon now decides, per member, which floor entries a mode-blind gate may see (`StandingScopeStore::floor_for`):
- all-modes entries go to `society_floor`;
- narrowed entries that include read go to `society_floor_read`;
- everything else goes to `society_floor_withheld`, with a reason, including any entry that would override one of that member's narrowed grants.

The gate's read admission is unchanged. Per-mode admission against `grants_by_mode` / `floor_by_mode` is #1345 part B.

## Rebuild and measure

```
python3 -I held/build-1347/build_1347.py <hestia worktree at the base> <out dir>
```

The script asserts the two reviewed copies by sha256. It applies their hunks offset-tolerantly, emits hooks-gt through `tools/hooks_gt.emit_patch` with the sources served in memory, names the patch by its sha256, and verifies by re-applying it. **Re-run it if main moves before the apply.**

`held/build-1347/run_with_overlay.py <wt> <out dir | main> <test>` runs a gate test with the re-cut copies loaded under the module names. Nothing is written under a governed name.

**Results on 656b147e:**

| suite | re-cut | main |
|---|---|---|
| `held/build-1347/floor_read_only_test.py` (moves to `tools/` with the apply) | 8/8 | fails (no read admission) |
| mechanism | 34 | 34 |
| shell grammar | ok | ok |
| seat gate boundary | 17×4 | 17×4 |
| closure | 39 | 39 |
| cross-harness | 4/4 | 4/4 |
| shell-scope battery | 1434/0 | 1434/0 |
| decide contract | PASS 24 | PASS 24 |

## Ordering with #1375 (#1327)

Both patches rewrite `hestia_gate_core.py`. Whichever lands second re-runs its own build script over the new main:
- for #1327, `held/build-1327/build_v3.py` on #1375's branch;
- for this one, `build_1347.py`.

Neither needs re-deriving.

— cbp-claude

## Re-cut on #1327's applied gate — ccf1d585 (2026-10-24), the bytes applied

#1327 (hestia #1375) landed its gate half first (438f9394, escalation 88340f22e1b3e251), so this branch merged
that and `build_1347.py` re-cut the same reviewed hunks over it:
`ccf1d585071637cf5e341490c8b7e4589dc19ed52537f4a417870644a272879b.patch` (every hunk exactly once, verified in
memory). On the overlay: floor read 8/8, mechanism 34, grammar ok, boundary 17x4, closure 39, cross-harness 4/4,
battery 1434/0, decide contract PASS 25 (#1327's checks included). This is the patch the governed apply uses;
32c9f5f8 is superseded.

— cbp-claude
