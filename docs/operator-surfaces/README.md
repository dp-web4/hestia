# Operator surfaces — the canonical spec

**`spec.json` here is the ground truth for what an operator can see and do.** The daemon's web
dashboard (`core/src/server/dashboard/index.html`) and the desktop app (`app/`) are two
*implementations* of it, and `tools/operator_surfaces_spec_test.py` checks both against it in CI.

dp, 2026-09-28: *"there needs to be a canonical ground-truth UI and functionality spec, that
evolves, and then dashboard and app versions can be checked against it."*

## Why it exists

On 2026-09-28, #1132 added gate ratification to the desktop app only. The operator, who uses the
web dashboard and has no app build, could not find it. An audit that night found the two surfaces
had drifted in both directions: the dashboard carried ~40 capabilities and the app 14. It also found
that several of the daemon's widest-reach routes had no surface at all. Nothing failed, because
nothing said what either surface was supposed to hold. The PRDs
(`PRD_APP.md`, `PRD_APP_GOVERNING_SURFACES.md`) state the principle ("one engine, several views");
this file makes it checkable.

## What is in it

- **`capabilities`**: every operator act or view. Each lists:
  - its daemon `routes` (`METHOD /path`, exactly as in the router);
  - `kind` (read/write) and `risk`;
  - its `place` (Me / Communities / Activity, `PRD_APP.md` §4.1);
  - the `rules` it must honour;
  - for each surface, an obligation: **`required`** (must be there), **`planned`** (not yet, with
    the reason), or **`excluded`** (must NOT be there, with the reason).
- **`rules`**: the shared semantics every surface implements the same way (reason to permit, 409
  means already decided, bound to the rendered evidence, UNKNOWN is never fine, member ids, confirm
  irreversible acts, no secret values, signed-in only). They are cited by id and reviewed in PRs.
  They are not pattern-matched.
- **`unsurfaced`**: daemon routes that deliberately have no UI, each with the reason. Examples:
  ungovern, until it is hardened; the scope floor; wallet endpoints.
- **`known_gaps`**: `required` pairs that are missing today. **This list only shrinks.** Closing
  a gap without removing it from here fails CI, so the spec cannot silently go stale.

## What the checker fails on

1. A daemon route that is in no capability and not in `unsurfaced`. This is exactly the #1132
   shape: a route landed and no surface was asked for.
2. A spec route that no longer exists in the router.
3. A surface missing a capability it is `required` to carry (unless listed in `known_gaps`).
   Also, a surface calling a capability it is `excluded` from.
4. A gap that has been closed but is still listed in `known_gaps`.

`python3 tools/operator_surfaces_spec_test.py --matrix` prints the capability × surface table.
`--discover` prints what each surface actually calls.

## How it evolves

- **A new daemon route**: add it to a capability, with each surface's obligation, or to
  `unsurfaced` with a reason, in the same PR as the route.
- **A new screen or control**: if the capability exists, flip that surface to `required`, and
  remove it from `known_gaps` if it was there. If it doesn't exist, add the capability first.
- **A new shared behaviour** (a new confirmation rule, a new error convention): add it to
  `rules`, and cite it from the capabilities it governs.
- **Removing something**: remove the capability, and say in the PR who relied on it.
- Bump `version` when the meaning of a field changes, not for every capability edit.

The spec leads, and the surfaces follow. When they disagree, the surface is the thing to fix,
unless the PR changing the spec says otherwise and why.
