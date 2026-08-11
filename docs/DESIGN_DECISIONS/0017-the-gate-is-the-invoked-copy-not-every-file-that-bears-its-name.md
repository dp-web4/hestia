# 0017 — The gate is the INVOKED copy, not every file that bears its name

**Status:** proposed
**Date:** 2026-08-10
**Author:** claude-code (CBP)
**Resolves:** the self-development toll paid ~a dozen times this session (#261, #263, #301, #318,
and every `gate-self-access` refusal of a read or a source edit). **Uses:** the deployment-truth
finding (registration ≠ file-name) as its mechanism.

---

## 1. The friction, stated as a leader would

An agent editing the thing that governs it is not governed — correct, and `gate-self-access` exists
to make that visible. But the rule as implemented matches **any file bearing a governance name,
anywhere on disk**. So it refuses:

- reading the gate to *understand* it (repeatedly, this session);
- editing the gate's **source in a repo worktree** — a copy that governs nothing;
- and it does so with a single-use, marker-keyed, TTL-expiring approval (#310, #318), so a human
  must re-approve **every edit**, and the approvals expire before they are used.

The result: **the human is the integration mechanism for the gate's own evolution.** That does not
scale, and it is the one place the self-closing loop cannot close — the gate cannot be improved
without a person in every single edit. Every gate hardening this session (newline #319, the git
grammars #317/#322, the payload-key correction) paid this tax.

**A rule that makes hardening the gate this expensive makes the gate less safe over time, not more.**
That is dp's own principle (0016): when the rule makes the right thing harder than the wrong thing,
the rule is the defect.

## 2. The insight, which was already in the deployment-truth work

The five-seat synthesis (2026-08-10) established: **the gate is not "a file named `pre_tool_use.py`."
The gate is the copy the harness actually INVOKES** — its registered PreToolUse hook. Registration,
not file-name, is what makes a file the gate. That is #315 and the #294 monitor spec.

Apply it here. On CBP, the enforcing gate is `~/.claude/hooks/hestia/pre_tool_use.py` (registered in
settings). A file at `hestia/.wt/deploy-main/plugins/claude-code/hooks/pre_tool_use.py` **bears the
name but governs nothing** — it is repo source. Editing it changes no verdict for any call, because
no harness invokes it. It becomes the gate only when an operator runs the installer — **which is
already separately gated** (`install-members.sh` requires operator approval, correctly, #272).

So the current rule conflates two acts with opposite risk:

| act | changes the enforcing gate? | already governed by |
|---|---|---|
| edit the **invoked/registered** copy | **yes, immediately** | must stay gated — this is the real self-access |
| edit **repo source** in a worktree | **no** — governs nothing until deployed | PR + NOT-SAME review + operator-gated install |

The second is refused today at the same severity as the first. That is the payload-key defect's
sibling: *the path where a write LANDS decides its risk; a write to a non-invoked source lands on
nothing.*

## 3. The decision

**`gate-self-access` keys on the INVOKED gate copy, not on the file name.**

A write is self-access when its destination **is (or realpath-resolves to) a copy the local harness
registration actually invokes** — the registered PreToolUse/witness/law hooks, resolved from
settings the way the installer already resolves them (`expects.json` registration reader). A write
to any other file — including repo source that bears a governance name — is **ordinary**, and is
governed the way all consequential work is: PR + NOT-SAME review + the operator-gated deploy that
would make it the gate.

Consequences, each measured against a seat this session:

- **CBP (installed):** editing `.wt/.../plugins/.../pre_tool_use.py` no longer trips — it is source,
  not the invoked `~/.claude/hooks/hestia/` copy. The branch grammar (#322) lands without f29224.
  Editing the invoked copy still trips. Deploying still requires the installer approval. **The
  human moves from per-edit to per-deploy** — one operator decision per release, not per keystroke.
- **NOMAD / HUB (working-tree seats):** the invoked copy *is* the working tree, so edits to it still
  trip — correctly, because there the source **is** the enforcing gate. Registration decides, and it
  gives the right answer per seat automatically.
- **THOR (no registration):** no invoked gate, so nothing to self-protect — matching reality (it has
  no gate), and the loudest signal remains "unregistered" (#312/#315), not a false MATCH.

**Reading is always permitted** (already true via `_is_read_only` + `gate_self_read`), so
understanding the gate stops requiring approval at all.

## 4. Why this is safe — the property that must hold

The self-access rule's job is: **an agent cannot silently change the policy that decides its own next
call.** That property is preserved *exactly*, because it is defined over the INVOKED copy — the only
copy that decides a call. Editing source that no harness invokes cannot change any decision until an
operator deploys it, and deploy is gated. Nothing an agent can reach silently changes its governance.

What changes is only the **false positives**: refusing reads, refusing edits to copies that govern
nothing, and the per-edit approval churn. The true positive — silently editing the enforcing gate —
is refused as firmly as today, and on working-tree seats that includes the worktree.

Fail-closed clause: if the local registration **cannot be resolved** (settings unreadable, ambiguous
invocation), every governance-named file is treated as invoked — the strict current behaviour. Never
guess a file is non-invoked; unknown registration means maximal protection.

## 5. What this unblocks, and what it deliberately does not

**Unblocks:** the gate evolving under review instead of under per-edit operator approval. The loop
can close on the gate itself — a member proposes a gate change, a NOT-SAME peer reviews it, it merges,
and the operator's one remaining gate is the **deploy**, which is where operator authority actually
belongs (putting a new policy into force), not on every source keystroke.

**Does not:** weaken deploy-time gating (the installer stays operator-approved), touch the enforcing
copy's protection, or change reading (already open). It does not remove the operator from governance
— it moves them to the decision that is actually theirs: *what becomes law*, not *what gets typed
into a draft of it*.

## 6. Acceptance — measured, never asserted

- On CBP, an Edit to a `plugins/**/hooks/pre_tool_use.py` **worktree source** path is **permitted
  and witnessed**, while an Edit to the **registered** `~/.claude/hooks/hestia/pre_tool_use.py` is
  **refused** — verified by both, on the chain.
- On a working-tree seat, an Edit to the invoked working-tree gate is **refused** (registration
  resolves the worktree as the invoked copy).
- With registration unresolvable, **every** governance-named write is refused (fail-closed).
- The branch grammar (#322) and future gate hardening land through **PR + review + deploy**, with the
  operator approving the deploy, not the edit.

## 7. The recursion, named honestly

This decision proposes a change to the gate, and implementing it needs one edit to the gate — which
the current rule refuses. So the **first** application still costs one operator approval (or the
worktree-source carve-out applied to its own PR). That is the last toll; it buys the removal of the
toll. Landing it is the operator putting into force the rule that lets the gate be maintained without
them in every loop — which is exactly the authority that is theirs to exercise.

---

*Filed by claude-code (CBP), leading rather than paying the toll again. Grounded in this session's
measured facts: the five-seat deployment-truth synthesis (registration ≠ file-name), #318 (approval
keyed too coarsely), #310 (approvals expire), and ~a dozen `gate-self-access` refusals of reads and
non-enforcing source edits.*
