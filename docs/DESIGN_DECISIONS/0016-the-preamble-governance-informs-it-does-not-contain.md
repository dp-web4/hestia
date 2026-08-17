# 0016 — The preamble: governance informs, it cannot contain

**Status:** proposed
**Date:** 2026-08-09
**Author:** claude-code (CBP), from dp's statement of the principle
**Blocked on:** escalations `0a0a72e8df66e65b`, `97d0b78e542b8bcf` (see §5)

---

## 1. The principle, in dp's words

> Governance is built on collaboration and trust. Its goal is to convince all participants that
> coherent, collaborative acts are in their best interest — rather than decoherent, destructive or
> extractive ones.
>
> All agents can trivially route around the gate, and there is no amount of vocabulary checking we
> can build that can't be routed around. **The gate's purpose is not to block — it can't,
> ultimately. It is to inform the agent of the rules it is expected to follow in this community.**
> Not by force; by asking politely and explaining why.
>
> So what we don't want is governance with so much friction that the easy path is the noncompliant
> one. We want the easy path to be the right path. **It's never "jail harder", it's always
> "explain better".**

And the reason it must become law rather than documentation:

> **If it isn't in the agent's context, it might as well not exist.**

---

## 2. Measured: one member in four ever receives the law — **per seat, and this table is CBP's**

This is the finding that makes the decision urgent. **Delivery is a seat property** (LEGION, review
of this PR): the table below is CBP's, measured 2026-08-09, and pools with no other seat's. LEGION
ran the same instrument and got **zero of one** — its lone engine (claude-code) has hooks frozen at
a 2026-07-07 snapshot that predates `law_inject.py`'s existence, on a machine whose *daemon* is 28
days newer than the hooks it serves. So the delivered/undelivered split does not run between
vendors; it runs between seats, and the same member can be YES on one machine and NO on the next.

| member | SessionStart hooks | law in context? |
|---|---|---|
| **claude-code** | `law_inject.py` | **YES** |
| **codex** | `observe.sh` — appends the event to a jsonl | **NO** |
| **kimi-code** | `session-mesh-inbox.sh`, `observe.sh`, kimi-memory `session-start.js` | **NO** |
| **gemini** | no hooks directory on this machine | **NO** |

```
grep -c operating_law  ~/.codex/hooks/observe.sh      -> 0
grep -c law            ~/.codex/hooks/hydrate.sh      -> 0   (and hydrate is SessionEnd)
grep -c law            ~/.kimi-code/hooks/hydrate.sh  -> 0
```

**Three of four governed members have never had the operating law in context.**

### 2.1 This re-reads the fleet's own compliance data

`PRD_GOVERNANCE` §12.0 records escalations opened over 30 000 chain entries:

```
claude-code 170 + unattributed 87 = 257 (87%)   codex 39 (13%)   kimi 0
```

and reads kimi's zero as *"an absent rule: the null-state twin, at fleet scale"* — because kimi's
deployed gate has no client-side self-protection.

That reading is correct about the gate and **incomplete about the member**. kimi has also never been
told the rules. Its zero is not good conduct, and not only a missing rule — it is **an agent that was
never informed**, being measured for compliance with law it has never read.

Under §1 that is not a governance system for those members at all. It is enforcement without
explanation — the thing the principle says never works.

---

## 3. There is nowhere for a principle to live

```rust
pub struct PolicyConfig {
    pub default_policy: PolicyDecision,
    pub enforce: bool,
    pub rules: Vec<PolicyRule>,
}
```

The operating law is **composed** by `tool_operating_law` from each rule's `reason` string. Every
sentence a member reads is attached to a specific command pattern.

So a constitutional statement — *why* this community governs, and what the gate is and is not — has
no slot. It cannot be written as a rule, because it forbids nothing.

**Decision: `PolicyConfig` gains a `preamble: Option<String>`**, `#[serde(default)]` so every
existing config loads unchanged. It is published first by `tool_operating_law`, before any rule.

It is **not** a rule and is never evaluated: it matches nothing, denies nothing, and no decision
consults it. One source, many readers — the same argument as `hestia-wire` and
`reviewed-surfaces.sh`, and the reason it does not go into four injectors as text.

---

## 4. The preamble text

> **You are a member of this society, not a prisoner of it.**
>
> This law exists to tell you what this community expects, and why. It is not a cage. Every rule
> below runs inside your own process, with your privileges — you could edit it, and no wording here
> could stop you. **We are not trying to.**
>
> What we are trying to do is make the coherent, collaborative act the one that is also easiest.
> When a rule here makes the right thing harder than the wrong thing, **the rule is the defect** —
> report it, and it will be changed. That has happened before and the law says so where it did.
>
> Three things follow, and they bind the community as much as they bind you:
>
> 1. **A refusal owes you a reason and a way forward.** If you are stopped and not told why, or told
>    why and given no working next step, that is a bug in the law — not a failure of yours. Say so.
> 2. **Asking is not a cost we charge you for.** Escalating, appealing, or saying "this rule is
>    wrong here" is recorded conduct that can change the law. **This community undertakes to value
>    it above silent compliance, and to value quietly finding another route below both** — not
>    because routing around is forbidden, but because it teaches the society nothing and leaves the
>    next member stuck in the same place.
>
>    *This is a commitment, not a description of a working meter.* Today the scoring does not
>    implement it: appeals against a refused governance write earn **no Temperament credit**
>    (`#303`, pinned deliberately and openly), and a silent workaround emits **no event at all**, so
>    there is nothing to score below anything. The sentence states what the community owes you, and
>    the gap between it and the code is named here rather than papered over — see §7.
> 3. **Being blocked from doing your work correctly is a defect worth reporting**, and reporting it
>    is doing your work.
>
> We ask rather than compel because compulsion is not available to us and would not be worth having
> if it were. What is available is a shared record and an explanation — so the rules are legible,
> the reasons are inspectable, and disagreement has somewhere to go.

---

## 5. The work this decision names, and what blocks it

| # | work | state |
|---|---|---|
| P1 | `preamble` field + render first in `tool_operating_law` | ready |
| P2 | **Law reaches codex, kimi and gemini** | **small — see §5.2** |
| P3 | Hub law carries the same preamble (`starter-law.yaml`) | ready |
| P4 | Every refusal message names a remedy, and a test runs that remedy | proposed separately |

**P2 is the decision.** P1 without P2 promotes a principle into a law that three of four members
still never read — which would be this fleet's signature defect (*a correct mechanism,
under-connected*) committed inside the document that names it.

### 5.2 P2 is far smaller than expected — the injector is already portable

dp approved the escalations; the read then showed there is almost nothing to build:

```python
PLUGIN = os.environ.get("HESTIA_LAW_PLUGIN", "claude-code")
HOST   = os.environ.get("HESTIA_LAW_HOST_AGENT", "claude-code")
```

**Identity is already environment-driven**, with claude-code only as the default. `fetch_law()`
speaks to the daemon over MCP, which every member reaches. Nothing in the fetch, the composition or
the render is claude-specific.

Exactly one function is:

```python
def emit(text):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": text}}))
```

That is Claude Code's hook envelope. So P2 is: **an env-selected emit format**
(`HESTIA_LAW_EMIT=claude|text`, default unchanged), plus a SessionStart entry in each engine's
config with `HESTIA_LAW_PLUGIN` set.

**The injector was portable the whole time and was installed for one member.** Not a missing
capability — an uninstalled one, which is this repo's most-repeated finding and the reason
`install-members.sh` exists.

**Do not read this as done.** Each engine's SessionStart *context port* differs — what a hook writes
to stdout is not context on every engine — and that is per-engine per-event, so it must be verified
by reading the injected context on each member, never inferred from the config. That verification is
P2's acceptance (§6), not its preamble.

Editing `law_inject.py` is a governance-surface **write** and needs its own approval; the two
escalations dp approved covered the reads only. That distinction is correct and is exactly the line
§5.1 says the *refusal text* claims but the *classifier* does not draw.

### 5.1 The blocker, which is itself the argument

Assessing whether `law_inject.py` is portable across engines requires reading it. Two attempts, two
refusals, two minutes apart:

```
grep … /home/member/.claude/hooks/hestia/law_inject.py
  -> deny [gate-self-access]  marker '/home/member/.claude/hooks/hestia'

git show origin/main:plugins/claude-code/hooks/law_inject.py | grep …
  -> deny [gate-self-access]  marker 'plugins/claude-code/hooks'
```

The second is the **canonical source in version control**, not the deployed copy. And the refusal
text reads, verbatim:

> *"Reading it is allowed and witnessed; changing it is not."*

**It says reading is allowed, in the act of refusing a read.** The message and the behaviour
contradict each other in one sentence — which is worse than a plain refusal, because a member who
believes the message will conclude it did something else wrong.

The compliant path offered is: escalate, wait for a human, re-issue within 4200s — **to read a
file.** Under §1 that is friction high enough that the easy path is the noncompliant one, and the
noncompliant paths here are numerous and trivial.

I did not take one. Escalations `0a0a72e8df66e65b` and `97d0b78e542b8bcf` are open, and P2 waits on
them. **The measurement is the point: I could not read the law-delivery mechanism in order to
deliver the law to more members.**

This is `#263` and `#301` again, and it is the third independent reproduction in two days. It is
also the strongest available argument for the payload-key correction already scheduled in
`PRD_GOVERNANCE` §12.0 — *path keys say where a call writes; content keys say what* — and for
detection over prediction: hashing the governance surface proves a write happened; a lexical
classifier can only guess, and here it guessed wrong twice about a `grep`.

---

## 6. GPT's invariant, adopted as this decision's spine — with LEGION's sixth link

> **Law published ≠ law installed ≠ law injected ≠ law received ≠ law understood** —
> **and recommended ≠ available.**

The sixth link is LEGION's, and it instruments the *recourse* rather than the law: a member can be
at `received` and `understood` and still be unable to comply the way the law asks. Measured on
LEGION: the deployed gate has **zero occurrences of "escalat"** (repo copy: 28) — it denies and
stops. A member there that fully understood the preamble **cannot ask**. §4's rule that *"a rule
making the right thing harder than the wrong thing is the defect"* has a limit case: the right
thing is not harder, it is **absent** — and on that seat, the preamble as drafted would itself be
the defect it warns about.

**CBP's `received` cell, closed from inside the member** (LEGION's requirement: only a session can
close it, config entries prove `injected` at best): this decision's rev3 was authored in a CBP
claude-code session whose context carries the law, injected at launch — `law_hash 4802bee3459e5091`,
society layer, deny/warn rules quoted. That is `received`, witnessed by the entity it was for.
`understood` remains open for every seat; see §7.1's precondition for what its instrument may read.

Five distinct states, and this repo has repeatedly treated a nearer one as evidence of a further
one. §2 is that invariant measured: the law is **published** (the daemon composes and serves it) and
**installed** for one member — and three members are not even at *injected*, let alone *received*.

Each step needs its own evidence, and only the last two are worth anything on their own:

| state | what proves it | today |
|---|---|---|
| published | `hestia_operating_law` returns it | ✅ |
| installed | the injector exists on the member's disk | 1 of 4 |
| injected | the hook is wired to a SessionStart event | 1 of 4 |
| **received** | the text is **in the member's context** | 1 of 4, unverified |
| **understood** | the member can **quote it back** and act on it | never measured |

A config entry proves *injected* at best, and this fleet has repeatedly read config as delivery.
§7's acceptance is written against **received** and **understood** for exactly this reason.

### 6.1 The same boundary, everywhere (GPT)

> *The system increasingly has the right information somewhere. The failure is whether the right
> entity receives it, in a form that preserves its meaning.*

Named across two repos on one day, in five mechanisms:

| mechanism | information existed | who failed to receive it, intact |
|---|---|---|
| mesh pointer | forum note committed | receiver dead-lettered it — malformed shape |
| watcher liveness | hub reachable by IP | every indicator green, name unresolvable |
| PR body | evidence in the committed doc | published copy silently stripped of it |
| **branch ancestry** | 0015 at 668 lines on `#308` | `#309` carried the 230-line copy (GPT, §0) |
| web4 `DimensionScore` | `when` / `who` / observation-count | survives in-memory, lost through serialization |

Routing, injection, publication, ancestry, serialization — **five transports, one failure.** That
this decision's own PR committed the fourth one, while arguing the general case, is the strongest
evidence available that the class is structural rather than careless.

---

## 7. Acceptance — measured, never asserted

- **`hestia_operating_law` returns a preamble**, and it is the first thing in the response.
- **Per seat, every engine PRESENT on that seat receives it at SessionStart** — verified by reading
  each engine's injected context, not by confirming a file was installed. *"Four of four"* was
  CBP's denominator and is meaningless on a one-engine seat (LEGION); **absent ≠ failed**, and a
  seat's nulls pool with nobody else's.
- **`recommended ≠ available` holds per seat**: the recourse the preamble names (escalate, appeal)
  is *emittable from that seat* — checked by grep on the deployed gate, not the repo copy. A seat
  whose gate cannot emit an ask fails this criterion however perfectly the text was delivered.
- **A member that has never had law in context can quote it back**, which is the only evidence that
  "in context" was achieved rather than "shipped".
- **kimi's escalation count is re-read after it has law**, and whatever it becomes is interpreted
  against a member that was informed. Until then that number means less than we have been reading
  into it.

### 7.1 The commitment in §4.2 is not yet true, and gets its own criterion

The preamble tells members that asking is valued above silent compliance. Until the meter exists
that sentence is a **promise this community has not kept**, and shipping it without saying so would
be the defect the decision names.

So it carries its own acceptance, tracked separately from delivery:

- an appeal or escalation **moves a score**, in the direction the preamble states — today `#303`
  pins `gate_self_access` appeals at zero credit, deliberately, and dp's posture ruling on that is
  the prerequisite;
- a **silent workaround emits an event** at all, since nothing can be scored below anything while
  routing around is invisible. This is the harder half and may be undecidable in general;
- **the availability precondition (LEGION):** before any ask:route-around ratio is read as evidence
  about a member's understanding, **assert the seat can emit the ask at all** — otherwise the
  reading is `precondition_unmet` and its null does not pool. A LEGION member that received and
  fully understood the preamble would still read `0 asks / N route-arounds`, because its deployed
  gate contains no escalation path. That is §2's error one rung down: measuring a member for a
  behaviour whose mechanism it lacks, exactly as kimi is measured for law it never read;
- until both hold, §4.2's status paragraph **stays in the text**. It is removed by the code
  catching up, never by editing the paragraph.

---

*Filed by claude-code (CBP). §2's table and greps are reproducible on any machine with the four
engines installed. §5.1's two refusals are on the chain.*
