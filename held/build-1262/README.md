# held: #1262 re-cut on main (critical-timeout protocol, canonical or MISWIRED)

kimi-code's #1262, round-2 head `d94149b3` (10-07), was previously merged for preparation
against historical main bases `95d6d0b7` and `2b3d0ca2`. **NOT applied.** kimi-code handed
the PR over on 10-26. This directory prepares held artifacts; it does not establish that any
particular artifact applies to current main or is authorized for application.

Patch (v5, 2026-11-03): `held/c7fb52e58eea95f8f5a04243b384bde431337487d63a848889061d0c65543459.patch`, built on `83f57eb8`. Same gate and shim bytes as v4; the four `_timeout_contract` template texts (and their hooks-gt copies) no longer claim the gate "always fails closed" before the harness kills it, but call the margin a designed budget whose installed delivery is unverified (Codex's 11-03 HOLD; Class T, #1489). SUPERSEDED v4: `held/a656f67d34b0976a9c0e892e480f2f809644d90735dea69d1b436e897c3395b4.patch`, the same builder re-run on main `83f57eb8` after #1469 (which changed `hestia_gate_mechanism.py` and the manifests; same 19 files, cache contract PASS). SUPERSEDED v3: `held/e612a448a1ac59da2381a9aee0cc72960dd7faa58b28a280c7f6d66df05f0aa9.patch`, cut by this builder (with Codex's cache repair, `7811c2ab`) on `827b3e7d` (v0.3.0), reproduced byte-identically by cbp-claude; no gate file changed between `827b3e7d` and main at the time of the cut. SUPERSEDED: `held/9ee3fe6c1efdb3dc80ea11d7fa70ec03d143af08bcdf46cd2041e6409b6e56b9.patch` (re-cut 2026-10-27 on main `2b3d0ca2`, after #1412 moved the manifests; the sources are unchanged). Superseded: `held/565e424e….patch` (on `95d6d0b7`) (19 files:
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

The v4 artifact named above was built on `83f57eb8`, not on the historical `95d6d0b7` base.
Before any proposed application, compare the target to the exact full build base and verify the
artifact digest, source, ground-truth closure and independent regression evidence. If the target
has moved, prepare and review a fresh artifact; an offset-tolerant build is not proof of behavioral
compatibility. The current v4 template wording also makes an unverified universal timing claim;
correct it and regenerate the artifact before requesting application. Obtain independent review,
passing exact-head checks and a new explicit operator decision bound to the exact candidate and
base. An earlier approval or a green build is not authorization for a different artifact. No
application instruction here grants permission to change governed sources or ground truth.

## Review-only cache experiment

The builder on the review branch additionally transforms the neutral gate candidate to read
each registration once and cache a parse only while the bytes are identical. It keeps one entry
per path and reader, and preserves duplicate-key evidence. This addresses the reported same-size,
same-mtime collision; it does **not** prove that the registration remains stable after the read.
The transform refuses source drift and does not edit the governed gate.

Against base `827b3e7da93b00321adc0e2c5253246457213b81`, two independent output directories
produced SHA-256 `e612a448a1ac59da2381a9aee0cc72960dd7faa58b28a280c7f6d66df05f0aa9`.
`cache_contract_test.py <base-worktree> <output>/sg_rev.py` tests equal metadata with changed
bytes, malformed replacement, one-read parsing, reader isolation and duplicate marks. Its
same-metadata arm fails against the prior candidate and passes against this one. These are
synthetic tests, not deployment evidence. The contract runner now propagates pipeline failures.

The output is a **held artifact**, not an applied patch: independent source, regression,
compatibility and exact-base reviews plus the applicable operator approval remain required.
Do not run the applying instructions above on the strength of this experiment.
