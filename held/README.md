# Held governed patch for #1247

This directory keeps the **governed half** of #1247 as one digest-named patch, so the reviewed bytes
live in the repo and not only in a scratch directory. **It is not applied.** Applying it changes
files the gate governs (the shared closure, the common gate, their published copies under
`hooks-gt/`), so it lands through the gate's escalation path, as one `git apply`, after review.

| file | sha256 |
|---|---|
| `4b5c6db572cd58b8ff8af2103c9ffcea76389616ab7f82a92a949f4f73c0e620.patch` | `4b5c6db572cd58b8ff8af2103c9ffcea76389616ab7f82a92a949f4f73c0e620` |

Verify before applying: `sha256sum held/4b5c6db5*.patch` must print the name.

## What it is

The whole of #1247's change at branch head `1783b840e0247365ec3e60b72966cd10012d4cbf`:
21 files changed, 2368 insertions(+), 99 deletions(-).

- every member's declared install surface derived into the closure
- the executed surface, governed from what each seat's harness registration actually runs
- location pricing for member gate entries, and the `registered-gate-entry` marker
- tests, the hooks-gt republish, and the CI step for the real-daemon test

## What it applies to

`git apply --check` passes on this base: main at `efea915`, merged with the #1239 stack at
`4ea38827df422f806f3a5985b12da78f440de401`. That commit is #1239's head `8fe646e` plus #1239's held
producer patch `d39341b1…`, carried byte-identical on this branch. The base itself is
`git merge-tree --write-tree efea915 4ea3882`.

It does **not** apply to current main as-is. The #1239 stack no longer merges cleanly with current
main; only the `hooks-gt` manifests conflict, and those are regenerated.

## Status: superseded once #1247 is re-stacked

#1239 is being rebuilt and rebased onto current main, and its "price every target" implementation
is the one that survives. When #1247 is re-stacked onto #1239's new head, this branch drops its own
every-target commits (`b5611ca`, `6db885d`) and adapts to #1239's `resolved_targets` list. This
patch is then replaced by a new one under a new digest, recorded here. Until then, this file is
the reviewed record of the governed half at `1783b840`.
