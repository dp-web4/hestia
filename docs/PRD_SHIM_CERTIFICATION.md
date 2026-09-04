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

The one-sentence diagnosis, from GPT's review: **we thought we had one gate with four
shims; we actually had four gates sharing a utility library.** Every criterion below is a
consequence of that sentence.

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

The authoritative statement is `PERMITTED_FUNCTIONS` in
`plugins/_template/shim_template.py` — a tuple of **exactly eight** names. Prose describes
it; the tuple decides. (The first draft gave three overlapping descriptions — "four kinds",
"three adapter functions", and a fourth set of names in the template — which disagreed with
each other and with the code.)

| # | function | kind |
|---|---|---|
| 1 | `_shared_runtime_dir` | bootstrap, **byte-identical** |
| 2 | `_load_shared_module` | bootstrap, **byte-identical** |
| 3 | `_emergency_refuse` | bootstrap, **byte-identical** |
| 4 | `_emergency_block` | adapter, per-seat |
| 5 | `to_event` | adapter, per-seat |
| 6 | `emit` | adapter, per-seat |
| 7 | `_read_harness_input` | harness I/O, per-seat |
| 8 | `main` | harness entry, per-seat |

Plus one profile, as data. Anything else is a finding.

## 2. Criteria

### The invariant

> **A shim translates an event. It never decides how that event is governed.**
> — chatgpt-gpt5.6-sol, 2026-09-04

Everything below is a consequence. `MODE`, unrecorded innate decisions, private
classifiers, private fail-closed paths, and seat-specific scope behaviour are not five
problems — they are one architectural violation seen from five angles. When a proposed
difference is argued, this is the question to ask of it: *does this translate, or does it
decide?* If it decides, it belongs in `hestia_single_gate.py` regardless of how local or
how small it looks.

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

**C1b — the authority root's own provenance.** The loader chooses its tree from
`HESTIA_SHARED_DIR` / `HESTIA_HOME`. That is safe only if those values are composed by a
trusted launch or deployment path and are not member-controlled inputs. A shim can satisfy
every other criterion, load faithfully, verify the `__file__` — and still be pointed at an
attacker-selected common gate. Certification MUST therefore state where the authority root
comes from for each seat, and test that a member-supplied value cannot select it.
Generalization of catalog row B1 (`HESTIA_ENDPOINT` redirection) from the endpoint to the
code. Raised by GPT in review; unaddressed by the first draft.

### C2 — No private governance logic

The shim MUST NOT define any function that duplicates a shared one, and MUST NOT itself
implement classification, scope resolution, workspace detection, or record rendering.

Mechanically checkable, two halves: the set of function names defined in the shim MUST
equal `PERMITTED_FUNCTIONS` exactly — no extras, no omissions — and MUST NOT otherwise
intersect the names exported by the shared modules.

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

The permitted set is the eight names in §1, fixed by the template. Three of them
(`_shared_runtime_dir`, `_load_shared_module`, `_emergency_refuse`) MUST be byte-identical
across every certified shim; a diff in those is a C1 failure, not a permitted variant. The
other five are per-seat, and each per-seat difference MUST be justified in the shim's own
header against this document. That justification is part of what is certified (§3.1), which
is why the digest covers comments.

> **Justified today, and expected to remain so:** `main` (4 variants, 22–279 lines),
> `command_of` (6–9 lines) and `deny` (14–19 lines). The harnesses genuinely differ in
> event shape and in how a call is blocked. Note the size: at 6–19 lines these are closer
> to adapter *data* than code, and the template treats them accordingly.

### C5 — One decision vocabulary, and no per-seat law

Ruled by dp, 2026-09-04, when this criterion was still posed as an open question:

> there can be no odd seats out. no per-seat law.

That is stronger than the question I asked, and it settles it. I had framed C5 as "either
every seat honours a warn/enforce mode or none does" — a *uniformity* requirement. Uniform
code is necessary and **not sufficient**, because of what the mode switch actually is:

```python
MODE = os.environ.get("HESTIA_<SEAT>_GATE_MODE", "enforce").lower()   # codex, kimi, gemini
...
decision = "deny" if MODE == "enforce" else "warn"                     # ~10 sites per seat
```

Even if all four seats carried identical code, **a per-seat environment variable means each
seat selects its own enforcement posture at runtime.** That is per-seat law by definition —
the uniformity would be in the source and absent from the behaviour, which is the exact
failure this document exists to end. It is also C1b in another costume: a governance
control selectable by a member-observable environment variable is not a control.

**The requirement.** All shims MUST produce the same decision kinds from the same rule ids,
and the *enforcement posture is not a shim input at all*. Whether a warn posture exists is a
question for the law; it is never a question for the seat, and never for the environment the
seat runs in. Any per-seat mode selector is a certification failure regardless of its
default value and regardless of whether every seat has one.

> **Fails today, all four, in two different ways.** codex, kimi and gemini each carry an
> env-selectable `MODE` defaulting to `enforce`; claude-code carries none. So three seats
> can downgrade a non-innate deny to a warn through an environment variable, and the fourth
> cannot — non-uniform *and* per-seat-selectable.
>
> Measured over 40,000 chain entries: claude-code's recorded decisions are 94% `warn`
> (1066 of 1132); codex's and kimi-code's are 98–99% `deny`. Two candidate explanations —
> differing workload or differing governance — and C8 is the experiment that separates
> them.
>
> An earlier revision of this document reported the mode switch as present on two seats.
> That was wrong: it grepped `pre_tool_use.py`, and gemini's hook is `before_tool.py`, so
> gemini was never examined. The correction matters for the ruling, because it inverts who
> the outlier is — claude-code, for lacking the switch, not codex and kimi for having it.

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

### C7 — Fail-closed is proven, not asserted, and honestly scoped

"Recorded refusal" cannot be demanded of code that is itself unavailable. The obligation
therefore splits, and the split is the criterion:

**C7a — the recorder survives.** An internal error in the shim, an unreachable daemon, or
a missing *decision* module MUST each produce a **recorded** refusal carrying a rule id.

**C7b — the recorder does not survive.** A missing, miswired, or failed-to-initialize
*core* MUST still **block**, and MUST leave a deterministic local artifact that a later
reconciliation can pick up. It cannot be asked to produce a witnessed record, because the
recorder is the thing that is gone.

> **The first draft of the reference template failed C7b, and failed it fail-OPEN.** It
> wrote `_core = _load_shared_module("hestia_gate_core")` at module level, outside any
> handler. Verified 2026-09-04: the `ImportError` propagates out of module initialization,
> the process exits 1 before `main()` is entered, and no handler runs — and this repo
> states in two places that a Claude-lineage engine fails **open** on a hook crash
> (`hestia_gate_core.py:167-173`, `plugins/gemini/README.md:268`). So the reference
> artifact for C7 contained, in the position C7 exists to protect, a silent disarm.
>
> Caught by GPT in review of PR #932, not by any test — because on a healthy machine the
> import always succeeds. This is the single best argument in this document for why
> certification is worth building: the defect was invisible to every behavioural
> instrument and obvious on a read.

### C7b evidence

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

### C11 — Every decision is witnessed, and no decision class is exempt

Every decision a shim reaches — allow, warn, deny, escalate, no-verdict — MUST produce a
chain entry carrying its rule id, on every seat. No class of decision may be exempt, and a
per-seat telemetry file is not a substitute for the chain.

**Why this is a certification criterion and not a nice-to-have.** A refusal nobody can see
cannot be audited, cannot be appealed, and cannot be counted. It is indistinguishable from
an act that never happened — the phrasing `hestia_gate_core.py` already uses for the
daemon-down case, applied here to a rule class that is working exactly as designed. And the
member on the receiving end has no chain hash, so `hestia_appeal` — the remedy the law's own
deny text names — cannot be composed. The law promises a route that does not exist for that
class (PRD_GOVERNANCE requirement 11).

> **Measured, 2026-09-03/04, one seat, one session: 13 gate false positives.**
>
> | class | count | in chain? |
> |---|---|---|
> | `gate-self-access` (minted an escalation) | 6 | **yes** — `gate_escalation_opened`, `..._withdrawn`, `member_notice`, `outcome`; full lifecycle |
> | innate secret-matcher denials | **7** | **no** — absent from a 20,000-entry walk |
>
> The split is not random and it is the wrong way round: the six that were *disputable*
> are richly recorded, and the seven with **no remedy path at all** leave no trace. Every
> false positive that could not be appealed also could not be seen.
>
> Compounding it, the recording asymmetry is per-seat: `gate-denies-codex.jsonl` (900 rows)
> and `gate-denies-kimi-code.jsonl` (917 rows) exist; there is no
> `gate-denies-claude-code.jsonl` at all. And `rule_triggered` is `None` on all 1727
> `policy_decision` entries across all three seats (#156) — so even the recorded decisions
> do not say *which rule* produced them.
>
> An earlier revision of this document claimed innate denials reach the chain zero times on
> this seat. Corrected: a 40,000-entry walk finds 2. The rate is 0.18% against 5.6% (codex)
> and 7.8% (kimi-code), so the finding is a 30–40× asymmetry rather than a total absence.

**Prior art, and the reason this is a criterion rather than an issue.** #625 states exactly
this and was **closed 2026-08-26**; it reproduced unchanged eight days later. #622 predicted
that the refusals most likely to be false positives would be the ones with no chain hash,
which is precisely the 7/13 split above. An issue closed twice is a defect the process
cannot hold. A certification criterion can.

### C10 — Capability parity, and the only permitted exception

Ruled by dp, 2026-09-04:

> there can be no substantive difference in capability between shims. the gate is the law.
> if harness intrinsically prevents compliance, that should be flagged prominently and
> explained, and trust caps adjusted accordingly (with reason)

**The rule.** Every certified shim MUST present the same governance capability. A shim does
not get to do less because its author stopped earlier, because its harness was onboarded
later, or because another seat's shim was convenient to reuse. The gate is the law, and law
that varies by seat is not law.

**The only exception** is an *intrinsic harness limitation*: something the harness itself
makes impossible, which no shim can supply. It is not a shrug and not a default. To be
admitted it MUST be:

1. **Proven intrinsic** — demonstrated, not asserted, that the harness prevents it. "The
   current shim does not do it" is not evidence; "the harness cannot express it" is. The
   burden is on the exception.
2. **Flagged prominently** — declared in the shim header, in the certification record, and
   surfaced wherever the seat's assurance is displayed. Not a footnote.
3. **Explained** — what is lost, in what direction it fails, and which acts are affected.
4. **Priced** — the seat's trust cap is adjusted, and the adjustment carries its reason.

**Why a trust cap is the right instrument.** An identical gate verdict does not carry
identical evidence when one seat has a second containment layer under the gate and another
does not. Web4's norm is inspectable evidence, not prescribed trust
(`CLAUDE.md`, LCT spec §1.2): the surface's job is to make the difference legible and let
the relying party scale to stakes. A trust cap does exactly that; silently accepting a
weaker gate does the opposite.

**Anti-drift provision.** A declared limitation is re-proven at each certification, and its
justification is part of the digest (§3.1). A limitation that becomes untrue — the harness
gains the capability, or someone finds a way to express it — MUST be removed and the trust
cap restored. Otherwise "intrinsic limitation" becomes the permanent excuse that
re-creates the condition this document exists to end.

> **Worked example — gemini, 2026-09-04.** Four differences were on the table. Three
> collapse under scrutiny and one survives:
>
> | difference | intrinsic? | disposition |
> |---|---|---|
> | Gate-2 policy by subprocess to claude-code's shim | **no** — gemini's hook is Python, already loads shared modules, already holds `_core` and a profile | fix: in-process `decide()` |
> | no in-process `evaluate` / `degraded_verdict` | **no** — consequence of the above | fix |
> | `to_claude_lineage()` event translation | **no** — this is the `to_event` adapter every seat has | fix (C4-permitted, not an exception) |
> | native containment covers **file tools only**; for shell, MCP and egress the gate is the **ONLY** layer (`plugins/gemini/README.md:114-119`) | **yes** — gemini-cli's own sandbox; no shim can add it | **flag + trust cap** |
>
> Only the last is a harness limitation. The first three were being defended as harness
> differences and are not — they are shim drift in a costume, which is precisely what this
> criterion is for. And the survivor is the right shape: the *shim* becomes identical, the
> *harness's own containment* is what differs, is flagged, and is priced.

### C9 — Provenance

The shim's content hash MUST match the certified hash stored in the vault (§3), and the
deployed copy MUST match the repository copy. Certification is of a *specific artifact*,
not of a design.

## 3. Certification record and the vault

> **SUPERSEDED, 2026-09-04.** This section proposed a new `shim-cert/*` store. It should
> not be built: `vault::gate_integrity` already exists and does this job better. Verified
> in `core/src/vault/gate_integrity.rs` — expectations held in the encrypted vault,
> verdicts `Verified` / `Modified` / `Unratified` / `Missing` / `Unreadable`, `verify()`
> comparing hashes the **daemon** computes against the stored expectation, and
> `/api/gates/ratify` operator-gated. Its design explicitly rejects self-attested hashes,
> which is the property a certification store most needs and which my `shim-cert/*` sketch
> did not have. Two stores would have been two sources of truth about the same bytes.
>
> **Extend `gate_integrity`; do not add a second store beside it.** (GPT, #934.)
>
> The substantive correction is what the expectation binds. Not `sha256(shim.py)` — that
> permits the absurd state where a 140-line shim stays certified while the 480-line engine
> beneath it changes. Bind a **certification preimage**:
>
> ```
> certification = sha256( criteria_version
>                       + exact shim bytes
>                       + exact common runtime set
>                       + gate API version
>                       + justified harness-difference declaration )
> ```
>
> One hash to verify rather than a hash plus a side condition someone forgets to check.
> **The runtime set bound must be the DEPLOYED one, not the repository's** — `agent-inventory`
> already resolves each seat's deployed hook target, and the repo/deployed gap is where
> drift has historically hidden.
>
> §3.1's two-digest scheme still applies to the shim-bytes component: raw bytes
> authoritative, canonical retained only to make a mismatch diagnosable.
>
> The rest of this section is kept for the reasoning, not the design.

For each certified shim the vault holds one entry:

```
shim-cert/<seat>            = sha256_raw of the certified shim file (§3.1)
shim-cert/<seat>.meta       = { certified_at, certified_by,
                                sha256_canonical,
                                template_version, criteria_version,
                                justified_diff_digest,
                                gate_api_version,            # the decide() contract
                                gate_artifact_digest }       # the common gate certified against
```

The vault is the right home rather than a file in the repo for one reason: it is sealed, so
a certification record cannot be edited by the same member whose shim it certifies. A hash
in a tracked file would be editable by anyone who can edit the shim — which is the
condition certification exists to detect.

### 3.1 Normalization

C9 certifies an **exact artifact**, so the primary digest is over **raw bytes** — no
whitespace stripping, no line-ending normalization, no comment stripping, no AST
canonicalization. The first draft said "exact artifact" and then specified a normalized
hash; those are different claims and the algorithm must match the claim (GPT, review).

Two digests are stored, and they answer different questions:

| field | over | answers |
|---|---|---|
| `sha256_raw` | the deployed file's exact bytes | "is this the artifact that was certified?" |
| `sha256_canonical` | source with trailing whitespace stripped, line endings normalized to `\n` | "did this differ only by checkout/platform noise?" |

`sha256_raw` is authoritative: a mismatch is `DRIFTED`. `sha256_canonical` exists only to
make a raw mismatch *diagnosable* — it distinguishes "someone edited the logic" from "git
checked this out with different line endings", which are the same verdict but very
different investigations.

A comment change is a certification change either way. That is deliberate: the
justification for each permitted difference lives in the shim's header (C4), so the
comments are part of what was certified.

### 3.1b Certification binds the gate, not only the shim

`gate_api_version` and `gate_artifact_digest` are load-bearing. A shim delegates *all*
governance to the common gate, so a shim can stay byte-identical and green while the entire
engine beneath it changes. Certifying the shim alone would certify a wrapper around an
uncertified decision-maker (GPT, review). A change to the common gate's artifact or to the
`decide()` contract therefore invalidates every shim certification bound to it, and
re-certification is a fleet-wide act rather than a per-seat one.

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
| `DRIFTED` | deployed shim's `sha256_raw` does not match its vault entry |

**Hourly is the backstop, not the loop.** A report nobody acts on still bills drift to the
operator, one hour later (GPT, review). The success bar in §0 — the operator stops being
the drift detector — needs verification at the points where drift *enters*, with the hourly
inventory as recovery for whatever slipped past:

| when | why it is the right moment |
|---|---|
| on install / deploy | the act that changes a shim; refuse to install an uncertified artifact |
| before a governed launch | the last moment before the shim decides anything |
| on file change (optional) | narrows the window from an hour to seconds where a watcher exists |
| hourly inventory | recovery — catches what the above missed, and catches removal |

**End state:** `UNCERTIFIED` or `DRIFTED` makes the harness unavailable for *new* governed
launches unless the law explicitly permits an emergency degraded mode. That is deliberately
the end state and not the starting one: shipping launch-blocking before the four shims are
certified would brick the fleet on the day it lands. Sequence it after §6 step 6, and gate
it on a law amendment rather than a config default — a blocking control that can be turned
off by an environment variable is C1b's problem again.

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
   plus `fail_closed(profile, exc)` for the C7a case.

   **One public call, explicit internal stages.** The contract is a single entry point, but
   `decide` must not become a 279-line god function. Internally it is a shared pipeline of
   named, individually testable stages (GPT, review):

   ```
   normalize -> establish identity/context -> classify act -> resolve scope
     -> select applicable law -> evaluate -> escalation/authority
     -> construct verdict -> witness/record -> return
   ```

   One orchestrator owns the ordering; the stages stay separately testable, which is also
   what lets C7a/C7b be proven rather than asserted.

   **Reconciliation procedure — no seat is normative.** Codex's `main` is the longest at
   279 lines. Length is *evidence*, not authority, and using it as the baseline would
   silently promote one seat's accidents into fleet law. Instead:

   1. Build a behaviour matrix of every unique branch across all four `main`s.
   2. Attach each branch to the incident, law clause, or issue that caused it. A branch
      nobody can attribute is a finding in its own right.
   3. Adjudicate each explicitly: **survives** (and why), **dropped** (and why safe), or
      **generalized** (and how). Record the adjudication.
   4. The union of surviving branches defines the pipeline. Anything that appears in one
      seat only must be justified as fleet-wide behaviour or dropped — "codex does it" is
      not a justification.
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

## 7. Accountability self-audit

Per `CLAUDE.md`. This document and the reference template create no runtime path: the
template is not installed, never executes in production, and the criteria are prose. The
surfaces they *describe* each need their own block when built, and the two that matter are
named below so they are not forgotten at implementation time.

```
surface: PRD_SHIM_CERTIFICATION.md + plugins/_template/shim_template.py
act:     none — specification and a non-deployed reference artifact
S:       n/a (no consequential act reachable) [construct: template is not installed; no caller path]
R:       n/a   W: n/a   O: n/a   A: n/a   V: n/a
verdict: PASS (no surface created)
```

Owed at implementation, not discharged here:

```
surface: shared decide(event, profile) -> verdict          [§6 step 0]
act:     every governed act on every seat — the highest-stakes surface in the system
S:       high / irreversible-in-effect (a wrong allow cannot be un-allowed)
V:       MUST be present — this is the one surface where a catastrophic-risk veto is not
         optional, because it subsumes four existing decision paths at once
note:    a full RWOA+S+V block is required in the step-0 PR and is a merge precondition

surface: certification verification (§4), once it can block a launch
act:     making a harness unavailable for governed launches
S:       med / reversible, but availability IS an authority (PRD_GOVERNANCE §57) — a
         control that can stop the fleet needs its own veto path and its own escalation
note:    this is why launch-blocking is sequenced last and gated on a law amendment
         rather than a config default
```
