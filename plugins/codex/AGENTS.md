# Hestia member context for Codex

This file is a public installation template. It describes the mechanism; it does not confer
membership, trust, repository scope, or authority. An operator may extend the installed copy with
local context outside the public Hestia checkout.

## What Hestia does

Hestia records disclosed member activity and consults a local policy authority before governed
acts. The gate and observation hooks are visible source, not hidden surveillance.

## Authority and scope

- The shipped identity seed grants no repository or filesystem scope.
- Durable grants and the society floor are operator decisions stored in the encrypted Hestia
  vault and served as versioned runtime policy.
- A local identity file is continuity state and a bounded policy replica; it is not an authority
  a member may widen by editing.
- If an act needs scope you do not hold, request it through the configured governance surface.
- A denial is feedback. Do not repeat the same act unchanged or route around it.

## Harness facts

Codex supports lifecycle hooks when `codex_hooks` is enabled. Hestia uses those hooks for disclosed
observation and policy consultation. Filesystem sandboxing remains a separate structural boundary;
operators should configure it for the installation's risk model.

## Local continuity

The installed identity normally lives at `~/.codex/hestia-instance/identity.json`. Session-end
hydration updates bounded session metadata and the state block below. Local relationships,
milestones, and operating context belong in an operator-controlled overlay, not this repository.

<!-- HESTIA:STATE:BEGIN -->
## Local state (written after installation)

No local session state exists in the public template.
<!-- HESTIA:STATE:END -->
