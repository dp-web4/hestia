# PRD — Shim Certification

**Status:** draft, 2026-09-04 (cbp-claude). Derived from a function-by-function read of the
four deployed shims and the shared modules, not from behavioural sampling. Every criterion
below is one that at least one shim **fails today**, and each names the evidence.

## 0. Why this exists

The gate is common. The *approach to* the gate is not.

Of 14 function names defined in more than one seat shim, 6 have an equivalent already
present in the shared modules and simply are not called. The fleet did not diverge by
design; it diverged one correct local fix at a time, because nothing made drift cost
anything:

| fix | landed in | missing from |
|---|---|---|
| FP12/13/14 shell-classification fixes | claude-code | codex, kimi, gemini |
| `MODE` (warn/enforce) switch | codex, kimi | claude-code, gemini |
| authority loader (`_load_shared_module`, #742) | claude-code, codex, gemini | **kimi** |
| closure classification | claude-code, codex, kimi | **gemini** |

Each row is a defensible decision by whoever made it. Together they mean a refusal is a
property of the act **and the seat**, which makes cross-seat corroboration of a gate
verdict unsound: the peer is not re-running your experiment, it is running a different one.

**Drift was never free.** An earlier draft of this section said it was, and that was
wrong in the way that matters. The cost was being paid in full the whole time — by the
operator, in patience and in trust, because the operator is the only party positioned to
see across all four seats. Every seat could act locally correctly and remain locally
consistent; only a human looking at four shims at once could see that they had stopped
being one gate. So the bill went to the one participant who could not delegate reading it.

That is what certification changes. Not "drift now costs something" — it always did. It
**relocates an existing cost** from the operator onto the thing that drifts, and makes it
payable at the moment of the change rather than accumulated silently until someone loses
patience. A shim that drifts should fail an hourly check, not erode a person.

This also sets the bar for whether this document succeeds. Not "are the shims aligned"
but: **can the operator stop being the drift detector?** If verification still requires a
human to read four files and notice, nothing here has worked.

## 1. What a shim is allowed to be

A certified shim is an **adapter**, not a participant in policy. It converts a harness
event into the shared normalized form, calls one shared decision path, and converts the
result back into the harness's blocking protocol. It holds no governance logic of its own.

Concretely, a shim may contain exactly four kinds of thing:

1. **A profile** — the seat's identity and paths, as data.
2. **An event adapter** — harness event → `NormalizedEvent`.
3. **A response adapter** — shared verdict → the harness's blocking protocol.
4. **A bootstrap** — the authority loader, which cannot live in the shared tree because it
   is what decides which shared tree to trust.

Anything else is a finding.

## 2. Criteria

Each criterion is stated so it can **fail**. A criterion no shim can fail is not a
criterion.

### C1 — Authority loading is uniform and verified

The shim MUST resolve every governing module through the authority-loader contract:
installed directory only (no checkout fallback), `sys.path` canonicalized by
`realpath`+`normcase` so a symlink and its target cannot both hold precedence, the loaded
module's `__file__` verified to equal the required path, and `BaseException` during module
initialization converted to `ImportError` so callers reach the fail-closed posture.

> **Fails today: kimi.** It has no `_load_shared_module`. It uses five bare
> `__import__('hestia_gate_mechanism')` calls guarded by
> `if _SHARED_DIR not in sys.path: sys.path.insert(0, _SHARED_DIR)` at three separate
> points. That guard is inverted in effect — if the directory is already present at a
> later position the condition is false and nothing is inserted at 0, so an earlier entry
> wins. It compares strings rather than realpaths, so a symlink and its target are two
> distinct entries. There is no `__file__` verification, so kimi cannot tell whether it
> loaded the engine it intended.

### C2 — No private governance logic

The shim MUST NOT define any function that duplicates a shared one, and MUST NOT itself
implement classification, scope resolution, workspace detection, or record rendering.

Mechanically checkable: the set of function names defined in the shim, minus the four
permitted categories in §1, MUST NOT intersect the set of names exported by the shared
modules.

> **Fails today: codex and kimi** carry byte-identical private `_detect_workspace`
> functions while the shared core has `detect_workspace(profile)` — the same algorithm
> parameterized — and while both shims already construct a `HarnessProfile`. This is the
> function whose three copies took two of three seats offline during the 2026-09-03
> workspace move.
>
> **Fails today: claude-code** imports `hestia_shell_classifier`
> (`_READ_ONLY_HEADS`, `_is_read_only`), which appears in no shared module and in no other
> seat. It decides read-vs-write at the gate-self-access branch with a classifier the
> other seats do not have.

### C3 — Seat variation is data, never code

Every seat-specific value MUST be expressed in the profile. If a seat needs a value the
profile cannot express, the profile gains a field; the shim does not gain a function.

> **Fails today: codex and kimi.** Five wrappers each — `_gate_self_call`, `_role_bridge`,
> `_tally_scope`, `_witness_gate_self`, `_claim_self_write`, 8–10 lines apiece, two
> variants apiece — exist solely to bind `plugin_id`, `identity_path`, `client_name` and a
> tally directory into a shared engine call. Their own docstrings concede the point:
> *"Seat wrapper … one engine body decides."* Those bindings are precisely the fields
> `HarnessProfile` already declares. The wrappers exist because the mechanism API takes
> loose keyword arguments instead of a profile.

### C4 — The adapter surface is closed and enumerated

Exactly three adapter functions are permitted: the event adapter, the response adapter,
and `main`. Their names are fixed by the template. A shim defining a fourth adapter MUST
justify it in the shim's own header against this document, and that justification is part
of what is certified.

> **Justified today, and expected to remain so:** `main` (4 variants, 22–279 lines),
> `command_of` (6–9 lines) and `deny` (14–19 lines). The harnesses genuinely differ in
> event shape and in how a call is blocked. Note the size: at 6–19 lines these are closer
> to adapter *data* than code, and the template treats them accordingly.

### C5 — One decision vocabulary

All shims MUST produce the same decision kinds from the same rule ids, and MUST agree on
whether a mode switch exists. Either every seat honours a warn/enforce mode or none does.
A mode switch present on some seats and absent on others is a certification failure
regardless of its default.

> **Fails today.** `HESTIA_CODEX_GATE_MODE` and `HESTIA_KIMI_GATE_MODE` gate ~10 decision
> points apiece as `decision = "deny" if MODE == "enforce" else "warn"`. The claude-code
> shim has no such switch; its only two `"warn"` references concern *receiving* an
> audit-only verdict from the daemon. Measured over 40,000 chain entries: claude-code's
> recorded decisions are 94% `warn` (1066 of 1132); codex's and kimi-code's are 98–99%
> `deny`. Two candidate explanations — differing workload, or differing governance — and
> C8 is the experiment that separates them.

### C6 — One record renderer

The attempted-act summary, the refusal recorder, and the target extractor MUST be shared.
What the witness chain shows for an act MUST NOT depend on which seat performed it.

> **Fails today.** `_attempted_summary` has three variants (36–56 lines) and
> `_fail_closed_internal_error` has two (39 and 28 lines) that record the same
> `gate-internal-error` class by different paths — codex calls `witness_decision_unified`
> directly with `target=m._extract_target(...)`, kimi delegates to a local
> `_record_refusal`. Consistent with the chain, where codex records `target` as a bare
> first token (`wc`, `git`, `if`) while claude-code records full command text.
>
> Also fails, uniformly and therefore at least *consistently*: `rule_triggered` is `None`
> on all 1727 `policy_decision` entries across all three seats (#156).

### C7 — Fail-closed is proven, not asserted

Each shim MUST demonstrate, under test, that three conditions each produce a **recorded**
refusal carrying a rule id: an internal error in the shim, an unreachable daemon, and a
missing or miswired shared module.

The third is the one no shim tests today, and it is the one C1 is about.

### C8 — Cross-seat verdict parity

Every certified shim MUST return the same verdict as every other certified shim on the
shared parity corpus. This is the criterion that makes the others meaningful: C1–C7 are
structural, C8 is behavioural, and a shim can satisfy every structural criterion and still
diverge.

> **Fails today: 4 of 8 cases**, in both directions — claude-code more permissive on
> `for`/`if` reads (FP12's fix, which only it has) and more restrictive on `awk` pipes and
> command substitution (FP15/FP17, pinned open in its corpus, and not defects on the peers
> at all because the shared closure permits them). Instrument:
> `plugins/_shared/cross_seat_verdict_parity_test.py`.

### C9 — Provenance

The shim's content hash MUST match the certified hash stored in the vault (§3), and the
deployed copy MUST match the repository copy. Certification is of a *specific artifact*,
not of a design.

## 3. Certification record and the vault

For each certified shim the vault holds one entry:

```
shim-cert/<seat>            = sha256 of the certified shim file, normalized (§3.1)
shim-cert/<seat>.meta       = { certified_at, certified_by, template_version,
                                criteria_version, justified_diff_digest }
```

The vault is the right home rather than a file in the repo for one reason: it is sealed, so
a certification record cannot be edited by the same member whose shim it certifies. A hash
in a tracked file would be editable by anyone who can edit the shim — which is the
condition certification exists to detect.

### 3.1 Normalization

The hash is taken over the shim's source with trailing whitespace stripped and line endings
normalized, and **nothing else** — no comment stripping, no AST canonicalization. A comment
change is a certification change. That is deliberate: the justification for a permitted
difference lives in the shim's header comment (C4), so the comments are part of what was
certified.

### 3.2 What certification asserts

That a named human or quorum reviewed **this exact artifact** against **this version of
these criteria** and found the differences from the template justified. It asserts nothing
about future versions and nothing about the other seats.

## 4. Periodic verification

`hestia-agent-inventory` already runs hourly (`OnBootSec=3min`, `OnUnitActiveSec=1h`,
`Persistent=true`), already resolves each agent's deployed hook target from its harness
config, and already reports the verdicts `wired`, `governed`, and `MISWIRED` (wired but
target missing — "the worst state, because it reads as governed").

Verification extends that existing job rather than adding a new one. Two verdicts join the
vocabulary:

| verdict | meaning |
|---|---|
| `UNCERTIFIED` | deployed shim has no vault entry — never certified, or the entry was removed |
| `DRIFTED` | deployed shim's hash does not match its vault entry |

`DRIFTED` is deliberately not `MISWIRED`. A miswired shim reads as governed and is not
governed. A drifted shim *is* governed — by code nobody certified. Those are different
failures and conflating them would lose the distinction the inventory README already
insists on for the miswired case.

**Fail direction.** Verification reports; it does not un-govern a seat. A shim that cannot
be hashed (unreadable, absent) reports `UNCERTIFIED`, never "OK by absence" — the inventory
README's existing rule, that the tool must never render "nothing ungoverned" out of "could
not look", applies unchanged.

## 5. What this does not solve

- It does not make the shims correct. Four identically-wrong shims certify green.
- It does not detect a change made *and* re-certified by the same party. Certification is
  as strong as whoever holds the vault, which on a single-operator machine is the operator.
  That is A1 — cooperative and tamper-evident, not adversary-proof — and consistent with
  the assurance ceiling `STATUS.md` already claims.
- It does not cover the daemon, the shared modules, or the harness itself. Only the shim.

## 6. Order of work

C8 last, not first. The parity corpus is the acceptance test for the migration, and it
cannot pass until C1–C3 have removed the private logic that makes the seats differ. Running
it first produces a red job nobody can fix, which is how a criterion becomes decoration.

**Step 0 is larger than it looks, and it is the reason the previous four attempts at this
were a battle.** The common gate is missing its top half. The shared tree exports ~48
*primitives* — `evaluate`, `degraded_verdict`, `command_in_scope`, `needs_society_gate`,
`gate_self_call`, `witness_decision_unified`, `role_bridge`, `query_society_safety` … —
and **no orchestrator**. There is no `decide(event, profile) -> verdict`. So every shim
composes the sequence itself: which primitive to call, in what order, what to do with each
result, when to escalate, when to record, what happens when one fails.

That composition *is* the governance logic, and it is written four times because nothing
shared performs it. Every divergence found on 2026-09-04 lives in it — the mode switch,
the record renderer, the fail-closed handler, the read/write determination, the workspace
lookup. None of those are adapter concerns.

A shim can only be as thin as the shared API permits, and today the shared API hands back
parts. Promoting six duplicated functions would not have fixed this; the shims would have
kept their orchestration and simply called shared helpers from inside it.

0. **Build `decide(event, profile) -> verdict`** in the shared tree, owning the sequence,
   plus `fail_closed(profile, exc)` for the one case a shim must format itself (the shared
   recorder being unavailable). Derive the sequence from the deployed shims — codex's
   `main` at 279 lines is the most complete existing statement of it — and reconcile the
   four variants deliberately, recording each reconciliation. This is where the real
   design decisions are, and doing it by reconciliation rather than by fresh design keeps
   the incidents each variant already encodes.
1. Template (`plugins/_template/shim_template.py`) and criteria (this document).
2. C1–C3 per seat, now possible because the shim has something to delegate *to*.
   `_detect_workspace` first: three copies of the algorithm that took the fleet down on
   2026-09-03, in seats that already hold the profile parameterizing it.
3. C5–C6: one mode decision, one record renderer.
4. C7: the fail-closed proofs, including the missing-module case.
5. C8: parity goes green; the pinned divergence rows in the parity test retire themselves.
6. C9 + §3 + §4: certify, store, verify hourly.

Steps 0 and 2 rewrite the governance surface on four seats. Each write is escalatable by
construction, and that is correct — but it means this is a staged migration under review,
not a single change. A hasty version of step 2 is how the codex shim was taken offline for
eight minutes on 2026-09-03 by a blanket path rewrite that collided with existing content.
