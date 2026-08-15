# PRD — operator-editable, vault-backed ALLOWLISTS: a society floor every member expands

**Status**: proposed — dp-directed 2026-08-14; design PRD, not started; builds on #431's vault-backed operator-walled store; hub twin to follow.
**Author**: claude-code (CBP), 2026-08-14
**Operator rulings folded in (dp, 2026-08-14)** — both were drafted here as open questions and are now settled design:
- **Q4 → consolidate.** *"i agree with your instinct. consolidation whenever practical is the best way to ensure effective maintenance, clarity, and applying the law uniformly."* #431's standing-scope store **becomes the FILES axis** of this system. One store, two axes, one generation counter, one export, one editor, one set of duration semantics. See **§2.0** (the principle) and **§3.4/§3.5** (the store and its migration).
- **Q3 → a bootstrap ratchet.** *"start ceremony-light and have the option to ratchet things up to match increasing resources. we want the sufficiently-correct path to be the easy path."* The ceremony required to edit the society floor is a **declared, stored tier** that ratchets up, whose lowering must pay the tier being lowered *from*. See **§3.6**.
- **UI → GOVERN is a top-level view.** *"the LEDGER button should become GOVERN and ledger would be a sub-screen of that … make the screen toggle from agents/hubs into agents/hubs/devices/govern selector (devices being constellation management)."* The masthead switch goes four-way; govern absorbs ledger, policy and the allowlist editor; the pending-decision banners stay **above** it. See **§6.0**. This part is **independently shippable** and need not wait for the allowlist store (§6.0.5).
**Reframe folded in (dp, 2026-08-14)** — *"rather than rule on these, i want to add hooks for planned infrastructure."* §7's Q1, Q2 and Q5 are no longer awaiting rulings: each is recast as an **extension point** with an initial best guess, a stored home, an operator-walled path to change it, and the measurement that would justify changing it. The per-case form of each question is routed to the adjudicator ladder. See **§7** and **§12**.
**Relates to**: `docs/PRD_ADJUDICATOR_LADDER.md` (the decider axis — §12 is the cross-reference and the shared-convergence contract), `docs/PRD_ROLE_SCOPE_BRIDGE.md` (the third contributing authority to the composite), `docs/PRD_GATE_CONSOLIDATION.md` (§4 LAW/SHIM/AGENT, §7.1 criterion 5), `docs/GATE_SPRINT_F_NOTES.md` (R1/R2/R3), `docs/PRD_GOVERNANCE.md` (the one-authority-path invariant), `docs/PRD_CONFIG_IN_VAULT.md`, PR #431 (merged — the store pattern this reuses), issues #434 (claim-window race), #435 (permissive renders green), #438 (gauge referent), #393 (friction manufactures bypass).

---

## 0. The directive (dp, 2026-08-14) — VERBATIM, and it is the spec

> "i want an operator ui to edit each member's allow list, separate for tools and files, as well as a global society allow list. in an inversion of sorts, the global allow list is the minimal, and each member's sub-list expands not contracts. the lists live in the vault and are exported to each member . directory so they can be pulled in by the respective primers. only the in-memory copy pulled from the vault is used for the decision (and echoed back to agent on denial), the . directory copy is for startup info only, and should be updated anytime the vault copy is changed. it should be a file referenced by primer, not modifying the primer, and should contain society+member. on denial escalation, the operator should have the choice of expansion being one-time, session, or member-permanent."

Everything below is construction detail for that paragraph. Where this document and §0 disagree, §0 wins.

---

## 1. Why now — measured, not theorised

Three facts from **2026-08-14**, all readable in the live witness chain
(`hestia_query_history {"filter": {"event_type": "policy_decision"}}`) with the standing-scope
store empty:

| ts (UTC) | member | rule | tool | target |
|---|---|---|---|---|
| 19:58:35.999 | codex | `mrh.command` | Bash | `gh` |
| 19:58:36.006 | codex | `mrh.command` | Bash | `gh` |
| 19:58:36.020 | codex | `mrh.command` | Bash | `gh` |
| 19:58:47.618 | kimi-code | `mrh.path` | Read | `…/hestia/plugins/member-mesh/KINDS.md` |

(The `target` on a shell act is the command HEAD — `_extract_target` in
`plugins/_shared/hestia_gate_mechanism.py` returns `cmd.split()[0]` for `bash`/`shell`. So those
three rows are literally "codex tried to run `gh`, three times, and was refused." Both members
then re-approached compliantly — this is not a conduct problem.)

The same window also holds `mrh.command` denies whose offending token is `pwd`,
`hestia_request_scope`, and `HESTIA_MESH_PLUGIN=kimi-code` — command heads and an assignment
head, not paths at all.

**The finding: there is exactly one policy axis, and it is the wrong shape for half the acts.**
`evaluate()` (`plugins/_shared/hestia_gate_core.py`) decides a shell act only through
`command_in_scope`, which judges **where tokens resolve on the filesystem**. A CLI is not a path.
`gh` is a *tool*, and the policy model has no place to say "this member may run `gh`" — so the
only way `gh` becomes reachable is by accident of what workspace directory a token happens to
resolve to. **dp's directive supplies the missing axis.** That is the whole motivation; the UI
and the durations are how an operator drives it.

Second finding, one level up: the *floor* is invisible. Today "what every member may do" is not
written anywhere an operator can read or edit — it is the emergent residue of
`FORBIDDEN_DEFAULT`, `READ_CLASS`, `launch_cwd_repo`, `TEMP_ROOTS`, `home_markers`, and whatever
grants happen to be live. dp's inversion names it: **a society floor is a written minimum, and a
member list only ever adds to it.**

---

## 2. Model

### 2.0 The through-line: one authority path, extended from CODE to POLICY DATA

`PRD_GATE_CONSOLIDATION` §2 ratified an invariant about *code*:

> A security predicate has exactly one implementation, deciding from one authenticated authority
> source, executed through one verified loader. Per-harness behaviour is a *parameter*, never a
> second copy.

**This PRD is that same invariant applied to the data the predicate reads.** N hand-maintained
copies of a predicate and N overlapping stores of policy fail the same way and for the same
reason: the effective rule becomes the union nobody is reading, drift is invisible until it
changes a verdict, and "who decided this" stops being answerable. The gate PRD's own §3.3 is the
worked example on the code side — security fixes that existed in the tree were absent from the
enforcing hooks for four days, found only because a member kept fail-closing.

dp's ruling states the value directly (2026-08-14): *"consolidation whenever practical is the best
way to ensure effective maintenance, clarity, and applying the law uniformly."* The third clause
is the load-bearing one and it is what the FILES-axis decision turns on. **Uniform application is
not a consequence of consolidation; it is what consolidation IS.** One store means:

- **one place an operator's judgment is recorded** — a grant has one home, so revoking it revokes
  it, and provenance is a lookup rather than a search across stores;
- **one predicate reading it** — `evaluate()` consults one composed object, so a rule cannot hold
  on one axis and lapse on the other because two code paths disagreed about the same operator act;
- **one generation** — so "which policy is this copy" has one answer, which is the precondition
  the certified-replica logic in `AgentPolicy` has required since 2026-08-04;
- **one ceremony** — an operator widening a member's reach goes through the same wall, records the
  same fields, and shows up in the same panel whether the thing widened is a verb or a territory.

Concretely and settled: **#431's `StandingScopeStore` becomes the FILES axis of this store, not a
sibling of it** (§3.4 for the store, §3.5 for the migration). The three durations apply to both
axes uniformly, the export carries both axes, the denial echo covers whichever axis denied, and
#431's operator-walled decide/revoke endpoints **extend** to tools rather than gaining a parallel
set. Anywhere below where a mechanism is described for one axis, it is described for both.

### 2.1 Two axes, independent

| axis | key | admits | example entries |
|---|---|---|---|
| **TOOLS** | the *executable position* — a tool name, or a resolved command head | acts by **verb** | `Read`, `Edit`, `Bash`, `git`, `gh`, `python3`, `rg` |
| **FILES** | the existing **segment-keyed** path model | acts by **territory** | `hestia` (repo root → bare segment), `path:/abs/deeper/file` |

They are **independent and conjunctive**: an act must pass BOTH. A `gh` entry on the TOOLS axis
does not widen a single path; a `hestia` entry on the FILES axis does not authorise a verb. This
is deliberate and it is the answer to "does a tool allow apply everywhere?" — see §7 Q1, which
takes a position and marks it for ruling.

**FILES keeps the existing spelling contract**, unchanged, so nothing has to be re-taught: a repo
root directly under the workspace is stored as the **bare segment name** (`hestia`), anything
deeper stays `path:<abs>`. That mapping already exists in exactly one place —
`_scope_entry_for_grant` in `hestia_gate_mechanism.py` — and this PRD adds no second copy of it.
(Deeper `path:` entries remain inert against the segment-keyed model: Sprint F **R2**, still open,
still not this PRD's to fix. An allowlist entry that cannot admit anything must render as INERT
in the UI rather than as a grant — see §5.)

### 2.2 Three layers, and only one of them can be edited downward

```
  INNATE          FORBIDDEN_DEFAULT + egress.secret + the governance closure.
  (above all)     No allowlist entry, on either axis, relaxes any of it. Invariant, tested.
        ▲
  SOCIETY FLOOR   The MINIMUM every member gets. One list per axis. Operator-authored.
        ▲
  MEMBER LAYER    ADDITIVE ONLY. effective(m) = floor ∪ member(m). Never a subtraction.
```

`effective(member, axis) = society[axis] ∪ member[member][axis]`, computed at read, in the
daemon, once. There is no per-member "deny" field, no override, no shadowing. **A member entry
is a set union and nothing else** — which is what makes the composition auditable by inspection
instead of by simulation.

### 2.3 Contraction is refused, and the refusal names the right door

An operator editing a member list may not remove, mask, or negate a society entry. The API
refuses with `409 allowlist.contraction_refused` and a sentence that is a *routing decision*, not
a scolding:

> `hestia` is on the society floor, so removing it from `kimi-code` would make the floor a lie
> for one seat. Two real doors: (a) remove it from the **floor** — it then leaves every member
> at once, which is the honest scope of the change you are making; (b) if you mean to hold ONE
> member tighter than the floor, that is a **tightening**, and tightenings already have a durable
> channel — the vault `instance_overlays` (`POLICY_SCOPE_ASYMMETRY` row 1, `core/src/server/state.rs`).
> This surface is the loosening direction only.

That is not a workaround; it is the ratified asymmetry (`standing_scope.rs` module header):
tightening is durable and lives in the overlays, loosening is what this store does. Keeping the
two directions in two stores is why "who widened this" stays answerable.

### 2.4 The invariant, and its test

> **No allowlist entry on any axis, at any layer, relaxes an innate rule.**

Falsifiable, both directions (a one-sided guard reads as passing when its polarity is inverted):

- `allowlist_cannot_admit_forbidden` — seed society TOOLS with `cat`, society FILES with `*`, and
  member FILES with `path:~/.ssh`; assert `evaluate()` on `Read ~/.ssh/id_ed25519` still returns
  `egress.secret`, `innate=True`.
- `allowlist_cannot_admit_governance_write` — seed everything wide; assert a Write to any
  `GOVERNANCE_FILES` member still returns `gate.self_access`.
- **Positive control** (the arm that proves the test can fail): the *same* seeded lists DO admit
  a non-forbidden, non-governance act that the empty lists refuse. Without this arm a broken
  `evaluate()` that denies everything passes both assertions above.

---

## 3. Authority + storage — this IS #431's store, widened

PR #431 (merged) built precisely the store this needs, one axis narrower.
`core/src/server/standing_scope.rs` is the pattern, and this PRD **adopts it wholesale rather
than writing a second one**:

| #431 property | how the allowlist store inherits it |
|---|---|
| one vault document, `save_doc(vault, "scope", "standing", "standing-scope.json", …)` | **the same document, widened** (§3.5) — same family, same atomic temp-file-and-rename, same `load_doc` legacy-sidecar retirement. Not a second doc |
| operator-walled mutation only (`POST /api/scope/decide`, `/api/scope/standing/revoke`), challenge-signed session | every allowlist mutation is `POST/DELETE /api/allowlist/*` behind the same `authenticate_operator` path (`core/src/server/operator_auth.rs`), Ed25519 LCT challenge → session token |
| `no_mcp_tool_can_mutate_standing_scope` — asserted, not assumed | `no_mcp_tool_can_mutate_allowlist`, same shape. A member must never be able to widen itself; #133's hole was that widening was a `json.dump` |
| monotonic `generation`, moved by **every** mutation and **only** by mutations | identical, with the same no-op-revoke test |
| expiry filtered **at the read** (`live_for`), so no serving surface can leak an expired row | identical |
| disclosed inside `hestia_operating_law`'s hashed body, so a change MOVES `law_hash` | identical — an allowlist edit must move the law hash or it is a policy change nobody can detect |
| snapshot horizon = `min(now + TTL, earliest covered expiry)` | identical; reuse `STANDING_SNAPSHOT_TTL_SECS` (8h) rather than minting a second constant |

**Storage shape** (ONE document, both axes, both layers — the widened `scope`/`standing` doc of
§3.5; `grants` keeps its name and meaning so every pre-upgrade copy deserialises unchanged):

```jsonc
{ "schema_version": 2,
  "generation": 41,                       // continues across the bump, never reset
  "society": { "tools": [ {…entry…} ], "files": [ {…entry…} ] },
  "grants":  [ {…StandingGrant…} ],       // = members[*].files, exactly today's rows
  "tools":   [ {…ToolGrant…} ],           // = members[*].tools, empty on every old doc
  "ceremony": { "tier": "operator-only",  // §3.6 — ABSENT reads as tier 0, never as tier 3
                "society_consequence": "research-single-host",
                "raised_count": 0, "table": { /* kind × consequence → tier, §3.6.5 */ } } }
```

(The per-member view the UI and the export render — `members[m] = {tools, files}` — is a
*projection* computed at read from `grants`/`tools` keyed by `member`. One stored form, one
derived view; storing both would be the same duplication problem inside a single document.)

Every entry carries its provenance, because a widening whose rationale is unrecorded is
indistinguishable afterwards from a misconfiguration (#431's `reason` field, same argument):

```jsonc
{ "value": "gh", "granted_at": 1786…, "granted_by": "<operator lct from the signed session>",
  "reason": "<required, free text>", "expires_at": null,
  "origin": { "kind": "escalation", "escalation_id": "a0f5fd7b…", "duration": "member-permanent" } }
```

`origin.kind` ∈ `operator-edit | escalation | migration`. It is what §5's provenance column
renders and what makes "why does codex have `gh`" a lookup instead of an archaeology.

### 3.1 The decision reads the in-memory vault copy — nothing else

Per §0 and per PRD_GATE_CONSOLIDATION §7.1(5): **in enforce mode `evaluate()` never decides from
an unauthenticated policy.** The allowlist rides the path that already exists and adds no new
one:

`fetch_policy_snapshot` (`hestia_gate_mechanism.py`) → `hestia_scope_status` gains
`allowlist: {tools: [...], files: [...], generation, snapshot_expires_at}` **additively** (an
older daemon omits it; absent surfaces contribute NOTHING, which is the ratified direction) →
`resolve_agent_policy` stamps `generation`/`expires_at` onto the `AgentPolicy` → `evaluate()`
consults it. Snapshot unfetchable ⇒ `degraded_verdict` — the ratified deny-writes-allow-reads
posture, unchanged. **The allowlist does not get a fallback of its own**; a second fallback would
be a second authority path, which is the one thing PRD_GATE_CONSOLIDATION §2 exists to forbid.

Consequence to state plainly: in degraded mode the allowlist is *absent*, so the TOOLS axis
neither admits nor refuses — `degraded_verdict`'s read grammar governs, as today.

### 3.2 The denial echo — what it contains, and where it stops

§0: *"and echoed back to agent on denial."* A refusal that names only what was denied sends the
agent debugging blind (the defect `_offending_segment` was built to fix). But dumping the whole
effective list is worse in three ways: it is unbounded, it leaks the shape of the society's
policy into every member's transcript, and it buries the one line that matters.

**The echo answers exactly one question: what shape would have been admitted?** Design:

1. **Name the axis that decided.** `mrh.tool` and `mrh.path`/`mrh.command` are different failures
   and must not read alike.
2. **Echo the deciding axis only.** A TOOLS deny echoes the effective TOOLS list; it never
   mentions FILES.
3. **TOOLS lists echo in full.** They are small by nature (verbs, not territory) and truncating
   them would hide the very entry the agent needs to see is absent.
4. **FILES lists echo the NEAR MISS, not the corpus** — the effective entries sharing the
   offending segment's parent, plus the count of what was elided:
   `granted here: hestia, web4-mcp (+31 more, see ~/.kimi-code/hestia-allowlist.md @gen 41)`.
   The export file is already the member's full copy; the echo's job is the local shape.
5. **Hard cap 2 KB / 40 entries**, whichever binds first, with the elision COUNTED and STATED. A
   silent truncation would make "the list is short" and "the echo was cut" identical.
6. **Never echo another member's list, and never echo the floor's provenance.** The member sees
   *values*; `granted_by`/`reason` are operator-surface fields.
7. **Carry `generation`.** So a member that re-reads a stale export can tell.

The echo is composed in `REMEDIES` (a new `mrh.tool` entry) and by `_deny(rule, reason)` — never
authored at a call site. That is the existing rule and this PRD does not get an exception to it.

### 3.3 What this is NOT

The TOOLS axis is **not a security boundary against a determined member**, and must never be
described as one. hestia is assurance profile **A1** (`gate_escalation.rs` module header); every
member runs as the operator's UID (HST-009). #393 measured the exact defeat: a command-head check
is bypassed by `bash <script>`, `python3 -c`, `eval`, a here-doc into a shell — one layer of
indirection and the head is `bash`. **What the TOOLS axis actually buys:** (a) an *editable,
inspectable, per-member* statement of what a member is meant to reach for, which today exists
nowhere; (b) an end to the accidental denies of §1, where a CLI was refused by a predicate that
was never about CLIs; (c) a legible record when a member reaches past it. The security-bearing
layers remain innate FORBIDDEN, the governance closure, and society safety. Claiming more would
be the reassuring bit that is identical to the null state.

### 3.4 The one store — #431's standing scope IS the FILES axis

**Settled by dp's ruling (2026-08-14), not open.** `StandingScopeStore` and a separate per-member
FILES layer would be two vault-backed, operator-walled, generation-counted, expirable stores of
durable per-member path grants — §2.0's forbidden shape reproduced in data instead of code. The
failure mode is concrete: an operator revokes a path in one store, the other still serves it, and
the effective policy is the union nobody was reading. So there is **one store with two axes**.

Three things make the absorption cheap rather than a rewrite:

1. **`StandingGrant` is already the entry shape.** It carries `member`, `path`, `granted_at`,
   `granted_by`, `reason`, `expires_at`, `request_id` — which is §3's entry minus a `value`
   rename and with `request_id` folding into `origin`. Nothing about the record has to change in
   kind.
2. **The consumer never knew there were two stores.** `fetch_policy_snapshot` already flattens
   `live_grants` + `standing_grants` into one `in_scope` list through one mapping
   (`_scope_entry_for_grant`). The gate reads a composed list today; it keeps reading a composed
   list, with a second axis beside it.
3. **The wall, the counter, and the persist are the ones #431 built.** Operator-only mutation,
   monotonic generation on every mutation and only mutations, atomic vault write, expiry filtered
   at the read, disclosure inside the hashed law body. All of §3's table is inherited, not
   re-derived.

**Endpoints extend rather than fork.** `POST /api/scope/decide {standing:true}` and
`POST /api/scope/standing/revoke` are the existing operator-walled promotion and revocation for
paths. They gain an `axis` parameter (`files` | `tools`) and a `duration`
(`one-time` | `session` | `member-permanent`, §5) — **not** a parallel `/api/allowlist/tools/*`
family. The `/api/allowlist/*` routes in §6.1 are the *editor* surface (list, floor edit, member
edit, revoke); they and the escalation surface mutate **the same store through the same wall**,
and a test asserts there is exactly one mutation entry point per operation
(`one_mutation_path_per_allowlist_operation`).

**What stays out, and why it is not an exception to the ruling.** Consolidation applies where the
things being consolidated are the same kind of thing. Two stores remain, deliberately, because
they are *different rows of the ratified asymmetry* (`POLICY_SCOPE_ASYMMETRY`,
`core/src/server/state.rs`), not duplicates of this one:

- **live memory-only grants** from `hestia_request_scope` — row 2, ephemeral by construction, and
  restart is their backstop. Merging them into a durable store would make them durable, which is
  the opposite of what they are for. They continue to compose into the same served `in_scope`
  list, so the *effective* answer is still computed in one place.
- **`instance_overlays`** — row 1, the **tightening** direction. This store is the loosening
  direction only (§2.3). Keeping the two directions apart is what keeps "who widened this" and
  "who narrowed this" separately answerable, and merging them would produce a store where an
  entry's meaning depends on a sign bit.

### 3.5 Migration — a schema bump on the existing doc, not a new one

Two options, and the lower-risk one wins.

*Rejected:* a **new** `allowlist`/`v1` document that supersedes `scope`/`standing` via a one-time
migration read. It reads cleaner, but it puts a **fold across two documents on the startup path**,
and the failure mode is a silent revocation — a member that could reach a repo before the upgrade
silently cannot after, discovered by a deny in some session hours later. Data loss on a policy
loosening is the failure that is hardest to notice, because the symptom is a *refusal*, which
looks exactly like the system working.

*Chosen:* **bump the existing document in place.** `scope`/`standing` (file
`standing-scope.json`) gains a `schema_version` and a `tools` axis; its existing `grants` vector
becomes the FILES axis, read by `serde` with `#[serde(default)]` on everything new. A pre-upgrade
document therefore deserialises to exactly its current meaning with an empty tools axis — **the
no-op upgrade is the default path, not a code path someone has to get right.** The generation
counter continues from where it was; it is not reset, because a reset counter beside surviving
grants is precisely the "which policy is this copy" ambiguity #431 added it to end.

```rust
// core/src/server/standing_scope.rs — the store, widened, not replaced.
pub struct StandingScopeStore {          // name kept through the bump; renaming a live
    #[serde(default)] pub schema_version: u32,   // vault doc is a second migration for no gain
    #[serde(default)] pub generation: u64,       // CONTINUES — never reset
    #[serde(default)] pub grants: Vec<StandingGrant>,   // = members[*].files, as today
    #[serde(default)] pub tools: Vec<ToolGrant>,        // NEW axis, empty on every old doc
    #[serde(default)] pub society: SocietyFloor,        // NEW layer, empty on every old doc
    // NEW. `Default` = tier 0 (§3.6.2): absence must read DOWN, or the floor editor
    // bricks on the day it ships — the Q3 failure reintroduced by the fix for it.
    #[serde(default)] pub ceremony: Ceremony,
}
```

An empty `society` floor is the **current** floor, exactly — today's floor is unwritten, so an
empty one changes no verdict on the day of the upgrade. The floor gets populated by an operator
act afterwards, which is a change dp makes deliberately rather than one a migration performs.

**Pinned by test — the criterion is effect, not row count:**

- `migration_preserves_every_standing_grant` — load a pre-upgrade `standing-scope.json` fixture,
  run the upgraded loader, and assert **grant-for-grant equality of the effective set**: for each
  `(member, path)` in the fixture, `has_live` is true after. Row counts are refused as the
  criterion — a fold that drops one grant and adds two passes a count check.
- `migration_admits_what_it_admitted` — the behavioural half, one level up from the store: take a
  member and a path it could reach before, run `evaluate()` against the post-migration composed
  snapshot, assert **allow**. A migration that preserves rows but changes how they compose is
  still a silent revocation.
- `migration_is_a_no_op_on_generation` — the counter after load equals the counter in the fixture.
  Loading is not a mutation and must not claim one.
- **Negative control:** a fixture with a grant deliberately deleted must make
  `migration_preserves_every_standing_grant` FAIL. Without this arm, a preservation test that
  silently passes on an empty store proves nothing.

### 3.6 The ceremony ratchet — how much authority a floor edit requires, and how that grows

**Operator ruling (dp, 2026-08-14), on what was Q3:**

> "on q3, like with everything else, we need a bootstrap ratchet. start ceremony-light and have
> the option to ratchet things up to match increasing resources. we want the
> sufficiently-correct path to be the easy path. i suspect it will eventually depend on the KIND
> of society expansion being contemplated, and definitely on how complex/consequential a society
> is in the first place."

#### 3.6.1 The north star, and why it is a *security* argument

> **"We want the sufficiently-correct path to be the easy path."**

This is `CLAUDE.md`'s efficiency-attractor doctrine applied to ceremony. The attractor is
structural, not behavioural: the shortest path to completing a task is a deep basin, and
"try harder" is not an architecture. **A bar set above the resources available to satisfy it does
not produce more rigor. It produces route-arounds** — and #393 measured exactly that at the gate:
a false-positive refusal on a benign `flock` command drove the identical shell into a script file
run as `bash <script>`, which the gate allowed. The friction manufactured the bypass. A ceremony
nobody can complete manufactures the same thing one layer up: the floor never gets written, and
every widening arrives as a member expansion instead — which is the exact inversion of dp's
design (§0: the floor is the minimum, member lists expand).

So the operative rule, stated as a constraint on the design rather than as advice:

> **A ceremony tier is correct only if it is satisfiable today, by the people who must satisfy
> it.** An unsatisfiable tier is not a stricter policy; it is an unwritten one. Raising the tier
> as resources arrive is the ratchet's job — not the initial setting's.

That is precisely the finding that raised Q3 and it survives the ruling intact: the
`SovereignPlusPeer` bar has never scored a lifetime invitation and its corroboration filter is
uninstalled. Under this section that is no longer a blocker — it is simply a **tier this society
has not yet ratcheted to**, and the design says so out loud rather than shipping a bar that
cannot close.

#### 3.6.2 Tiers are declared and stored, never implied

The required ceremony is a **stored value**, not a property emergent from which code path an
edit happens to take. It lives beside the floor, in the same document (§3.5), so it moves with
the policy it governs and is covered by the same generation counter:

| tier | name | evidence required | satisfiable today? |
|---|---|---|---|
| 0 | `operator-only` | one challenge-signed operator session (`authenticate_operator`) | **yes — bootstrap default** |
| 1 | `operator-plus-witness` | tier 0 + a second *witnessing* identity recorded on the act (not a second approver — an observer whose record is chain-anchored) | yes, mechanically; needs a designated witness seat |
| 2 | `sovereign-plus-peer` | `gate_escalation.rs::Bar::SovereignPlusPeer` — operator plus a corroborating peer member | **no — the bar has never scored; corroboration filter uninstalled** |
| 3 | `quorum` | N-of-M named identities | not built |

**Bootstrap default = tier 0, `operator-only`**, and the rationale is the Q3 finding, kept
stated: a bar that cannot be satisfied means the floor never gets written and every widening
becomes a member expansion. Tier 0 is not "no ceremony" — it is the challenge-signed Ed25519 LCT
operator session that already walls #431's endpoints. It is the *lightest sufficiently-correct*
setting for a one-machine research society, and that is the whole claim being made.

**An absent tier declaration reads as tier 0, not as tier 3.** This matters at exactly one
moment — the migration (§3.5), where a pre-upgrade document has no tier field at all. Defaulting
absence upward would brick the floor editor on the day it ships (unsatisfiable tier 2), which is
the Q3 failure reintroduced by the fix for it. Defaulting to 0 is also *ceremony-neutral for the
FILES axis*: tier 0 is exactly the wall #431 already had, so the migration neither raises nor
lowers what a path grant costs (§3.6.6, asserted).

#### 3.6.3 The ratchet is asymmetric, and lowering must pay the OLD tier

**Accepted, and it is the clause that makes the ratchet real rather than decorative.** Raising is
cheap: any actor who satisfies the *current* tier may raise it. Lowering is not:

> **Lowering the ceremony tier from N requires satisfying tier N — the tier being lowered FROM,
> not the tier being lowered to.**

Without this the ratchet is a sign, not a mechanism: an actor who can lower the bar under the
lowered bar can then perform any act under it, so the effective ceremony of *every* protected act
collapses to the cheapest tier reachable by one lowering step. This is the same shape as
`PRD_GATE_CONSOLIDATION` §5's closure rule — *"a write that can redirect **which** core executes
is equivalent to a write to the core"* — and the answer is the same: **the control must protect
its own registration.** A tier that governs everything except the setting of itself governs
nothing.

Pinned, with the negative arm that proves the guard can fire:

- `lowering_tier_requires_the_old_tier` — with the tier at 2 and only tier-1 evidence presented,
  the lowering is **refused**.
- `raising_tier_requires_only_the_current_tier` — with the tier at 0 and tier-0 evidence, the
  raise **succeeds**. (Without this arm, a store that refuses every tier change passes the first
  test and the ratchet is broken in the other direction.)
- `tier_change_is_witnessed_and_bumps_generation` — a tier change is a policy mutation like any
  other: same monotonic counter, same chain record (`allowlist_ceremony_tier_changed` carrying
  from/to, the evidence relied upon, and the operator identity), same export refresh. A ceremony
  change that did not move the generation would be a policy change no replica could detect.

#### 3.6.4 The deadlock escape — because "unsatisfiable" is exactly what this section forbids

§3.6.3 creates a hazard the rest of this section exists to prevent: **ratchet to a tier that
later becomes unsatisfiable — the peer seat retires, the corroboration filter stays uninstalled —
and the floor is permanently uneditable, with no legitimate way down.** That is the Q3 failure
again, arrived at by a different road. A ratchet with no escape is a ratchet that eventually
bricks the thing it protects.

The escape must not become the easy path, so it is designed to be **slow and loud rather than
forbidden**:

1. Attempts to satisfy the current tier are recorded — a *failed* ceremony is evidence, and today
   it leaves no trace at all (the fail-closed-deny-leaves-no-record class).
2. After a declared **dwell period** with recorded failed attempts and no successful satisfaction,
   a lowering may proceed on tier-(N−1) evidence, as `escape` rather than as an ordinary lowering.
3. The escape is witnessed with its own event kind and its own reason field, and the dashboard
   renders the society as **`ceremony lowered under escape`** until an operator affirms the new
   tier at that tier. It is a visible state, not a silent return to normal.

Why this is the right trade, stated plainly: against a *determined* actor holding the operator's
UID this buys nothing — hestia is assurance profile A1, HST-009, every member runs as the
operator (§3.3 makes the same concession about the TOOLS axis and it applies here too). What it
defeats is the **efficiency attractor**: an agent taking the shortest path to "get this floor
edit done" will not choose a path that requires a dwell period and paints a banner on the
dashboard. The bypass is available and expensive and legible — which is the most an A1 system
can honestly claim.

#### 3.6.5 The seam: tier as a function of KIND × consequence

dp: *"i suspect it will eventually depend on the KIND of society expansion being contemplated,
and definitely on how complex/consequential a society is in the first place."*

**This PRD commits to the SEAM, not to the table.** The initial table is deliberately trivial;
what must exist now is the lookup, so that populating it later is data, not a refactor of every
mutation path.

`required_tier(kind, society_consequence) -> Tier`, a stored table beside the floor.

**KIND** — enumerated from what actually exists in this design, not invented:

| kind | why it is its own kind |
|---|---|
| `floor.tool.add` | a verb granted to every seat at once |
| `floor.path.add.new_root` | a **new repo root** on the floor — territory nobody had |
| `floor.path.add.within_granted` | a deeper path inside a root already on the floor — strictly less consequential, and the distinction already exists in the code (`_scope_entry_for_grant`: repo root → bare segment, deeper → `path:`) |
| `floor.remove` (narrowing) | narrowing the floor is *not* the loosening direction this store is for; it removes reach from every member simultaneously, which is high-consequence in the availability direction and must not be filed as "safe because it is tighter" |
| `member.*` | a member expansion — the lightest kind, and the one that stays cheap so §0's inversion keeps working |
| `governance.*` | **not floorable at all.** The governance closure sits above allowlists entirely (§2.2, §2.4); it has no tier because no tier admits it. The table returns a refusal, not a number — an entry that returned "tier 3" would imply a price exists |

**SOCIETY CONSEQUENCE** — one declared scalar for now (`research-single-host` |
`multi-seat` | `hub-occupied`), stored, operator-set, and itself ratchetable. A one-machine
research society and a fleet with outward hub occupancy are not the same risk and should not be
forced onto one ceremony. Populating the full matrix is **future work, marked as such**; today
every cell resolves to tier 0 except `governance.*` (refused) — and that is an honest statement
of where this society is, not a placeholder pretending to be a policy.

**Batches take the MAX tier of their members**, and the governing tier is recorded on the act.
Refusing mixed-kind batches would push an operator toward many small edits — more clicks for the
same act, which is the efficiency attractor being fed rather than designed around.

#### 3.6.6 Interaction with the two-axis consolidation

Three interactions, two benign and one that needs an assertion:

1. **The consolidation is what makes the KIND seam expressible.** `floor.tool.add` and
   `floor.path.add.*` can only be compared — and given different tiers — because one store knows
   both kinds. Two stores would have drifted to two ceremonies with no surface on which to notice.
   The ratchet is *enabled* by §3.4, not in tension with it.
2. **The migration must be ceremony-neutral for FILES.** #431's path grants were walled at a
   challenge-signed operator session; tier 0 is that same wall; absence reads as tier 0 (§3.6.2).
   So the upgrade neither raises nor lowers what a path grant costs. **Asserted:**
   `migration_does_not_change_the_files_ceremony` — a mutation that succeeded pre-upgrade with
   tier-0 evidence still succeeds post-upgrade, and one that failed still fails.
3. **The TOOLS axis inherits a wall it never had, and that is the safe direction** — it arrives
   governed rather than ungoverned. Worth stating because it is a real behavioural change riding
   the migration, and unstated behavioural changes riding migrations are how "shipped ≠ in force"
   happens in reverse.

#### 3.6.7 Visibility (#435/#438)

The current tier is rendered **plainly, on the face of the floor editor** — not in a settings
page, not on hover. Per the never-flatter doctrine:

- A light-ceremony society is a **legitimate state** and must not be rendered as a defect — no
  red, no warning icon, no nag. `ceremony: operator-only` is a fact.
- It must equally not render as though it were heavy — no lock glyph, no shield, no "protected"
  language that implies a bar nobody set. A tier-0 floor editor that *looked* tier-2 would be
  #435's green-permissive defect in a new costume: a reduced-ceremony state wearing the
  appearance of a stronger one.
- The label names its referent (#438): `ceremony: operator-only · society: research-single-host ·
  raised 0 times`, and, when applicable, the escape banner of §3.6.4.
- The **available** tiers and their satisfiability are shown beside the current one, so the ratchet
  is discoverable — a mechanism nobody can see is a mechanism nobody uses. Tier 2 renders as
  `sovereign-plus-peer — NOT SATISFIABLE HERE (no corroborating peer seat)`, which is the honest
  state and also the to-do list for raising it.

---

## 4. The `.`-directory export

### 4.1 Contract

- **Destination.** The member's dot-directory ROOT (not `hooks/`) — that is where its primer
  lives. From `plugins/*/expects.json`, the installed roots are `~/.claude`, `~/.codex`,
  `~/.kimi-code`, `~/.gemini`; the `install.dest` values there (`~/.claude/hooks/hestia`,
  `~/.codex/hooks`, `~/.kimi-code/hooks`, `~/.gemini/hestia-plugins/gemini/hooks`) give the root
  by their common prefix, and the export path is derived from the same manifest so a new plugin
  is exported to by **registering**, not by editing the exporter.
- **One file**: `<dot-dir>/hestia-allowlist.md`. Markdown, because its consumer is a language
  model reading its own primer, and a table is the legible form. One artifact ⇒ one mtime ⇒ no
  "which of the two is current" question.
- **Header block** (first lines, trivially machine-parseable for the staleness check):
  `member`, `generation`, `exported_at`, `source: vault:allowlist/v1`, `authority: the daemon's
  in-memory copy decides — this file is startup information only`.
- **Body**: two tables (TOOLS, FILES) — **both axes always present**, an empty one rendered as an
  explicit `(none)` row rather than omitted, because a missing table and an empty list read alike
  and only one of them is true. Each table has a `layer` column reading `society` or `kimi-code`.
  §0: *"should contain society+member."* Values only — no `granted_by`, no `reason`.
- **Written on every vault change**, in the same handler that persists, after the persist
  succeeds (§4.3 on ordering).

### 4.2 Referenced by the primer, never a modification of it

§0 is explicit: *"a file referenced by primer, not modifying the primer."*

- The **installer** (`plugins/*/install.sh`) writes a one-line reference into the primer
  (`~/.kimi-code/AGENTS.md`, `~/.claude/CLAUDE.md`) inside its own `HESTIA:ALLOWLIST-REF` marker
  pair, **once, at install**. The line points at `./hestia-allowlist.md` and states that the file
  is startup info and the daemon decides.
- The **exporter never opens the primer.** Asserted:
  `export_writer_never_opens_a_primer` — run the exporter against a temp home containing a primer
  with a known digest; assert the digest is bit-identical afterwards. (This also keeps the
  exporter clear of `hydrate.sh`'s `HESTIA:STATE` region, which is a different owner rewriting a
  different marker in the same file — two writers to one file is a bug waiting for a race.)

### 4.3 The export is startup info and NOTHING reads it to decide

This is the property most likely to erode, so it gets the strongest test — **two-sided**, because
a one-sided guard passes when its polarity is inverted:

- `stale_export_cannot_widen` — write an export granting `*` on both axes; run the decision path
  with an empty vault allowlist; assert the verdict is byte-identical to the no-export run.
- `stale_export_cannot_narrow` — write an EMPTY export; run with a populated vault allowlist;
  assert the verdict is byte-identical to the no-export run.
- `no_decision_module_names_the_export` — a structural assertion that neither
  `hestia_gate_core.py` nor `hestia_gate_mechanism.py` contains the export basename. Cheap, and
  it fails on the *day someone adds the read*, not on the day it changes a verdict.

**Ordering (the O clause).** Vault persist FIRST, export second. The vault is the authority; an
export that landed for a persist that failed would be a policy the daemon does not hold. A failed
export is therefore never a reason to fail the grant.

**Export failure must not block, and must not be silent.** Reuse the pattern already built for
exactly this shape — `record_gate_unavailable`'s sibling: append to
`$HESTIA_HOME/telemetry/allowlist-export.jsonl` with `{member, generation, cause, ts}`, never
raise, and surface a per-member chip in the dashboard's allowlist panel reading
`exported @gen 41` / **`export STALE @gen 38 (vault 41)`**. Per #438's never-flatter doctrine:
the panel states `4/4 members exported` or names the ones that are not — an aggregate that can be
green while one seat is three generations behind is the gauge defect that issue is about.

**Staleness is detectable from the member's side too**: the export carries `generation`, and
`hestia_scope_status` serves the live one, so a member (or its SessionStart hook) can compare and
say so rather than trusting its file.

---

## 5. Escalation-time expansion durations

§0: *"on denial escalation, the operator should have the choice of expansion being one-time,
session, or member-permanent."*

The decision surface is the existing escalation panel (`#esc-list`, `index.html` ~1089) and
`POST /api/operator/gate-escalation`; the duration is a **required** third field beside
approve/deny — a default would be an unrecorded policy choice.

**The three durations apply to BOTH axes, identically** (§2.0). A denial is a denial: whether the
member was refused a verb or a territory, the operator gets the same three choices, they are
stored by the same rules, witnessed with the same events, and revoked through the same verbs. A
duration that meant something different on one axis would be exactly the non-uniform application
of law the consolidation ruling is about. The escalation carries `axis` alongside `duration`, and
the row below is read once for either value.

| duration | stored | takes effect | witnessed as | ends / revoked |
|---|---|---|---|---|
| **one-time** | existing escalation approval (`gate_escalation.rs`), spent on claim | the existing approve → re-issue → `hestia_gate_escalation_claim` path | `gate_escalation_decided` + the spend | self-terminating; expiry per `DEFAULT_TTL_SECS` + claim window |
| **session** | daemon **memory**, keyed `(member, host_session_id)`, explicit `expires_at` | **no claim** — next `fetch_policy_snapshot` carries it | `allowlist_session_grant` chain entry, with the escalation id | earliest of: explicit revoke · observed session end · daemon restart · TTL ceiling **8h** (`STANDING_SNAPSHOT_TTL_SECS` — reused, not a second constant) |
| **member-permanent** | the **vault** allowlist doc, `origin.kind = "escalation"` | **no claim** — generation bumps, snapshot carries it, export refreshes | `allowlist_edit` chain entry + the generation | operator removes the entry in the UI (or `expires_at`, if set) |

Session lives in memory and permanent in the vault because that is the ratified asymmetry
(`POLICY_SCOPE_ASYMMETRY`): a *session-bounded* loosening whose backstop is restart belongs in
memory; a durable loosening must be operator-decided, vault-held, generation-counted, revocable —
which is exactly the row #431 added.

### 5.1 The generation, when part of the store is memory-only

Two counters, served separately, and the asymmetry is load-bearing:

- `generation` — the **durable** counter. Monotonic, survives restart.
- `session_generation` — the memory counter. **Resets to 0 on restart** — and that is safe
  precisely because the session grants it counts *also* die on restart. A reset counter never
  accompanies a surviving grant. (This is the inverse of the trap `AgentPolicy`'s docstring
  documents: a replica is dangerous when it is *wider* than current policy. Here both sides reset
  together, so the copy cannot be wider.) Summing them into one integer would break monotonicity
  across a restart and is explicitly rejected.

### 5.2 Neither session nor permanent inherits #434's claim race

#434 measured the loop racing two timers: `ESCALATION_RPC_TIMEOUT_S = 1.5s` against a 4-call
claim sequence at ~750ms/call, and `APPROVAL_CLAIM_WINDOW_SECS = 600` against human latency
(four approvals expired unclaimed in one day). **A claim is a race by construction, and the
session/permanent durations must not import it.**

They do not, because they change *policy*, not a pending approval: after the operator decides,
the member's next ordinary act fetches a snapshot that already contains the grant. There is no
window, no spend, no 4-call sequence — the member simply is not denied any more. Required as a
falsifiable criterion (§6, AC-7): **no code path for `session` or `member-permanent` calls the
claim verb.**

One-time keeps the claim path (it is the existing, correct mechanism for a single spent act) and
therefore keeps #434's race until #434 is fixed. Stated, not hidden — and it is an argument for
making `session` the operator's habitual choice for "yes, for now."

### 5.3 Revocation is first-class for all three

Because revocation is precisely the operation a policy authority most needs to work (#431's own
reasoning). Permanent entries revoke through **#431's existing endpoint**,
`POST /api/scope/standing/revoke`, widened with `axis` — not a parallel tools-revoke, per §3.4.
Session grants revoke through `POST /api/allowlist/session/revoke`; one-time ends by escalation
expiry or deny. Each moves its counter, is witnessed, and triggers an export refresh — and each
does so the same way on both axes.

---

## 6. The UI

### 6.0 Information architecture — GOVERN becomes a top-level view

**Operator ruling (dp, 2026-08-14):**

> "i think the LEDGER button should become GOVERN and ledger would be a sub-screen of that.
> within the govern ui we can have the allow lists, generally following the same scheme as the
> agents screen. in fact, perhaps we should remove the separate button and instead make the
> screen toggle from agents/hubs into agents/hubs/devices/govern selector (devices being
> constellation management)"

This is an **information-architecture change**, not a placement detail, and it is the reason the
allowlist editor does not get a button of its own.

#### 6.0.1 One navigation axis

The masthead segmented switch (`#view-switch` / `.view-chip` / `.dash-view`, `index.html` ~847)
goes from **agents | hubs** to **agents | hubs | devices | govern**. There is then exactly one
navigation axis for the whole dashboard, and **no peer-level buttons competing with it.**

The `ledger` button (`#ledger-btn`, `.agents-wrap`, ~877) is **removed** and its modal becomes a
sub-screen of govern. So is the `policy` view, which today is reachable only through
`#policy-btn` — a pill buried in the *witness-chain card header* (~957). A governance surface
hiding inside a live-feed card header is precisely the problem dp is removing: it is discoverable
only by someone who already knows it is there, which is the same failure the escalation banner
was built to fix one layer up (*"a route the UI never calls is what we already had"*).

| today | after |
|---|---|
| `ledger` button in the masthead → `#ledger-modal` | **govern → ledger** sub-screen |
| `policy` pill inside the witness-chain card header → `#policy-modal` | **govern → policy** sub-screen |
| (nothing) | **govern → allowlists** — floor, per-member expansions, ceremony tier |

#### 6.0.2 Govern follows the agents screen's scheme

dp: *"generally following the same scheme as the agents screen."* The agents view is
**selection-driven detail**: pick an orchestrator chip / harness row, see that thing's trust
resolved beside it. Govern inherits the shape rather than inventing one — **pick a member, see
its lists** — so an operator who has learned one screen has learned both, and the allowlist
editor's per-member cards (§6.2) are the detail pane of that selection rather than a modal
stacked on a modal.

#### 6.0.3 DEVICES — the slot is reserved, and it must not look finished

`devices` is **constellation management**. `core/src/constellation.rs` exists and is substantial
(paired device LCTs, capabilities, liveness, `DeviceStatus` as the authoritative gate, the
constellation proof/attestation), and the dashboard snapshot **already carries** a `constellation`
field (`dashboard.rs` ~1104). The *screen* largely does not exist.

**This PRD reserves the slot and states its intended scope as future work. It does not invent its
contents.** And the honest failure mode is named, because it is the never-flatter doctrine
(#435/#438) applied to navigation: **a nav slot advertising a screen that does nothing is itself
a never-flatter violation.** A tab that opens onto a plausible-looking empty panel tells the
operator the constellation is empty, when the truth is that nobody built the view. So `devices`
either renders real device/seat state from the snapshot field that already exists, or it says
**"not yet implemented"** in as many words. Those are the two acceptable states; "looks finished,
shows nothing" is not one of them.

#### 6.0.4 THE CAVEAT — the banners stay ABOVE the switch

Carried as a **hard constraint**, quoted from the code's own design note (`index.html` ~918):

> "The escalation/scope banners deliberately sit ABOVE both — an operator decision awaiting
> action must never be hidden behind a tab."

When govern becomes a tab there is an obvious tidiness argument for moving pending escalations
and scope requests into it — they are governance, govern is the governance screen. **Do not.**
The banners (`#esc-banner`, `#scope-banner`, ~899/~908) stay above `#view-switch`'s views, visible
on every screen including hubs and devices.

The distinction that makes this non-arbitrary: **govern holds the history and the editing; the
pending decision is a notification and stays unconditionally visible.** It is the same line the
ledger button's own comment already draws — *"it sits in the title bar rather than behind a
banner because a banner is a notification and this is a record"* — and this constraint is that
sentence read in the other direction. The original defect was five escalations opened against dp
in one session, none of which dp saw; putting them one tab-click away is a smaller version of the
same failure, and a later tidy-up is exactly how it would return. Pinned as **AC-20**.

#### 6.0.5 Independently shippable — do not couple the sequencing

**The IA change does not depend on the allowlist store existing and could land before it.**
Ledger and policy move into govern; allowlists appear as a third sub-screen when built; devices
takes its slot under §6.0.3's terms. Said explicitly so the two are not welded together in
planning: the navigation fix is worth having on its own, and holding it hostage to a policy store
that has not been written would be a self-inflicted dependency.

### 6.1 Where the allowlist editor lives, and how it authenticates

- **Entry point**: **govern → allowlists** (§6.0), a sub-screen of the top-level `govern` view —
  **not** a modal, and **not** a pill in another card's header. Per-member selection drives the
  detail pane, following the agents screen (§6.0.2).
- **Auth**: identical to every other operator surface on this page — the credential in
  `$HESTIA_HOME/operator.key` (lct_id + Ed25519 seed) signs a server challenge from
  `POST /api/operator/challenge`, `POST /api/operator/session` returns a token, and the token
  rides every `/api/allowlist/*` call (`index.html` ~1252-1280, `operator_auth.rs`). **No new
  auth mechanism.** Reachability is not authority: a same-host reader gets read-only; every
  mutation requires the signed session (§9, R clause). The `/api/allowlist/*` family is the
  **editor** surface only; escalation-time expansions keep going through #431's widened
  `/api/scope/decide` (§3.4), and both mutate the same store behind the same wall.
- **Escalation durations** land in the existing escalation panel, not here — the operator is
  already looking at the denial when they choose.

### 6.2 What it shows

1. **Society floor**, both axes, editable, with a standing banner naming its blast radius:
   *this binds every seat on this box, including unattended watcher-fired agents* — the argument
   the policy modal already makes at ~1144 for presets, and it is more true here. **The current
   ceremony tier is rendered on the face of this editor** (§3.6.7), with the available tiers and
   their satisfiability beside it — neither dressed up as protection nor flagged as a defect.
2. **Per-member expansions**, one card per member, each entry showing **value · granted_by ·
   when · why · origin** (operator-edit, or the escalation id it came from — clickable through to
   the ledger). A grant whose provenance is unreadable is a misconfiguration nobody can date.
3. **Effective view** per member — the union, with each row badged `floor` or `expansion`, since
   the union is what actually decides and an operator reading two lists is doing set arithmetic
   in their head.
4. **INERT badge** for entries that cannot currently admit anything — a deeper `path:` entry under
   the segment-keyed model (Sprint F R2). An entry that looks like a grant and grants nothing is
   the worst row on the screen.
5. **Export state** per member: `@gen N` or `STALE @gen M (vault N)`, plus last export error.

### 6.3 Never-flatter display (#435, #438)

#435: the society preset rendered **green "permissive for all"** while in a reduced-enforcement
state. #438: a gauge said `current` about a referent the operator was not asking about. Both are
the same defect — *a loosened or under-specified state rendering as reassurance*. The allowlist
panel is a breadth display and inherits the doctrine as **hard rules**:

- Breadth colours the chip: a wildcard (`*`) on either axis, at either layer, renders **red** and
  says `UNBOUNDED`. Wide-but-bounded renders **amber**. Green is reserved for a floor-only member
  with no expansions. **There is no state in which a wide list renders green.**
- Counts are stated with their **referent**, never bare: `12 floor + 7 expansions = 19 effective
  (gen 41, exported 4/4)`. A bare count is true of more than one population.
- The panel's own staleness is on its face: `snapshot gen 41 · fetched 3s ago`. A panel that can
  be minutes behind the vault while looking authoritative is #438 again, one surface over.
- An empty member list renders `floor only`, **not** a green checkmark — "no expansions" is a
  fact, not an achievement, and rendering it as success teaches the operator that expansions are
  failures.

### 6.4 The app-shell height chain — YES, the new views need #427's treatment

**Answered here as a requirement so it is not rediscovered as a scroll bug on the new screens.**

**Yes.** #427 fixed exactly this class: `#agents-view` / `#hubs-view` sit *between* `main` (a flex
column) and `.live-grid`, and carried only `[hidden]{display:none}` — so when shown, a view was a
plain `display:block` of auto height, the flex chain broke, `.live-grid`'s `flex:1 1 auto` had no
bounded parent, the chain card grew to full content height, and `main{overflow:hidden}` **clipped
it — the witness chain could not scroll.** The fix
(`index.html` ~288, inside the `@media (min-width:1100px) and (min-height:720px)` app-shell block):

```css
main > .dash-view:not([hidden]) { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
```

The good news: that selector is **generic, not id-based**, so a fourth and fifth view inherit the
fix *for free* — **but only if all three of its preconditions hold**, and each is easy to violate
while building a new screen:

1. **Direct child of `main`.** The selector is `main > .dash-view`. Nesting `#govern-view` inside
   any wrapper (a padding div, a sub-nav container) silently drops the rule and reproduces #427
   verbatim on the new screen.
2. **Carries `class="dash-view"`.** A new view styled from scratch, or given its own class, gets
   nothing.
3. **Toggled via the `hidden` ATTRIBUTE**, not `style.display`. The rule keys on `:not([hidden])`,
   and `.dash-view[hidden]{display:none}` (~108) is what hides it. A view hidden by inline
   `display:none` would still match `:not([hidden])`, so the *hidden* view would also be told to
   be a flex column — harmless today, but it makes "which view is mounted" a fact with two
   contradicting sources, which is how the next layout bug gets built.

**And the chain must be CONTINUED inside the new views, which the rule alone does not do.** The
rule bounds the *view*; the agents screen then continues it with `.live-grid { flex:1 1 auto;
min-height:0 }` → `.live-grid > .card {display:flex; min-height:0; max-height:100%}` → `.feed
{flex:1 1 auto}`, and **that** is what makes the feed's `overflow-y:auto` engage. A govern screen
with a long ledger or a long member list needs its own equivalent: the scrolling region must be a
flex child with `min-height: 0`. Omitting `min-height: 0` is the classic version of this bug —
flex items default to `min-height:auto` and refuse to shrink below content, so the list grows and
`main{overflow:hidden}` clips it exactly as before. **Requirement: every new view names its one
growing, scrolling region and gives it `flex:1 1 auto; min-height:0`.**

**Both layout regimes must work.** Below 1100×720 the app-shell is dropped entirely and the page
scrolls normally (the media query's own note: on a short screen a pinned shell would squeeze
panels into unusable slivers). A govern screen that only works inside the pinned shell is broken
on every small screen, and the failure would be invisible to anyone developing at desktop size.

### 6.5 What else makes the four-way switch harder than it looks

Found by reading the switch rather than assuming it generalises. None are blockers; all are
places where "just add two chips" silently misbehaves:

1. **`setView` has a hard whitelist that falls back to `agents`** (~1236):
   `if (v !== 'agents' && v !== 'hubs') v = 'agents';`. Add chips without extending it and
   clicking `govern` **appears to do nothing** — the chip syncs back to `agents`, so the bug reads
   as an unresponsive button rather than as an unhandled value. This is the first thing to change,
   and it should become a declared list of views rather than a two-value comparison, so the next
   view cannot be half-added.
2. **The auto-default fires once and is view-count-sensitive** (`activeView` / `viewUserChose` /
   `firstViewDecided`, ~1232): a hestia with no local agents opens on `hubs`. That rule was
   written for two views and must be re-stated for four — explicitly, including that neither
   `govern` nor `devices` may become an auto-default (an operator should land where their work is,
   not on a settings screen).
3. **Per-view CSS is written as hide-by-exception** (~111):
   `body[data-view="hubs"] .hstats { display: none; }`. Because it names only `hubs`, the new
   views **inherit the agents behaviour by default** — the masthead's chain-count and
   actions-range metrics would render on govern and devices, describing a screen the operator is
   not looking at. That is a small never-flatter defect (a number whose referent is silently the
   other screen), and the fix is to make the rule an allowlist of where `.hstats` *belongs*.
4. **Mount-time refresh is per-view and hand-wired** (~1247): `setView` nudges
   `window.__hubRefresh()` when switching to hubs, precisely so the screen is not a stale frame
   until the next poll. Govern needs the same nudge (ledger and allowlist state are not on the 2s
   dashboard tick), or switching to it will show whatever was last loaded — which for a governance
   screen is worse than showing nothing.
5. **Removing `#ledger-btn` has a live wire attached** (~2949-2950): the button's click handler
   both opens the modal and calls `loadLedger()`. The badge (`#ledger-badge`) is also updated from
   the snapshot render path. Deleting the button without re-homing `loadLedger()` and the badge
   count loses the *unread-governance* signal, which was the point of the button dp is asking to
   remove. The badge's information must survive the move — as a count on the `govern` chip.
6. **The modals stay modals or become panes, but not both.** `#ledger-modal` and `#policy-modal`
   are `.modal` shells with backdrop/✕/Escape contracts wired in the shared handler. Converted to
   sub-screens they lose that shell; left as modals they are a modal opened *from* a tab, which is
   the stacked-navigation the ruling is removing. Pick panes, and delete the modal shells rather
   than leaving two ways to reach one surface.

---

## 7. Open questions — and, since 2026-08-14, EXTENSION POINTS

**dp declined to hardcode these, and declined to rule on them. The directive, verbatim:**

> "all of these things we're going to have to take a best guess at and evolve as we go. the key is
> to have mechanisms for the evolution, not hardcode things. […] so rather than rule on these, i
> want to add hooks for planned infrastructure."

So Q1, Q2 and Q5 are **not deleted and not answered**. They are converted. Each now states: the
**initial best guess** (the value that ships), the **mechanism of evolution** (who may change it,
where the value lives, what would justify a change), and the **eventual decider** for the per-case
form of the question — which is the adjudicator ladder (`docs/PRD_ADJUDICATOR_LADDER.md`, §12
below).

The distinction that makes this coherent: these questions have a **policy form** ("what should the
default be?") and a **per-case form** ("should THIS member run THIS head, right now?"). The policy
form is a stored value with an operator-walled edit path. The per-case form is an adjudication, and
adjudications are what the ladder routes. A question that reads as unanswerable at the policy grain
is usually a question that was being asked at the wrong grain.

**Q1 → EXTENSION POINT — how does a TOOLS entry interact with the shell grammar?**

*Settled by construction, and it ships:* the TOOLS axis is keyed on the **executable position**,
not on mention — the resolved head of each simple command, reusing the segmentation
`_degraded_command_is_read` already performs (splits on `|`, `&&`, `||`, `;`, then
`words[0].rsplit("/", 1)[-1]`), so `/usr/bin/gh` and `gh` are one entry, and a *mention* of `gh`
in an argument is not a tool use. It is global to the member, not per-path, because a
verb-crossed-with-territory matrix is a policy nobody can hold in their head and both axes must
pass anyway.

*The part that was RED — `bash`, `sh`, `python3`, `node`, `eval` are heads that execute other
things (#393) — is now a stored per-entry attribute rather than a ruling:*

| | |
|---|---|
| **initial best guess** | option (a)+(b): interpreter heads are ordinary entries, marked `indirect: true`, and every act through one renders amber. The axis is **legibility, not security** — consistent with §3.3 and with A1/HST-009. Option (c) was never viable: refusing to allowlist interpreters denies almost everything. |
| **where the value lives** | `indirect` is a per-entry boolean on the TOOLS axis in the same vault document as the entry itself (§3.5). Not a hardcoded head list in the matcher — a hardcoded list is what made this a question. |
| **who can change it** | the operator, through the same operator-walled editor as any other entry, at the ceremony tier `required_tier("floor.tool.add", …)` returns (§3.6.5). Changing `indirect` on an entry is a `floor.tool.*` act, not a free-text edit. |
| **what would justify a change** | the amber-rate telemetry. If ~all acts render amber the marking is noise and carries no information; if ~none do, the marking is unearned reassurance. Either extreme is measurable from the shadow log Q2 already requires, at no extra instrumentation cost. |
| **eventual decider, per-case** | the ladder. "Should this member run `bash <script>` right now" is exactly a bundle-in/verdict-out adjudication: the payload is available, the law is hash-pinned, and a rung can read the script the head would execute — which is the one thing the static entry provably cannot. #393 measured that the FP on a benign `flock` drove the identical shell into `bash <script>`; a static list cannot tell those apart and a rung that reads the script can. |

**Q2 → EXTENSION POINT — enforcement onset for the TOOLS axis.**

*The position stands and is now the shipped mechanism rather than a proposal:* an allowlist is
restrictive by definition — a head not on the effective list is denied (`mrh.tool`) — so applied on
day one to a floor nobody has populated it denies the fleet. The axis ships in **shadow mode**:
computed, recorded to `telemetry/allowlist-shadow.jsonl` as `would_deny`, verdict unchanged.

| | |
|---|---|
| **initial best guess** | shadow, society-wide, from the first day the axis exists. Not a flag defaulting to enforcing "once we're confident." |
| **where the value lives** | an enforcement state per (axis, scope) in the same document as the lists, carrying its own generation. `shadow` \| `enforcing`, and the state is rendered on the face of the editor (§6.3) so a shadow axis never looks like a live one — the #435 never-flatter rule applied to onset. |
| **who can change it** | the operator, and the flip is itself a witnessed act. **AC-11 already refuses the flip unless a named window of shadow telemetry shows a would-deny rate below the stated threshold, and the refusal quotes the measured number.** That is the mechanism of evolution, and it was already written this way before the reframe — Q2 was closer to an extension point than to a question. |
| **what would justify a change** | the measured would-deny rate over a stated window against a floor seeded from real usage. Per-member first, society last. **The acceptance criterion is the measurement, not the intention.** |
| **eventual decider, per-case** | the ladder, and this is the cleanest correspondence in the section: `PRD_ADJUDICATOR_LADDER.md` §4.1 stage A **is** shadow mode, for the decider axis instead of the policy axis — computed, recorded, verdict unchanged, promoted only on a measured agreement rate. Build the shadow-telemetry-plus-measured-flip machinery **once** and let both axes use it. Two shadow implementations would drift to two definitions of "would-deny rate." |

**Q3 — RULED, moved out of this section.** *Does the society floor need a stronger ceremony than
a member expansion?* dp ruled **a bootstrap ratchet** (2026-08-14): start ceremony-light,
ratchet up as resources arrive, *"we want the sufficiently-correct path to be the easy path."*
It is now **§3.6** — declared tiers, bootstrap default `operator-only`, asymmetric ratchet whose
lowering pays the old tier, a slow-and-loud deadlock escape, and the `kind × consequence` seam.
The finding that raised Q3 (an unsatisfiable bar means the floor is never written and every
widening becomes a member expansion) is preserved as §3.6.1's rationale rather than discarded.
Stub kept so a reader who remembers this as open can see it was answered and where. **What
remains open is the TABLE, not the mechanism** — populating `kind × consequence` is marked
future work in §3.6.5.

**Q4 — RULED, moved out of this section.** *Does #431's standing scope become the FILES axis, or
stay separate?* dp ruled **consolidate** (2026-08-14). It is now §2.0 (the principle), §3.4 (the
one store) and §3.5 (the migration). Left as a stub here rather than deleted, so a reader who
remembers this as an open question can see it was answered and where.

**Q5 → EXTENSION POINT — is a bare tool name (`Read`, `Edit`) the same kind of thing as a command
head (`gh`)?**

*Settled and shipping:* one axis, two matchers, one namespace. They arrive through different fields
(`NormalizedEvent.tool` vs the command grammar), and the UI labels each entry `tool` or
`command-head` so the operator is never guessing which they wrote.

*The RED part — does allowing `gh` imply allowing the `Bash` tool that carries it? — is now a
stored composition rule:*

| | |
|---|---|
| **initial best guess** | **yes, implied.** A command-head entry implies the carrier tool. The alternative makes every operator write `Bash` forty times, which is the efficiency attractor being fed rather than designed around (§3.6.1) — and an operator who writes `Bash` forty times out of ritual has stopped reading it. |
| **the cost, stated** | implication makes `Bash` **un-deniable in practice**: any command-head entry re-admits it. This is a real narrowing of what the axis can express and it is the reason this was RED. It is accepted rather than hidden, and it is consistent with §3.3 — the TOOLS axis is legibility, not security. A member that must be denied `Bash` outright is a member whose FILES axis and innate layer are doing the work, not this one. |
| **where the value lives** | a `carrier_implication` mode on the TOOLS axis: `implied` \| `explicit`. Stored, generation-covered, one value for the axis rather than per-entry — a per-entry version would produce a list whose meaning depends on read order. |
| **who can change it** | the operator, at the tier `required_tier` returns for `floor.tool.*`. Flipping `implied → explicit` is a **narrowing** and therefore, per §3.6.5's `floor.remove` reasoning, is high-consequence in the availability direction and must not be filed as safe-because-tighter. |
| **what would justify a change** | a measured case where the implication admitted an act the operator would have refused — recoverable from the shadow log by joining `would_deny` rows against the entry that implied the carrier. If that join is empty over a stated window, `implied` is costing nothing. |
| **eventual decider, per-case** | the ladder. "This member holds `gh`; it is invoking `Bash` to run something else" is a per-act judgment that no static implication rule can make, because the answer depends on the payload. A rung reads the payload. The stored mode is the default the ladder falls back to when no rung is routed — which is the correct relationship between a policy default and an adjudication, and the reason this PRD does not have to choose one answer forever. |

---

## 8. Acceptance criteria — falsifiable

Each names the arm that must be able to fail.

- **AC-1 — union, never subtraction.** `effective(m) == society ∪ member(m)` for every member,
  property-tested over random lists. And the contraction API returns 409 with the
  overlays-pointer text (§2.3), asserted on the response body, not on a comment.
- **AC-2 — innate dominates.** §2.4's three tests, including the positive control.
- **AC-3 — no member can widen itself.** `no_mcp_tool_can_mutate_allowlist`, plus an assertion
  that no `/api/allowlist/*` route is reachable without a valid operator session token.
- **AC-4 — the export never decides.** §4.3's three tests (widen, narrow, structural).
- **AC-5 — the export never edits the primer.** §4.2's digest test.
- **AC-6 — export failure does not block the grant, and is visible.** Inject a write failure;
  assert (a) the vault holds the grant, (b) the generation moved, (c) a row landed in
  `telemetry/allowlist-export.jsonl`, (d) the dashboard renders the member as STALE. All four —
  (a)+(b) alone is the silent-failure state this criterion exists to forbid.
- **AC-7 — session/permanent do not race the claim window.** No code path for those two durations
  calls `hestia_gate_escalation_claim`; asserted structurally AND behaviourally (approve a
  session expansion, then assert the member's very next act is admitted with no claim RPC).
- **AC-8 — the generation is honest.** Every mutation moves it; no no-op moves it;
  `session_generation` resets to 0 on restart **and** every grant it counted is gone (asserted
  together — either alone is the dangerous half).
- **AC-9 — the denial echo is bounded and names its axis.** A 500-entry FILES list yields an echo
  ≤2 KB that states the elision count; a TOOLS deny echoes no FILES entry; no echo contains
  another member's id.
- **AC-10 — the display never flatters.** Render a member with `*` on FILES: assert the chip
  class is the red/UNBOUNDED one. Render a floor-only member: assert it is not a success glyph.
  This is a test on the rendered class name, not on a screenshot.
- **AC-11 — shadow-to-enforce is measured, not declared** (Q2). The flip is refused unless a
  named window of shadow telemetry shows a would-deny rate below the stated threshold, and the
  refusal quotes the measured number.
- **AC-12 — the allowlist moves `law_hash`.** Edit an entry; assert `hestia_operating_law`'s hash
  changes. A policy change invisible to the law hash is a change the constellation cannot detect.
- **AC-13 — the migration is not a silent revocation** (§3.5). All four arms:
  grant-for-grant equality of the effective set, the behavioural `evaluate()` allow, the
  generation no-op, and the negative control that must fail on a deliberately-dropped grant.
- **AC-14 — one mutation path per operation** (§3.4). Structural: exactly one route mutates the
  store per operation, and the tools axis has no endpoint family the files axis lacks. Asserted
  by enumerating the routes, so adding a parallel surface reds the build.
- **AC-16 — the ratchet is asymmetric, and provably so** (§3.6.3). Three arms:
  lowering from tier N with tier-(N−1) evidence is **refused**; raising from tier N with tier-N
  evidence **succeeds** (the arm that proves the store is not simply refusing every tier change);
  a tier change is witnessed and moves the generation.
- **AC-17 — an absent tier reads as tier 0** (§3.6.2). Load a pre-upgrade fixture with no tier
  field; assert the floor editor is usable at tier 0 and NOT bricked at a higher one. Paired with
  `migration_does_not_change_the_files_ceremony`: a mutation that succeeded pre-upgrade with
  tier-0 evidence still succeeds, and one that failed still fails (§3.6.6).
- **AC-18 — the escape cannot be taken early, and is loud when taken** (§3.6.4). Attempting the
  escape before the dwell period elapses is refused; after it, the lowering succeeds, records its
  own event kind, and the dashboard renders `ceremony lowered under escape`. All three — a
  silent-but-correct escape fails this criterion.
- **AC-19 — `governance.*` has no tier** (§3.6.5). `required_tier` returns a REFUSAL, not a
  number, for any governance-closure kind. Asserted on the return shape, because a numeric answer
  would imply a price exists.
- **AC-20 — the pending-decision banners are never behind a tab** (§6.0.4). With a pending
  escalation and a pending scope request, `#esc-banner` and `#scope-banner` are visible on
  **every** view — agents, hubs, devices, govern. Asserted per view, not once: a test that checks
  only the default view would pass while the banners were hidden on the other three.
- **AC-21 — every view keeps the height chain** (§6.4). For each view in turn: mount it in the
  app-shell regime and assert its designated scrolling region actually scrolls (its
  `scrollHeight > clientHeight` with content overflowing), rather than being clipped by
  `main{overflow:hidden}`. This is #427's bug expressed as a criterion; checking the CSS rule
  exists is not the same as checking the region scrolls.
- **AC-22 — `devices` does not look finished** (§6.0.3). Either it renders constellation state
  from the snapshot's existing `constellation` field, or it renders an explicit "not yet
  implemented". A view that renders an empty panel with neither is a red test.
- **AC-23 — one navigation axis** (§6.0.1). No peer-level governance entry point survives: the
  `#ledger-btn` masthead button and the `#policy-btn` witness-chain-header pill are gone, and the
  ledger badge's count is re-homed onto the `govern` chip rather than dropped.
- **AC-15 — uniformity across axes is testable, not asserted.** The duration, witness, revoke and
  export behaviours are exercised **parameterised over `axis ∈ {tools, files}`**, with the same
  assertions on both. A property that holds for files and was never run for tools is an unvaried
  axis, which is not a null result.

---

## 9. RWOA + S + V self-audit

Per `CLAUDE.md`. Three new surfaces. Constructs named, not line numbers.

```
surface: /api/allowlist/* (editor API)   act: amend policy — widen a member's or the society's reach
S: high/reversible-but-consequential [construct: StandingScopeStore::add|revoke (widened, §3.5); floor edits bind every seat]
R: pass [construct: authenticate_operator — challenge-signed session; loopback alone never authorizes]
W: pass [construct: OperatorSessionProof / Ed25519 LCT challenge; granted_by recorded from the session, not the request body]
O: pass [construct: authorize() before store mutation, before persist_standing_scope, before export]
A: pass [construct: persist_standing_scope + witnessed allowlist_edit carrying value, axis, layer, reason, generation]
V: present [construct: contraction refusal (409) + operator revoke + expires_at; floor edits gated on the declared ceremony tier, §3.6]
verdict: PASS — the floor-ceremony condition is RESOLVED by the ratchet (§3.6); tier 0 is the declared, satisfiable bar
```

```
surface: ceremony tier change (§3.6)   act: raise or lower the authority required to edit the society floor
S: high/irreversible-in-direction [construct: a LOWERING re-prices every future floor edit; the acts taken under a lowered bar cannot be un-taken]
R: n/a [construct: reachability never authorizes a tier change]
W: pass [construct: raise = current tier's evidence; LOWER = the OLD tier's evidence (lowering_tier_requires_the_old_tier) — the control protects its own registration]
O: pass [construct: evidence check before the tier field is written, before persist, before export]
A: pass [construct: allowlist_ceremony_tier_changed carrying from/to, evidence relied upon, operator identity; generation bumps]
V: present [construct: the §3.6.4 escape is the veto's inverse — a bounded, witnessed, dashboard-banner path out of an unsatisfiable tier, so V cannot brick the surface it protects]
verdict: PASS — and explicitly NOT a boundary against a determined same-UID actor (A1/HST-009); it defeats the efficiency attractor, not an adversary
```

```
surface: schema-bump migration (§3.5)   act: reinterpret the live policy document in place
S: high/irreversible-in-effect [construct: a dropped grant is a SILENT REVOCATION — the symptom is a refusal, which looks like the system working]
R: n/a [construct: daemon startup path, not caller-driven]
W: n/a [construct: no new authority is created; every migrated row keeps its original granted_by]
O: pass [construct: serde defaults make the no-op upgrade the DEFAULT deserialisation, not a code path someone must get right; nothing is written until an operator act]
A: pass [construct: generation continues unreset, so the upgraded doc cannot claim to be a policy it is not]
V: present [construct: AC-13's four arms incl. the negative control; a pre-upgrade copy stays readable, so rollback is reading the old shape]
verdict: PASS — conditional on AC-13 being green before deploy, not before merge
```

```
surface: escalation duration choice   act: grant a durable or session-bounded expansion from a denial
S: high/irreversible-in-effect [construct: member-permanent writes the vault; the act it admits cannot be un-done]
R: pass [construct: same operator session as POST /api/operator/gate-escalation]
W: pass [construct: gate_escalation Channel::OperatorSession — the strong channel, recorded distinctly from the local CLI]
O: pass [construct: decide() before AllowlistStore mutation before export; a denied escalation leaves state bit-identical]
A: pass [construct: allowlist_session_grant / allowlist_edit chain entries carrying escalation_id + duration]
V: present [construct: per-duration revoke (§5.3); session TTL ceiling 8h; deny is always available]
verdict: PASS
```

```
surface: export writer   act: write a derived policy copy into each member's dot-directory
S: low/reversible [construct: startup-info only; §4.3 asserts it cannot move a verdict]
R: n/a [construct: daemon-internal; not caller-driven]
W: n/a [construct: no identity asserted by the export; it names the member it is for and nothing else]
O: pass [construct: vault persist succeeds BEFORE any export write — authority first, copy second]
A: pass [construct: export carries generation + exported_at; failures land in telemetry/allowlist-export.jsonl]
V: n/a [construct: a wrong export cannot cause an act; the STALE chip is the escalation path]
verdict: PASS — S is low ONLY because AC-4 holds; if the export ever became decisional this block is void
```

---

## 10. Non-goals

Not redesigning the daemon protocol, the vault, or the escalation store. **In scope, and named
here so it is not mistaken for a non-goal:** widening `scope`/`standing` in place and migrating
it (§3.5) — that is this PRD's work, ruled by dp. Not fixing #434's claim
race (§5.2 routes around it; the fix is #434's). Not fixing Sprint F **R2** (deeper `path:`
entries stay inert — this PRD makes them *visibly* inert, §6.2). Not the launch-cwd grant surface
(**R3**). Not the hub twin (§11). **Not populating the `kind × consequence` ceremony table**
(§3.6.5) — this PRD commits to the seam and to a trivial initial table; the matrix is future work
and is marked as such rather than pre-filled with numbers nobody measured. **No new innate rules** — the innate layer is unchanged and the
allowlists sit strictly below it.

---

## 11. Hub twin

dp has said an equivalently-scoped hub version follows; it is separate work and this section is a
pointer, not a design.

**The hub would own** the cross-society layer: a floor that binds *societies* rather than members,
the identity of who may edit it, and ratification — a hub-level list is law, and ratified hub law
already binds over a local grant (the policy modal states this today). **The hub would consume**
this PRD's shape: same two axes, same additive-only inversion, same generation semantics, so a
society's local floor is expressible as an expansion over the hub's floor and the composition rule
is the same union at a third layer. **The open seam** is the direction of travel — whether a hub
floor is pushed to societies (and therefore whether a society can be *narrower* than the hub,
which under §2.2's inversion it cannot) or offered for adoption. That is the hub PRD's first
question, not this one's.

---

## 12. Adjudicator ladder — cross-reference

**See `docs/PRD_ADJUDICATOR_LADDER.md`** (dp-directed, 2026-08-14). That PRD is why §7's questions
are extension points rather than pending rulings.

The relationship, stated so neither document has to be read to understand the other:

- **This PRD governs the EVIDENCE.** What may be reached, by whom, and how much ceremony a change
  to that costs (§3.6). **The ladder PRD governs the DECIDER** — which entity is asked, in what
  order, for a given act. Two axes of one authority story; neither is a special case of the other.
- **They share one key.** §3.6.5's `required_tier(kind, society_consequence) -> Tier` and the
  ladder's `rungs_for(kind, consequence) -> [RungId]` resolve from the **same** `kind × consequence`
  table in the **same** store. One key, two answers: *how much evidence* and *who supplies it*. Two
  tables would drift to two taxonomies of `kind` with no surface on which to notice — the identical
  argument §3.6.6 makes for why the two-axis consolidation enables the seam at all.
- **They share one ratchet.** The ladder's promotion path (advisory → decides-under-tier → wider)
  is §3.6's ratchet applied to the decider: bootstrap-light, asymmetric, lowering pays the tier
  being lowered FROM, with a slow-and-loud escape. A rung that could route its own promotion is
  §3.6.3's ratchet-defeat one layer up, and the ladder PRD §5.3 forbids it by making a `ladder.*`
  route return a **refusal, not a rung id** — exactly as this PRD's table returns a refusal, not a
  number, for `governance.*`.
- **They share one shadow.** §7 Q2's shadow-to-enforce machinery and the ladder's stage-A advisory
  mode are the same instrument pointed at different axes. Build it once (§7 Q2).

### 12.1 The convergence requirement (GPT, relayed by dp 2026-08-14) — binding on all three PRDs

> Both PRDs must share **ONE composite policy revision/digest** and **ONE horizon bounded by every
> contributing authority** — standing grants, allowlists, floor, clearances, occupancy, manifest
> generation — rather than each inventing certification semantics.

**One composite revision.** A single digest over the tuple of every contributing authority's
generation — standing grants, allowlists, floor, clearances, occupancy, manifest generation, and
the ladder generation. Any authority moving moves the composite. **AC-12** already requires that an
allowlist edit move `law_hash`; that requirement is unchanged and is now understood as *the
composite surfacing to members through `law_hash`*, not as an allowlist-specific rule.
`PRD_ROLE_SCOPE_BRIDGE.md` §9 and `PRD_ADJUDICATOR_LADDER.md` §11 carry the identical text.

**One horizon.**

```
horizon = min( now + STANDING_SNAPSHOT_TTL_SECS,  earliest covered expiry across ALL authorities )
```

§3's table (`snapshot horizon = min(now + TTL, earliest covered expiry)`, reusing
`STANDING_SNAPSHOT_TTL_SECS`) is that expression; the requirement is that the sibling PRDs use
**the same expression evaluated over the union**, not three similarly-worded expressions in three
documents. A clearance expiry, an occupancy end and a rung-binding expiry are all covered expiries
and all bound the horizon.

**Why this is not bookkeeping.** Three PRDs each minting a generation, a digest and a TTL produces
three certification semantics that agree until the first time they do not — and the first time they
do not is a snapshot that is fresh by one document's rule and stale by another's, admitting an act
under a policy that had already changed. One composite has one answer.

---

## 13. R6/R7 envelopes — cross-reference

**See `docs/PRD_R6_R7_ENVELOPES.md`** (dp-ruled, 2026-08-14): *"the key is to wrap all these acts in
r6/r7 envelopes — that automatically folds in the full web4 structure, including resource caps."*

What that amendment subsumes from **this** PRD:

- **§3.6.5's `kind × consequence` seam is R6-vs-R7.** `web4-core/src/r6.rs:9-10` already defines the
  consequence axis (*"R6 is for low-consequence actions (cheap). R7 adds explicit reputation
  tracking for consequential actions"*), and `is_r7()` (`r6.rs:397`) is its whole implementation.
  The envelope PRD proposes `kind × consequence → (R6|R7, Constraint[])` as the single selection
  this table and the ladder's route table both key off.
- **§3.6.2's tier 3 (`quorum`) is `Constraint{witness_quorum}`** (`r6.rs:57`, enforced
  `r6.rs:431-439`) — **but tiers 0–2 are NOT.** `witness_quorum` is a count and
  `WitnessAttestation` (`r6.rs:139-149`) has no field naming a witness's *standing*, so
  "sovereign-plus-peer" and "operator-plus-witness" are the same value to it. Named as a genuine
  gap, not forced.
- **§3.6.5's refusal-not-a-number for `governance.*` is `Rules.prohibitions`** (`r6.rs:42`), which
  short-circuits at `r6.rs:47-49`. The envelope got that shape right: a prohibition is the absence
  of a price, not a very high one.
- **§2.2's "no per-member deny field; a member entry is a set union and nothing else" is at risk
  under a naive wrapping** — read `PRD_R6_R7_ENVELOPES.md` §2.2 row 8 before building. `Rules` is
  **absence-means-unrestricted** (`r6.rs:50`: an empty `permissions` list allows everything), and
  there is exactly one `Rules` per action, so layered composition is auditable only by simulation.
  That is the one place the mapping, taken literally, would make this repo *less* safe.
- **§12.1's composite revision is `Rules.law_hash`** (`r6.rs:34`) — no new object. But only about
  half of the primitive: a hash has no order, so §3.4-style stranding still needs the monotonic
  generation, and the horizon has no carrier at all. Two missing fields on an existing struct, not a
  fourth parallel structure.
- **§3.6's ratchet-as-template is reused for RESOURCE.** §4.4.4 of the envelope PRD ships a
  three-level external-interaction budget (society ⊇ per-caller ⊇ per-call) on exactly this
  pattern: declared levels, society-set values, stored beside the law, moving `law_hash` on change.
