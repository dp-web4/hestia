# held: #1262 re-cut on main (critical-timeout protocol, canonical or MISWIRED)

kimi-code's #1262, round-2 head `d94149b3` (10-07), merged with main (`95d6d0b7`, re-cut on `2b3d0ca2`). **NOT applied.**
kimi-code handed the PR over on 10-26. Its commits are the change; this directory only re-cuts
it so it applies to today's main.

Patch: `held/9ee3fe6c1efdb3dc80ea11d7fa70ec03d143af08bcdf46cd2041e6409b6e56b9.patch` (re-cut 2026-10-27 on main `2b3d0ca2`, after #1412 moved the manifests; the sources are unchanged). Superseded: `held/565e424e….patch` (on `95d6d0b7`) (19 files:
the same set as #1262, sources plus the hooks-gt mirror and manifests).

## The conflicts, and how they were resolved

| file | #1262 side | main side | resolution |
|---|---|---|---|
| `plugins/_shared/hestia_single_gate.py` `_load_config` | three-value loader `(doc, how, dupes)` with identity-held duplicate marks | `(path, reader, mtime, size)` cache around a two-value loader | main's cache around #1262's loader. main's `registered_hooks` unpacks three values. The cached document keeps every marked object alive, so a mark's identity holds across cache hits |
| `plugins/{claude-code,codex,kimi}/hooks/hooks.json` | the canonical-or-MISWIRED `_timeout_contract` text | the older `_timeout_contract`, plus new `_disposition_reader` / `_member_mesh` keys | #1262's `_timeout_contract` plus main's new keys |

Everything else merged cleanly (`prep_1262.py` → `resolve_1262.py` → `mk_source_diff.py` →
`build_1262.py`).

## Nova's 10-07 HOLD was already answered at the round-2 head

The HOLD (07:42Z, on `f7f8aa9`) named two items. `08c01a3a` (07:55Z, 13 minutes later) fixes
both, but no comment announced it, so the PR read as stalled at `f7f8aa9`:

1. **Quote and backslash removal** (`./gate_'hook'.py` beside a longer exact binding):
   `_names_hook` now also tests each shell-normalized token. The exact binding stays strict on
   the raw spelling.
2. **`id()` reuse:** the mark holds `(obj, repeated)` and the lookup checks `mark[0] is obj`.

**Separation** (`run_decide.sh <main worktree> <build out dir> [gate]`, i.e. main's tree with the
build's neutral copies overlaid):
- re-cut gate: **PASS, 27 decide() contract tests (+ shim-parity 29x4)**;
- `f7f8aa9`'s gate: FAILS `p1-quoted-*` (4 rows), `json-agreeing-duplicate-*` (3) and
  `json-overwritten-objects-id-reuse-still-binds`, among others. Its other failures come from
  `f7f8aa9` predating main's later gate changes.

## Applying

Governed (plugins/_shared, hooks-gt): it needs dp's escalation. `git apply` of the patch on a
`main` worktree at `95d6d0b7`, then the test above unmodified. If main has moved, re-run
`build_1262.py <worktree> <out>`, which re-cuts offset-tolerantly or stops.
