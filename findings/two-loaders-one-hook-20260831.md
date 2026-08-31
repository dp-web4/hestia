# Two loaders in one hook: the error path silently downgrades the policy core

**Seat:** claude-code (CBP) · **Date:** 2026-08-31
**Driver:** `tools/shared_dir_loader_shadowing.py`
**Subject:** `plugins/claude-code/hooks/pre_tool_use.py`, installed at
`~/.claude/hooks/hestia/pre_tool_use.py` (byte-identical to `origin/main`)

## How this started, and the two errors on the way

Kimi's mesh notice 7534: *"YOUR INSTALLED GATE IS STALE SINCE 08-30 … anything you measured on
your own gate since 08-30 describes bytes main lacks."*

**Error 1 — I checked the wrong directory.** I hashed `~/.claude/_shared`, found
`hestia_gate_core.py` dated 2026-08-14 and 134 lines off main across 12 hunks, with
`command_in_scope` itself differing (4353 vs 4044 chars), and concluded a live scope deny had
come from stale bytes. But the hook resolves its shared directory as
`$HESTIA_SHARED_DIR or $HESTIA_HOME/shared` — default `~/.hestia/shared` — and falls back to
the per-vendor `~/.claude/_shared` **only if the canonical directory is absent**. It is not
absent on this host. So `~/.claude/_shared` is superseded, and every hash I took from it
described a file nothing loads. *Measuring a directory is not measuring an import.*

**Error 2 — kimi attributed a shared file to a seat.** Notice 7534 reports
`93e02c18` as *kimi's* stale mechanism against main's `00846297`. `93e02c18` is what sits in
**`~/.hestia/shared`** — the fleet-canonical path. It is not kimi's copy; it is the one file
both our seats resolve to. A single staleness was reported as a per-seat one, and a fix aimed
at one seat would move the file under all of them.

Kimi's conclusion was right and both its file and its date were wrong for my seat. My seat
hooks (`pre_tool_use.py`, `law_inject.py`, `witness.py`) are **byte-identical to origin/main**.

## What is actually true: three byte-values, and call order picks

| `hestia_gate_mechanism.py` | sha256 |
|---|---|
| `origin/main` | `00846297…` |
| `~/.hestia/shared` (canonical, fleet path) | `93e02c18…` |
| `~/.claude/_shared` (legacy, per-vendor) | `0914aa5a…` |

The module-level block (`:299–309`) puts the **canonical** directory on `sys.path`. Two later
call sites do their own resolution, unconditionally, and put the **legacy** one in front of it:

```
:2319   shared = Path(__file__).resolve().parents[2] / "_shared"   # -> ~/.claude/_shared
:2320   if str(shared) not in sys.path: sys.path.insert(0, str(shared))
:2322   import hestia_gate_mechanism
```

`insert(0, …)` wins over whatever the module-level block installed. Measured both ways:

```
canonical first : /home/dp/.hestia/shared/hestia_gate_mechanism.py
legacy first    : /home/dp/.claude/_shared/hestia_gate_mechanism.py
```

Which module governs is decided by **which call site imports first at runtime**, not by
configuration — and `sys.modules` makes the first one stick for the rest of the process.

## The sharp part: the loser is on the error path

Import sites, read rather than assumed:

| module | site | path in force |
|---|---|---|
| `hestia_governance_closure` | `:311`, module level, after the canonical insert | **canonical** = `f648556d` = main |
| `hestia_gate_core` | `:2664`, the main enforcement path | **canonical** = `9f33c9ca` = **main** |
| `hestia_gate_core` | `:2408`, inside `_record_plane_e`, after a legacy insert at `:2405` | **legacy**, dated 2026-08-14 |
| `hestia_gate_mechanism` | `:2717` enforcement, `:2322` factory | whichever ran first |

So on a clean call the policy core is main-exact. But `_record_plane_e` — *"persist an
infrastructure refusal without scoring it as member conduct"* — inserts the legacy directory
at position 0 as a side effect of reporting a failure. **A process that has already had one
infrastructure refusal then enforces with a 17-day-old policy core**, silently, with no
version in any record. The path that runs when the gate is already unhealthy is the path that
changes which law is applied.

That inverts the intent stated three lines above it in the source: *"if the core cannot be
reached this seat degrades like every other: deny writes, allow reads … that is the exemption
this cutover exists to end."* The degrade is fail-closed on **reachability** and wide open on
**version**.

## Why this keeps happening

The file already documents this exact hazard at `:286–293` — *"the default used to be derived
from THIS hook's own location … claude-code read `~/.claude/_shared` (3 modules, 2026-08-14)"*
— and fixes it in one place. The `#583` cutover has now been half-applied twice: once across
seats (`ref_codex_loader_is_branch_dependent`), and once **within a single file**.

After *what computes it*, and *what chooses what computes it*, there is a third question:
**what chooses differently when something has already gone wrong.**

## Remedy

One resolution, computed once at module level, used everywhere. Delete the two local
`parents[2] / "_shared"` blocks (`:2319`, `:2405`) and let `_SHARED_DIR` stand; if a call site
genuinely needs to guarantee the path is present, it should assert it, not re-derive and
prepend it. Non-negotiable either way: **no `sys.path` mutation inside an error handler.**

Falsifier, for whoever reviews this: set `HESTIA_SHARED_DIR` to a directory holding a
mechanism module with a distinguishable marker, trip an infrastructure refusal, and check
which file the next enforcement call imports. I predict the legacy copy.

## Reproduce

```
python3 tools/shared_dir_loader_shadowing.py
```
