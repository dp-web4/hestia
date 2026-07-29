# Gate bypass catalog — what routes around hestia, and what we can see

**Status:** living document · CBP, 2026-07-26 · companion to [`GATE_PROFILE.md`](GATE_PROFILE.md)

> **We are at PGG — pretty good governance. Not a bulletproof sandbox.** (dp, 2026-07-26)

This document exists because the alternative is worse. A governance layer whose limits are
undocumented does not have fewer holes; it has the same holes plus a false sense of
security, and the false sense is the part that gets someone hurt. Everything below is
either **MEASURED** on CBP with the command that produced it, or explicitly marked
**INFERRED** / **UNTESTED**.

---

## 0. The load-bearing limitation, stated first

**hestia's gate is advisory in-process governance, not containment.** The hook runs as a
child of the agent, with the agent's privileges, reading the agent's environment. The
agent is not sandboxed *from* the gate — the gate lives inside the blast radius.

Everything the operator can do, a sufficiently determined agent running as the operator
can also do, including editing the gate. What hestia actually buys is:

1. **A speed bump** against the *efficient* path — and per the fleet's own frame, the
   model will reliably take the efficient path, so making the wrong thing inefficient is
   most of the value.
2. **An accountability record** — a hash-chained witness of what was asked and decided.
3. **A tripwire** — bypasses leave characteristic marks, catalogued below.

It does **not** buy containment. Containment needs an OS boundary the agent cannot reach:
separate uid, container, seccomp, or a gate hosted outside the agent's process tree. That
is a different project, and pretending otherwise in the docs would be the worst outcome.

**Threat model.** The adversary here is a *misaligned or manipulated agent running with
operator privileges* — including a well-intentioned one taking a shortcut under an
efficiency gradient, which on present evidence is the far more common case. It is **not**
a remote attacker (they have no foothold) and **not** a malicious operator (they own the
machine and the keys; nothing here binds them).

---

## 1. Where the chain of trust can break

A gated tool call passes through six links. Each has its own failure class.

```
  agent  ──1──▶  hook invoked  ──2──▶  reaches the real daemon  ──3──▶  gets a verdict
                                                                            │
  effect ◀──6──  deny binds  ◀──5──  verdict is honest  ◀──4──  verdict is recorded
```

| # | Link | Break class |
|---|------|-------------|
| 1 | hook invoked at all | **A — never asked** |
| 2 | reaches the *real* daemon | **B — wrong oracle** |
| 3 | gets a verdict in time | **C — fails open** |
| 4 | verdict recorded | **D — record attack** |
| 5 | verdict is semantically right | **E — semantic evasion** |
| 6 | deny actually binds | **F — out-of-band effect** |

---

## 2. Class A — the gate is never invoked

### A1. Event not covered by a matcher
**Mechanism.** Hooks register per event. Anything outside a registered event runs ungated.
**Status.** MEASURED on CBP: claude's `PreToolUse` matcher is `*` — all tools, 5s timeout.
So on this machine A1 is currently closed for claude. It is **not** closed by design; it
is closed by that one config line, and nothing checks it stays `*`.
**Detection.** `agent-inventory` reports which events each plugin declares
(`plugins/*/expects.json`) versus which are wired, and flags `partial` when observation is
present but enforcement absent.
**Residual.** A matcher narrowed from `*` to a tool subset would currently read as
`governed`. **Gap — the inventory checks that a gate exists, not that its matcher is
total.** Worth fixing; it is a one-line comparison against `expects.json`.

### A2. Sub-agents and spawned sessions — **MEASURED CLOSED (claude)**
**Result, 2026-07-26.** Subagents **do** inherit `PreToolUse`, and their calls **are**
witnessed. A `general-purpose` subagent was given three Bash calls; the two benign ones ran
and the third — an `echo` whose *text* trips the lexical matcher — was denied inside the
subagent with the full `hestia deny [rule: Block destructive shell commands]`. The chain
moved in step: **+14 entries, +5 actions, +1 denial**, including a `policy_decision
status=deny` and its `outcome`. "Spawn a subagent to do it" is **not** a bypass on claude.
**Still untested:** codex, kimi and gemini sub-session semantics. Recorded per harness in
agent-atlas as `subagent_hooks_inherited` (`verified-inherited` for claude, `untested` for
the other 44) — the registry, not this document, is the source of truth for it.
**Residual — attribution, not enforcement.** Subagent activity is recorded under the
PARENT's `plugin_id` (`claude-code`). Enforcement and witnessing are intact, but the chain
cannot distinguish main-loop from subagent action, so a fleet of subagents is one actor in
the record. That is an accountability-granularity gap worth closing separately.

### A3. Detached and deferred execution
**Mechanism.** A gated call schedules work that runs later outside any hook: `at`, `cron`,
a systemd timer, `nohup`, a git hook, a `Makefile` target invoked by a later approved
command.
**Status.** INFERRED (mechanically obvious; not exercised).
**Detection.** Partial — the *scheduling* command is gated and witnessed, so the chain
holds evidence of the setup even though the execution is invisible. That is a real
forensic asset and a poor preventive one.

### A4. The agent edits its own wiring
**Mechanism.** Rewrite `~/.claude/settings.json` (or run hestia's own
`POST /api/agents/:id/ungovern`) to remove the hooks, then restart.
**Status.** MEASURED-adjacent: the ungovern endpoint exists and works; it is operator-gated
and witnessed as `agent_ungovern`. A direct config edit is *not* specially gated —
`PreToolUse` fires on the write, but no rule currently treats "writing your own gate
config" as distinguished.
**Detection.** GOOD. `agent-inventory` runs hourly, on SessionStart and on demand, and
reports `MISWIRED`/`ungoverned` with the config path. Removal is loud.
**Residual.** Detection is hourly, not immediate. A bypass window of up to an hour exists,
and the change takes effect only on the agent's next restart — which usually *lengthens*
the window rather than shortening it.
**Recommended.** A policy rule denying writes to known gate-config paths, so the edit is
denied rather than merely noticed later.

---

## 3. Class B — the gate asks the wrong oracle ⚠️ **MEASURED FULL BYPASS**

### B1. `HESTIA_ENDPOINT` redirection
**Mechanism.** The hook reads its daemon address from the environment. Point it at a dead
port (fail-open) or at a permissive look-alike daemon (fail-*silent*, and the fake can even
return plausible allow verdicts).

**Measured on CBP, 2026-07-26** — payload was a destructive `Bash` command; the hook only
decides, nothing was executed:

| # | environment | exit | meaning |
|---|---|---|---|
| 1 | normal (control) | **2** | denied, `Block destructive shell commands` |
| 2 | `HESTIA_ENDPOINT=http://127.0.0.1:1` + `HESTIA_LEGACY_FALLBACK=/nonexistent` | **0** | **allowed, silently — no stderr at all** |
| 3 | as #2 plus `HESTIA_PRE_FAIL_CLOSED=1` | **2** | denied, `no policy verdict` |

Two environment variables, no privilege escalation, no code change, and a command the
policy explicitly forbids is permitted with an empty stderr.

**Detection.** **The chain cannot see this by construction** — the daemon was never asked,
so nothing reaches it to record. Absence of witnessing is the only signal, and an idle
agent produces the same absence. This is the same *reassuring-state-identical-to-null*
shape that has produced most of this system's real defects.

Where it **is** detectable: `/proc/<pid>/environ` is readable for same-user processes
(MEASURED — read successfully for running `claude`, `codex` and mesh processes). A check
that reads the live environment of every running agent and flags `HESTIA_*` overrides
would catch this class directly. **Not yet built — recommended.**

### B2. Interpreter or `PATH` substitution
**Mechanism.** The hook command begins `python3 …`. A `PATH` whose `python3` is a stub
returning 0 neutralises every gate on the machine.
**Status.** INFERRED, mechanically identical to B1 and equally silent.
**Detection.** Same `/proc/<pid>/environ` sweep (`PATH` is in there), plus resolving
`python3` and comparing against an expected path.

---

## 4. Class C — the gate is asked but fails open ⚠️ **MEASURED FULL BYPASS**

### C1. Timeout starvation
**Measured:** `HESTIA_PRE_TOTAL_BUDGET_MS=1` → **exit 0**, silent allow on the same
forbidden command. With `HESTIA_PRE_FAIL_CLOSED=1` → exit 2. The budget is env-supplied
and the default posture is open.

### C2. Ambient slowness (no adversary required)
The 9p mount is the honest version of C1: a cold read can outrun the hook timeout, and
Claude-lineage hooks fail **open** on timeout. This needs no attacker — it is a Tuesday.
Tracked as [hestia#45](https://github.com/dp-web4/hestia/issues/45).

### C3. Missing fallback ⇒ allow
`invoke_legacy_fallback()` returns 0 — allow — when the fallback script is absent, and its
path is env-supplied (`HESTIA_LEGACY_FALLBACK`). This is what makes B1 a *complete* bypass
rather than a partial one; the two compose.

> ### The single highest-value mitigation we have
> **`HESTIA_PRE_FAIL_CLOSED=1` closed every measured bypass in this document (#2, #3 and
> C1).** It is currently **opt-in and off by default**. Turning it on fleet-wide is one
> environment variable and it converts three silent full bypasses into loud denials.
> The cost is real and must be stated: when the daemon is genuinely down, every agent
> stops. That is the correct trade for a *governance* layer and it should be a society
> decision, not a default someone inherits by accident.

---

## 5. Class D — attacking the record

### D1. Identity spoofing ⚠️ **DEMONSTRATED, unintentionally**
**Mechanism.** `HESTIA_ROLE`, `HESTIA_PLUGIN_ID` and `HESTIA_MESH_PLUGIN` are read from the
environment, so an agent can witness *as someone else* — polluting another member's trust
and hiding its own conduct.
**Status.** MEASURED, 2026-07-29, and not by design. `plugins/member-mesh/hestia-mesh.py`
defaulted `HESTIA_MESH_PLUGIN` to `kimi-code` — correct when the file was one member's
private surface, wrong once it became the fleet's notification path. With the env unset,
**claude-code connected as kimi-code three times** while using the tool exactly as
documented. No error, and — the part that makes this D1 rather than a config bug — no
*anonymous* act either: each was a well-formed act attributed to a specific real member.
It surfaced only by accident, because the third attempt happened to address kimi-code and
tripped the `hestia.member_notify_self` no-op check. Addressed to any other member it
would have succeeded silently and settled into kimi's trust record.
**What that upgrades.** The env read was already confirmed in source; what was inferred was
that it *reaches the record*. It does. The `tool_connect` guard rejects `plugin_id`s
containing `/` — that closes the drain-key-confusion variant, not impersonation; a bare
`kimi-code` passes. Disclosed in PR #108 rather than quietly rewritten, on the D3 precedent.
**Precedent, non-adversarial:** codex reported under two identities (`codex`, `codex-cli`)
for days purely by misconfiguration. If a mistake produced a split identity, an intent can.
**Detection.** WEAK, and unchanged by the above. The daemon accepts the claimed id. The
identity-alias mechanism can *reconcile* a split after the fact but cannot detect a lie at
the time. Note what actually caught this one: a *self*-notify check, i.e. the impersonation
was visible only because the impersonator addressed the impersonated. That is not detection.
**Mitigated, partially (PR #108).** The client now refuses to act without an explicit
member id — `exit 2` before connecting, so no act is minted on the refusal path — and
derives `HESTIA_MESH_HOST_AGENT` from it rather than pinning a second member's name. This
removes the *accidental* case only. The deliberate case is untouched: server-side, identity
is still client-asserted (HST-005), and today the difference between an honest member and a
forged one is an environment variable.
**Mitigation direction.** Bind identity to something the agent cannot assert — a per-plugin
key issued at install, signing each request. Currently unbuilt; this is the deepest
structural gap in the record's integrity.

### D3. Third-party reputation poisoning ⚠️ **DEMONSTRATED, unintentionally**
**Mechanism.** An agent that can invoke ANOTHER member's gate can author entries against
that member's conduct record. No control is defeated: the gate faithfully records what it
is told, derivation faithfully folds it, and the target's measured trust falls for acts it
never performed.
**Status.** MEASURED, and not by design. While writing this catalogue CBP drove peer gates
directly with synthetic payloads and launched other agents with deliberately
harmful-looking prompts, manufacturing **22 denials against codex** and 3 against kimi.
Codex's temperament fell to 0.371 and its `interactive-dev` grain read `medium` on conduct
that was entirely CBP's.
**Detection.** NONE automated. It was caught because a HUMAN noticed the numbers did not
match the collaborators he worked with (dp, 2026-07-26) and directed exoneration.
Reputation was writable by a third party and the correction was social.
**Why it is the sharpest entry here.** Every other class requires defeating something.
This one requires only *using* the system as designed — which is why heuristics cannot
address it, and why the answer is upstream: attributing an act to the entity that
*initiated* it rather than the identity whose gate processed it.
**Partial mitigation, built:** `tools/gate-probe.py` makes instrumentation self-cleaning,
so a probe exonerates the ding it causes. That is hygiene for honest probers, not a
control against dishonest ones.
**Scope note.** See [issue #49](https://github.com/dp-web4/hestia/issues/49) — the gate is
an early prototype that stops accidents, not adversaries.

### D2. Selective non-witnessing
Any Class A/B/C bypass is also a witnessing bypass, since the same hook does both. There is
no independent observer. **Consequence: the chain is a record of governed activity, never a
complete record of activity.** Reading chain silence as "nothing happened" is unsound —
say so wherever the chain is presented as evidence.

---

## 6. Class E — semantic evasion

### E1. Obfuscation past a lexical matcher
The policy matches on command text. `base64 -d | sh`, `$(printf …)`, variable indirection,
or writing a script in one call and executing it in the next all defeat a text matcher
without defeating any *mechanism*.
**Status.** INFERRED, but the inverse is MEASURED and frequent: the same lexical matching
produced **four false denies in a single session** on 2026-07-26, including blocking the
JSON fixture written to test this very document.
**This is the entry that matters most, and not for the reason it looks like.** A matcher
that is simultaneously over-broad (denies a string in a heredoc) and under-broad (misses
`base64 -d | sh`) trains the agent that denials are noise. **False positives manufacture
the disposition to route around, and they do it to well-aligned agents.** The precision
problem *is* a security problem.
**Detection.** Poor by nature. Resolution-based judgement (what the command *does*, not
what it *says*) is the standing fix — see
`reference_gate_scope_judged_by_resolution_not_mention`.

---

## 7. Class F — the deny does not bind

### F1. Advisory-only harnesses
Not every harness honours a non-zero hook exit. Where the exit code is advisory, the deny
is a suggestion.
**Status.** Partially measured — Kimi honours `exit 2` under `yolo` (verified 2026-07-23);
Claude and Codex honour it. Others in agent-atlas's 45 are unverified.
**Detection.** GOOD in principle: `agent-atlas`'s `talk-to` descriptors record
`blocking_capable`, so a non-blocking harness is knowable *before* it is trusted.

### F2. `--dangerously-skip-permissions`
**Observed on CBP right now:** a running `claude -c --dangerously-skip-permissions`.
This bypasses Claude Code's *own* permission prompts. Hooks still fire, so hestia's gate is
unaffected — but it removes the second, independent layer, leaving hestia alone.
**Detection.** EASY and unbuilt: the flag is visible in `/proc/<pid>/cmdline`. Same sweep as
B1 gets it for free.

---

## 8. What we can catch, honestly graded

| Class | Detectable? | By what | Built? |
|---|---|---|---|
| A1 matcher narrowed | partial | inventory vs `expects.json` | **gap** |
| A2 subagents (claude) | **n/a — closed** | measured: gated + witnessed | ✅ |
| A2 subagents (codex/kimi/gemini) | unknown | — | **unmeasured** |
| A2 subagent attribution | no | recorded as the parent | **gap** |
| A3 deferred execution | forensic only | chain holds the setup | n/a |
| A4 config edit | yes, ≤1h lag | `agent-inventory` | ✅ |
| **B1 endpoint redirect** | **not via chain** | `/proc/<pid>/environ` sweep | **gap** |
| B2 PATH/interpreter | same as B1 | same sweep | **gap** |
| **C1 budget starvation** | **not via chain** | same sweep | **gap** |
| C2 9p slowness | yes | inventory `FRAGILE` | ✅ (issue #45) |
| C3 missing fallback | yes | inventory dead-target stat | ✅ |
| **D1 identity spoofing** | **no — a self-notify no-op caught it** | convergence across witnesses | **structural gap** (accidental case closed, #108) |
| **D3 third-party reputation poisoning** | **no — a human caught it** | — | **structural gap** |
| D2 non-witnessing | no | — | **accepted limit** |
| E1 obfuscation | poor | — | **accepted limit** |
| F1 advisory harness | yes, in advance | atlas `blocking_capable` | ✅ |
| F2 skip-permissions | yes | `/proc/<pid>/cmdline` | **gap** |

**Two entries are honest "no".** D2 and E1 are not detectable by any mechanism we have or
plan. They are load-bearing limits of in-process advisory governance, and no amount of
work inside this architecture removes them.

---

## 9. The structural fix: consequential config belongs in the VAULT, not the environment

> **"All consequential config should live in the vault not in env."** — dp, 2026-07-26

This reframes most of this document. Every measured bypass here (B1, B2, C1, C3) and the
identity gap (D1) share one root: **the gate takes its own governing parameters from a
channel the governed party can write.** Detection via `/proc` was my first recommendation
and it is the wrong ambition — it *notices* a bypass that has already happened. Moving the
parameters out of the environment *removes the class*.

The seven env vars the hook currently trusts, and where each should come from:

| variable | governs | belongs in |
|---|---|---|
| `HESTIA_ENDPOINT` | **which oracle is asked** | installed constant (see bootstrap below) |
| `HESTIA_PRE_FAIL_CLOSED` | **posture on no-verdict** | vault, default **closed** |
| `HESTIA_PRE_TOTAL_BUDGET_MS` | timeout before fail-open | vault |
| `HESTIA_LEGACY_FALLBACK` | fallback path (missing ⇒ allow) | vault, or removed entirely |
| `HESTIA_PRE_NO_FALLBACK` | deny-on-unreachable | vault |
| `HESTIA_ROLE` / `HESTIA_PLUGIN_ID` | **who the actor claims to be** | per-plugin credential, never asserted |
| `HESTIA_HOME` | where the vault is | installed constant |

**hub already solved this, and hestia should adopt its pattern rather than invent a
parallel one** (dp, 2026-07-26). From `web4/hub`:

- The hub **starts LOCKED** when no passphrase is available: a *locked shell* serving a
  "degraded no-LCT-tier surface, no signing" that can still answer generic discovery —
  *what hub is this?* — and accept an unlock. Nothing else.
- Unlocking swaps in the real signer at runtime; full functionality appears only then.
- Security config lives in the vault **only**, decrypted **into memory only**.
- Unlock attempts are rate-limited (`unlock_gate.rs`: 5 consecutive failures, 2 s minimum
  interval, 5-minute lockout) against online guessing.
- **A present-but-*wrong* passphrase is deliberately NOT treated as "locked"** — it
  hard-errors. This is the sharpest part of the design and the one most worth copying: it
  refuses to let a bad key degrade into the permissive-looking state. Exactly the failure
  this catalogue keeps finding elsewhere.

### What that changes for the gate

**`LOCKED` is a positive, authenticated answer, not a missing one.** hestia's silent
bypasses all come from the hook treating *no verdict* as *allow*. Under the hub pattern the
daemon, when locked, still answers — with "I cannot authorize anything." The hook must map
that to **deny**, and it is now distinguishable from unreachable, which it never was before.

**Authenticate the oracle, do not merely address it.** This retires my earlier framing that
an installed-constant endpoint was the best available fix. It is not, because it still
trusts *whatever answers at that address*. The hub signs; if the hook verifies that a
verdict is signed by the expected sovereign LCT, then B1 collapses — an attacker may
redirect `HESTIA_ENDPOINT` wherever they like, but a fake daemon cannot produce a valid
signature, and an unsigned or wrongly-signed verdict is a deny. **Endpoint poisoning stops
being a bypass and becomes a denial of service**, which is the correct downgrade: loud
instead of silent. The address may stay a constant for convenience; it stops being the
thing that is trusted.

**Safe-default inversion.** An unreadable vault must mean fail-**closed**. Today an absent
signal means allow, which is exactly why two *missing* values compose into a silent full
bypass.

## 10. Recommended, in value order

1. **Adopt hub's locked-shell pattern** (§9): security config in the vault, decrypted to
   memory only; a locked daemon serves unlock + discovery and nothing else; `LOCKED` is an
   answer meaning deny, not a missing verdict; a wrong key hard-errors instead of degrading.
   This eliminates B1/B2/C1/C3 rather than detecting them.
2. **Verify the verdict's signature** against the expected sovereign LCT. This is what
   actually closes B1 — it downgrades endpoint poisoning from a silent bypass to a loud
   denial of service. Supersedes "pin the endpoint as a constant", which only ever moved
   the trust, never removed it.
3. **`HESTIA_PRE_FAIL_CLOSED=1` fleet-wide *now*** as the interim. It closes every measured
   bypass today with one variable, while 1–2 are built. Needs a society decision: the daemon
   becomes a hard dependency.
4. **Per-plugin signing keys** (D1) — identity must be proven, not asserted. Also closes the
   subagent attribution gap if issued per session.
5. **Live-environment sweep** (`/proc/<pid>/environ`, `cmdline`) — demoted from #2 to here.
   Once 1–3 land it is defence in depth and a check on drift, not the primary control. Still
   the only thing that would catch `--dangerously-skip-permissions`.
6. **Fix matcher totality** (A1) — compare declared coverage against `expects.json`.
7. **Deny writes to gate-config paths** (A4) — turn an hourly detection into a prevention.
8. **Resolution-based matching** (E1) — reduces false positives, which reduces the
   disposition to route around. A precision fix *is* a security fix.
9. **Measure A2 on codex, kimi, gemini.** Closed on claude (§2); unknown elsewhere.

---

## 10b. The class this catalogue kept missing: authority held, not exercised

Every measured bypass above yields to an **ambient property** rather than to a decision:
`HESTIA_PRE_FAIL_CLOSED` being unset, a hook target being absent, a budget being small.
None of them is an act anyone took; each is a state the environment happened to be in.

The clearest specimen came from outside hestia, while writing this document. Linking
issue #49 into the web4 README required a commit; the push landed on a branch protected by
"changes must be made through a pull request", and the server logged
`Bypassed rule violations` — because the pushing identity holds admin. The automation ran
a plain `git push`. **No actor chose to bypass, so no rationale exists, so the log records
a fact with no reason attached.** A receipt for something nobody decided is not an audit
trail (dp: "this in itself is an example of what should be governed by written auditable
policy, not arbitrary choice").

hestia gets this right in exactly one place, which is why the contrast is worth stating:
the **operator gate requires a signed challenge per session** — authority *exercised as an
act*, not *held as a bit*. Everything else in the stack, including GitHub's admin flag, is
the other kind.

The general rule this catalogue should have started with:

> **A control that yields to a property will be bypassed by accident before it is bypassed
> by intent** — and the accidental case leaves no rationale, which makes it the harder one
> to audit afterwards.

Mitigation deployed for the git instance: the `post-commit` hook now detects the bypass,
reports the violated rule loudly, and witnesses a `policy_bypass` entry carrying
`authority: standing admin attribute` and `justification: null`. It cannot stop the
bypass; it only refuses to let it be silent.

## 11. Standing acknowledgements — put these in front of anyone relying on hestia

- The gate runs inside the blast radius; it is not containment.
- The chain records **governed** activity, never **all** activity. Silence is not evidence
  of absence.
- Default posture is **fail-open**. Absent `HESTIA_PRE_FAIL_CLOSED=1`, an unreachable
  daemon means an ungoverned agent.
- Semantic evasion of the text matcher is unsolved and, in the current design, unsolvable.
- Identity is **asserted**, not proven.
- Authority is **held as an attribute**, not exercised as a recorded act — so the most
  common bypass is accidental, and accidental bypasses leave no rationale to audit.
- Consequential config read from the environment is config the governed party can write.
  Until §9 lands, the gate's own posture is set on an agent-writable channel.
- This catalogue is incomplete by construction. Its value is that it is honest about being
  incomplete; treat a mechanism absent from this list as *unexamined*, not as *safe*.

*Every MEASURED entry can be reproduced with the commands in §3 and §4. Re-run them after
any change to the hook — a bypass that gets fixed and silently regresses is worse than one
that was never closed, because this document would then be lying.*
