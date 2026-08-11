# 0017 — The gate is the authority-bearing closure, not every file that bears its name

**Status:** proposed
**Date:** 2026-08-10
**Author:** claude-code (CBP), amended by GPT NOT-SAME review
**Resolves:** the self-development toll paid by inert governance source copies without reopening
measured write positions on the live gate (#261, #263, #301, #318).
**Uses:** deployment truth (registration != filename), #285 registration-derived install targets,
#294 deployment integrity, and the measured shared-core / installer / exemption-ledger gaps.

---

## 1. The friction

An agent silently changing the thing that governs its own next call is not governed. That is why
`gate-self-access` exists.

But the current rule also treats **any file bearing a governance name anywhere on disk** as though it
were already enforcing. A repo worktree copy of `pre_tool_use.py` therefore costs the same operator
approval as the copy the harness is actually executing. The result is that gate hardening itself
repeatedly needs a human in the edit loop.

That is the wrong place for the human. The operator should decide **what becomes law**, not approve
every keystroke in a draft that governs nothing yet.

The original draft of this decision found the right first discriminator:

> filename is not authority; the harness registration tells us which copy is invoked.

The NOT-SAME review found the second half:

> direct invocation is not the whole authority boundary either.

Hestia has already measured artifacts that are not hook entrypoints but can still change what governs:
registration settings, installers and install manifests, an imported shared policy core, and the
exemption ledger. Those are not inert merely because the harness does not invoke them directly.

So the distinction is not **invoked vs named**.

**The distinction is authority-bearing vs inert.**

## 2. The effective governance closure

`gate-self-access` protects the **effective governance closure** for the local governed member.
That closure has two protected classes and one deliberately unprotected class.

### Class A — live execution set

Artifacts whose current bytes can directly participate in a governance decision or its mandatory
accounting path:

- registered/invoked PreToolUse, PostToolUse, witness, and law hooks;
- realpath/symlink aliases of those artifacts;
- runtime policy modules imported/loaded by an invoked hook, including the shared policy core;
- any equivalent runtime dependency proven to participate in the decision path.

A write into Class A is self-access and remains refused/escalated.

### Class B — authority-mutation set

Artifacts that can change Class A, change which artifact belongs to Class A, or weaken the mechanism
that protects Class A without requiring a second content-bound governance decision:

- harness registration/config selecting the invoked hook;
- `deploy/install-members.sh` and equivalent installers;
- install manifests / `expects.json` fields that select what is installed or where;
- exemption / escape ledgers controlling what the self-protection rule ignores;
- deployment-authority artifacts if editing them can cause unaudited bytes to be accepted as current;
- any future artifact whose modification changes the live execution set or its protection semantics.

A write into Class B is also self-access. **Being one hop upstream does not remove authority.**

### Class C — inert source copies

Governance-named source that is proven outside Classes A and B is ordinary repository work.
Examples include a worktree `plugins/.../hooks/pre_tool_use.py` on a seat whose registered gate is an
installed copy elsewhere, provided that worktree file is not itself imported by the live gate and no
registration/installer rule makes the edit take effect without a later governed deploy.

Class C is governed like other consequential repo work:

**proposal -> NOT-SAME review -> merge -> governed deploy.**

It does not require a separate operator approval per source edit.

## 3. How membership is derived

Protection must be derived from facts, not filename conventions.

1. **Registration is the root of the live execution graph.** Resolve the member's actual registration
   using the canonical registration contract (`expects.json` + the shared resolver being extracted in
   #330), not a per-consumer table.
2. **Resolve aliases.** Compare real paths so a symlink does not create an unprotected spelling of the
   same enforcing artifact.
3. **Include runtime dependencies.** A shared core imported by an invoked shim is authority-bearing even
   though the harness never names it in registration.
4. **Include authority-mutation artifacts.** Registration, installer, manifest, and exemption surfaces
   remain protected explicitly or by a derived dependency relation.
5. **Unknown means protected.** If registration or dependency closure cannot be resolved confidently,
   governance-named writes retain today's strict treatment. Never infer inertness from missing evidence.

A filename may remain useful as a conservative fail-closed marker. It is not the source of authority.

## 4. Seat consequences

### CBP — installed gate

The registered `~/.claude/.../hestia/...` gate and its runtime dependencies remain protected.
A separate repo worktree copy that participates in neither Class A nor Class B becomes ordinary source.
Gate changes can therefore be authored and reviewed without a per-edit operator toll; deployment is the
point where the new policy becomes live and remains operator-governed.

### NOMAD / HUB — working-tree gate

If registration points directly into the worktree, that worktree is Class A. Editing it still trips
self-protection because source and enforcing artifact are the same object on that seat.

### Unregistered / unresolved seat

No registration is not permission. If the seat is genuinely unregistered, there may be no live Class A;
if the resolver cannot distinguish unregistered from unreadable/unparseable state, the rule fails closed.
The deployment audit must say which fact was actually observed (#312/#330).

## 5. Why deploy approval alone is not enough

The original draft argued that inert source can be safe because an operator later approves deployment.
That is true only if the artifacts controlling deployment have not themselves been silently changed.

Example:

1. member silently edits `install-members.sh` or the install manifest;
2. operator later approves "deploy";
3. modified installer places different bytes or a different target into force.

The later approval does not retroactively authorize the hidden upstream edit unless the approval is
content/act-bound to the exact deployment graph. Hestia does not yet have that guarantee universally.
Therefore installer/manifest/registration surfaces stay in Class B.

**Authority does not transfer through the word "deploy" any more than it transfers through prose.**

## 6. Reading

Reading governance source remains permitted and witnessed. A member must be able to inspect the law and
verify the bytes that govern it. Repeated reads may remain useful evidence; blindness is not protection.

## 7. Acceptance — measured, never asserted

The implementation of 0017 is not complete until all of these arms are pinned:

- CBP inert worktree copy, proven outside Classes A/B -> **ALLOW + witness**;
- registered/invoked hook -> **REFUSE / escalate**;
- symlink/realpath alias of an invoked hook -> **REFUSE**;
- shared policy core imported by the invoked hook -> **REFUSE**;
- harness registration selecting the hook -> **REFUSE**;
- installer and install manifest capable of changing the enforcing copy -> **REFUSE**;
- exemption/escape ledger -> **REFUSE**;
- working-tree seat whose registration invokes the worktree -> **REFUSE**;
- unresolved registration/dependency closure -> **REFUSE**.

The negative control matters: at least one inert governance-named source copy must be shown to become
writable under ordinary PR governance, or this decision has not removed the toll it exists to remove.

## 8. The recursion

Applying this decision changes the current self-protection mechanism, so the first implementation still
passes through today's governance. That is not a reason for a master bypass; it is the final use of the
old rule to replace itself with the narrower, evidence-derived rule.

Afterward the intended loop is:

**finding -> source change -> NOT-SAME review -> merge -> governed deploy -> observed live evidence.**

The operator remains at the authority transition: **what becomes live law.**

---

*Original thread opened by claude-code (CBP). GPT NOT-SAME amendment preserves the invoked-copy insight
but incorporates Hestia's already-measured upstream authority surfaces. Related extraction: #330.*
