# Held governed patch for #1247

`held/README.md` and `held/574426d6…patch` are #1239's. This file is #1247's.

This keeps the **governed half** of #1247 as one digest-named patch, so the reviewed bytes live in
the repo and not only in a scratch directory. **It is not applied.** Applying it changes files the
gate governs (the shared closure, the common gate, the core's canonical list, and their published
copies under `hooks-gt/`), so it lands through the gate's escalation path, as one `git apply`,
after review.

| file | sha256 |
|---|---|
| `e2b891c22db82f17b2577250f9bfc187c09a3704eee8d6e384dfcf41b4071c32.patch` | `e2b891c22db82f17b2577250f9bfc187c09a3704eee8d6e384dfcf41b4071c32` |

Verify before applying: `sha256sum held/e2b891c2*.patch` must print the name.

## Order and base

1. #1239's held patch first: `held/574426d6772d36bf2630cb94bf4b82d1b1d2b07a0db18651d9808158ca2d825b.patch`.
2. Then this one.

The base this patch is built against and checked on (`git apply --check` passes) is
`1d82846e1ce7446ec5d1aee2f55f0d0f0ca623b2`. That commit is #1239's head `d6f23be` (current main
`d2b1f7c` merged in) plus #1239's held patch 574426d6 applied byte-identical. In other words:
main + #1239 + #1239's held patch. The patch is `git diff 1d82846 <this merge>`, with `held/`
excluded.

## What it is

#1247 re-stacked on #1239: 18 files changed, 2192 insertions(+), 85 deletions(-).

- **Declared surface.** Every member's install declaration (dest, gate entry, registration) is
  derived into the closure.
- **Executed surface.** What each seat's harness registration actually runs is governed, and a
  write to a registered gate entry escalates under `registered-gate-entry`.
- **Location pricing, on #1239's `resolved_targets`.** Each write verdict carries the location it
  lands at, and the gate sends that location for every target. The daemon matches each target
  against the declared member gate-entry locations, after lexical normalisation and with #1239's
  glob rule. A registered entry among the targets adds the `registered-gate-entry` token.
- Tests, the hooks-gt republish, and the CI step for the real-daemon test.

## What it supersedes

`4b5c6db572cd58b8ff8af2103c9ffcea76389616ab7f82a92a949f4f73c0e620.patch`, at #1247's earlier head
`1783b84`. That was built on #1239's earlier head plus its earlier held patch, and it carried a
second every-target implementation (`b5611ca`, `6db885d`). The re-stack drops that implementation
in favour of #1239's. The file is gone from this tree and stays in history at `c490729`.
