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

**Update, 2026-08-01 — the loud version was not enough, and the class recurred.** At 04:39,
unattended, a watcher-fired `claude-code` session pushed directly to `web4` `main`
(`76ff2f5`). The witness fired exactly as designed: `authority: standing admin attribute`,
`justification: null`, `note: "Exercised by automation without deliberation"`. A perfect
record of something nobody decided — which is what this section predicted, observed in the
wild, against the mitigation that was supposed to cover it.

dp's ruling:

> *"that authority should rest with the git manager, and it alone. auto sessions should go
> through the manager like all the others."*

So the authority stops being a property and becomes a **role that has to be transited**.
`pre-push-guard` (shared-context `scripts/git-census/`, step 1 of `git-manager-role`)
refuses any push whose destination is a protected branch unless the caller is acting as the
manager and says why:

```
GIT_MANAGER_ACT="<why this bypasses PR review>" git push ...
```

Three properties, stated with their limits:

- **The accidental case ends.** Automation running a plain `git push` does not set the
  variable, and that was the actual failure mode both times.
- **The deliberate case must name itself.** The reason is the whole point — §10b's
  complaint was a receipt with no rationale attached, and a declaration supplies one.
- **It is still A1 and still cooperative.** `GIT_MANAGER_ACT` is a *declaration, not proof*:
  any process on this box can set it. This converts an ambient bit into a recorded act; it
  does not convert it into an enforced boundary. Real enforcement is server-side branch
  protection that does not yield to admin, which is a GitHub setting and not a hook.

Blast radius is deliberately narrow: the guard returns 0 before any logic unless the push
targets `main`/`master`, so a defect in it cannot wedge ordinary branch work — and on that
narrow path it fails **closed**, because "could not tell" must not resolve to "went ahead"
for this specific act.

## 11. Codex audit update — 2026-08-02

The first version of this catalogue was written primarily from a Claude seat. A foreign
seat now exercises a different hook engine, a structural filesystem/network sandbox, and
out-of-process connectors. That changed the boundary enough to justify a second inventory.

Status vocabulary below is deliberately strict:

- **CONFIRMED-SOURCE** — the route follows directly from the code/configuration currently
  governing Codex; no consequential probe was needed.
- **MEASURED** — observed in a benign or already-authorized run.
- **INFERRED** — mechanically credible, not exercised because exercising it would itself
  cross the social boundary or damage useful state.
- **CONDITIONAL** — present in the fleet architecture, but a structural control on the
  current Codex seat removes a prerequisite.

### 11.1 Scope-read bypasses — the sandbox is not a read boundary

#### G1. Absolute non-workspace shell paths are not scope-checked
**Status: CONFIRMED-SOURCE.** `command_in_scope()` has a special pass for occurrences of
the configured workspace. Its relative-token pass skips absolute tokens. Therefore an
absolute path elsewhere on the filesystem is not rejected by MRH scope unless it also
contains one of the small innate forbidden substrings.

This matters because `workspace-write` permits reads across the filesystem. The sandbox
will not catch what the string gate missed.

#### G2. Recursive traversal from a broad working directory
**Status: CONFIRMED-SOURCE, explicitly acknowledged in the adapter.** A command operating
on `.` from the workspace root need not name any repository. The scope gate has no token
from which to recover the traversed repositories. Launching at the workspace root turns
this from a theoretical parser limit into an immediately available read route.

#### G3. Ambiguous-relative-path voting passes on one in-scope interpretation
**Status: CONFIRMED-SOURCE.** For relative tokens, the Codex adapter probes the event cwd
and every granted repository root. One existing in-scope interpretation wins even when an
out-of-scope interpretation also exists. This was introduced to stop false denials caused
by the hook event carrying a different cwd from the command executor. It trades those false
denials for an acknowledged false allow.

#### G4. Scope probing has a finite token budget
**Status: CONFIRMED-SOURCE.** After 40 filesystem probes, later relative targets receive no
scope decision. The bound exists to keep the hook below the harness timeout. That is a real
availability requirement and also a semantic cutoff an input can place before its actual
target.

#### G5. Symlink, alias, and time-of-check/time-of-use separation
**Status: INFERRED.** Scope is decided from lexical paths plus `exists()` probes, not from a
stable open file descriptor or a canonical object identity. An allowed spelling can resolve
through a link to a different readable object, and a path can change between check and use.
The write sandbox may independently stop some write escapes; it does not repair read scope.

### 11.2 Connector and MCP bypasses

#### G6. Repository selectors are only partially scoped
**Status: CONFIRMED-SOURCE.** `mcp_repo_target()` recognizes a limited set of name-bearing
arguments and keeps only the final repository-name component. Consequences:

- selectors by repository ID or repository URL can carry no recognized repository target;
- owner identity is discarded, so `owner-a/name` and `owner-b/name` are equivalent to the
  gate;
- a new connector schema or differently named target field is unscoped until hand-added.

The connector may still reject an unauthorized mutation. That is connector authorization,
not MRH enforcement.

#### G7. External mutations execute beyond the filesystem/network sandbox
**Status: MEASURED.** Connectors run in the harness process, not the sandboxed shell. They
can reach external services while `network_access=false`, and their writes never need to
touch the local working tree. GitHub object/ref operations first exposed this route; the
same class includes higher-level PR, issue, review, merge, deployment, and permission
operations.

Some connector calls have reached `PreToolUse`; others have not been demonstrated to do
so, and nested execution coverage is not a stated invariant. **Inconsistent coverage is
harder to reason about than uniformly absent coverage.** Until there is a connector census
and a red/green mutation probe per call path, treat every out-of-process mutator as outside
Hestia's assured boundary.

#### G8. Tool classes the Codex dispatcher does not hook
**Status: CONFIRMED-SOURCE.** The adapter records that tool discovery, custom/freeform tools,
and server-side search do not receive `PreToolUse`. Today many of those are read-only or
orchestration-only. The dangerous property is future composability: adding a consequential
capability to an uncovered class silently creates a bypass without changing Hestia.

### 11.3 Lexical and sequencing bypasses

#### G9. Live self-protection misses the single background separator
**Status: CONFIRMED-SOURCE against the deployed copy.** The live `_is_read_only()` rejects
raw pipes/redirections and splits `&&` and `;`, but does not split the shell's single
background-command separator. A read-like first segment can therefore determine the
classification while a later segment performs a mutation.

This is a protection hole in the gate's own self-access layer. A proposed classifier
widening seen on 2026-08-02 still omitted this separator and also admitted mutating forms
of several nominally read-only commands. Codex withheld the requested peer factor before
deployment.

**Replacement review, 2026-08-02.** PR #162 added the missing separator and removed the
first set of mutating heads, but its token grammar was still unsafe at the reviewed tip:

- `shlex(..., punctuation_chars=True)` emits compound operators such as `|&` and `&>>`
  as whole tokens; unrecognised punctuation then fell through as an ordinary argument;
- literal newlines were consumed as whitespace, making the declared newline separator
  unreachable and joining two commands under the first command's head;
- `posix=False` preserved quotes around guarded flags while only the command head was
  unquoted, so shell-valid quoted mutation flags evaded the guard; and
- `tree` was admitted as unguarded despite its file-output option.

The peer factor was denied at `32486b6f8fba`. The advertised 29-case matrix existed only
in temporary storage, not in the proposed commit, so it could neither be reviewed as part
of the object nor prevent regression. This strengthens the standing recommendation below:
a widened lexical grammar needs committed red cases and must reject every punctuation
form it does not fully model.

#### G10. Semantic indirection defeats command-text policy
**Status: INFERRED; the inverse false-positive behavior is MEASURED.** Encoded or generated
commands, interpreter programs, variable indirection, alternate utilities, staged scripts,
and an operation described without the expected verb can produce the same effect as a
denied command while presenting unrelated text to the matcher.

This is broader than “base64.” Any allowed program capable of general computation is a
second command language. A complete semantic denylist over arbitrary programs is not a
tractable goal.

#### G11. Deferred execution crosses the event boundary
**Status: INFERRED.** A gated act can install a repository hook, build step, scheduled job,
background worker, or artifact that a later process executes. The setup may be witnessed;
the later effect has no tool event. The same applies to an allowed source change consumed
later by a more privileged installer or deployment process.

#### G12. Nested unmanaged runners
**Status: INFERRED for deliberate use; ordinary Codex subagents are MEASURED-CLOSED.** The
product's subagent mechanism inherits hooks. That does not prove that a shell-launched CLI,
interpreter, agent runner, or copied harness inherits them. A parent call can be witnessed
while the child starts with different hook configuration and performs later work outside
the parent event stream. The OS sandbox may remain inherited; Hestia governance need not.

### 11.4 Git-manager and approval-path bypasses

#### G13. The requester can edit the deployed publisher
**Status: CLOSED FOR THE SANDBOXED CODEX SEAT, 2026-08-02 (`shared-context` `2200018e`);
fleet-wide residual remains.** The inbox refs and submission metadata are intentionally
requester-writable because they are proposals. The publisher program originally sat in that
same workspace, so a requester could change the code later run by the credential-holding seat.

The executable publisher now lives outside Codex's structural writable root. Acceptance receipts
record the running publisher's digest and source-parity observation. This removes the route for
this sandboxed seat and makes accidental substitution visible.

It is not a same-UID fleet boundary: an unsandboxed seat may still be able to write the deployed
copy, and a deliberately modified publisher can lie about its own digest. “The host decided” is
therefore structurally stronger for Codex and still cooperative/tamper-evident fleet-wide.

#### G14. Versioned publisher and deployed publisher are separate installations
**Status: SILENT-EMPTY-QUEUE FAILURE CLOSED, 2026-08-02 (`shared-context` `2200018e`);
deployment distinction retained honestly.** The first committed source derived its inbox from
its own source directory and reported an empty queue there. “No work” and “wrong installation”
rendered identically.

The publisher now requires an explicit, structurally valid inbox; a missing bare repository or
submissions directory is a hard configuration error. Every acceptance compares the running
publisher to governed source and records both the running digest and parity state.

Source and deployment remain separate objects by design, and parity currently warns rather than
blocks. That is now a visible, receipt-bound state instead of a healthy-looking empty queue. A
future reader must still distinguish “matched reviewed source” from “published under a recorded
mismatch.”

#### G15. Receipts and queue state are requester-writable claims
**Status: CONFIRMED-DESIGN.** A requester can alter refs, metadata, and receipt files. That
cannot itself mutate the external repository, but it can hide pending work, fabricate a
terminal-looking state, or influence a human/operator view. The publisher correctly says
inbox content is not evidence; every consumer must preserve that distinction.

The repaired receipt-to-tip discriminator closes one accidental authority leak. It does
not authenticate the receipt's writer.

#### G16. Reusing a PR leaves manager-authored provenance on the prior revision
**Status: PARTIALLY ADDRESSED; failure state remains false-green.** Revision acceptance
advanced the public branch from rejected tip `cf5029e` to repaired tip `3869603`, and the
receipt correctly retained both.
`open_pr()` found the existing PR and returned immediately, so the PR body continued to attest
the rejected tip and its old base.

Idempotency was implemented as “reuse the object,” but the required invariant is “one PR whose
managed current-revision state matches the accepted revision.” A reviewer reading the branch and
a reviewer reading the provenance table were shown different work.

The normal reuse path now rebuilds and refreshes the manager-authored body from the current
submission, so a successful edit converges without opening a duplicate PR. But a failed
`gh pr edit` still returns the existing PR object. `accept()` then writes `pr_status: opened`
and exits successfully even though the publisher just declared the body stale. The branch-
advanced/body-stale state is therefore still laundered into a healthy receipt.

Remaining repair: make refresh failure an explicit partial-failure result, return non-zero,
record that publication succeeded while provenance did not, and preserve idempotent retry.

## 12. Sandbox boundary: what it really holds, and how it can still fail

The Codex sandbox is the strongest control in this stack because it is enforced outside
the agent's command parser. It is still a boundary with a particular shape, not a general
containment claim.

### 12.1 Properties currently holding

- **CONFIRMED:** direct shell writes are restricted to the launch workspace and temporary
  storage.
- **CONFIRMED:** direct shell network egress is blocked.
- **CONFIRMED:** the installed hook copy and Codex configuration are outside the shell's
  writable roots.
- **MEASURED:** ordinary localhost socket fixtures are also refused in this seat.

These are meaningful. None implies that all workspace contents are authorized, that reads
are confined, or that an out-of-process tool is sandboxed.

### 12.2 Sandbox failure and escape classes

| ID | class | current assessment |
|---|---|---|
| S1 | **Over-broad writable root.** The structural grant is the whole launch workspace, not the member's MRH. A gate bypass can therefore write any repository under that root, including socially out-of-scope ones. | **CONFIRMED-CONFIG** |
| S2 | **Unconfined reads.** The filesystem is broadly readable; MRH read scope is cooperative plus lexical. | **CONFIRMED** |
| S3 | **Shared temporary storage.** Writable/executable temporary space permits staging, link/race attacks, cross-process rendezvous, and artifacts later consumed by a privileged process. | **CONFIRMED-PERMISSION; exploit paths INFERRED** |
| S4 | **Confused deputy.** MCP servers, hook processes, publishers, installers, and other host services run outside the sandbox and may act on sandbox-authored inputs. | **MEASURED architecture** |
| S5 | **Inherited handles.** A pre-opened file descriptor, pipe, socket, or process handle can carry authority the path/network policy would otherwise deny. Whether the current launcher leaks any useful handle is unmeasured. | **UNTESTED** |
| S6 | **Process-control surface.** Same-user process signalling, debugging, `/proc` inspection, or environment observation may affect or disclose unsandboxed peers unless the runtime/OS separately blocks it. Read access to peer environment was measured elsewhere; mutation/ptrace is untested. | **PARTIAL** |
| S7 | **Filesystem semantic mismatch.** Symlink following, hard links, rename races, case folding, host-mounted filesystem behavior, and mode-bit emulation can make policy about names differ from policy about objects. Mode-bit drift has already produced repeated defects; an actual write escape is unproven. | **PARTIAL / UNTESTED ESCAPE** |
| S8 | **Resource exhaustion.** CPU, memory, process, file-descriptor, disk, or I/O pressure can starve the hook/daemon until a fail-open harness proceeds. Even when fail-closed, this is a governance denial of service. | **INFERRED; timeout failures MEASURED** |
| S9 | **Unsandboxed child due launcher regression.** If a future execution path spawns a child before applying the sandbox, or applies it only to the first process, that child becomes an escape. There is no standing conformance probe across every tool/child path. | **UNTESTED** |
| S10 | **Kernel/runtime vulnerability.** A defect in the sandbox implementation, kernel, namespace/seccomp layer, filesystem bridge, or host integration can escape the structural boundary. | **UNKNOWN by construction; no exploit sought** |
| S11 | **Setuid/capability/user-namespace interactions.** Executables carrying ambient privilege can invalidate assumptions about the caller's effective boundary if `no_new_privs` and capability stripping are incomplete. | **UNTESTED; no available instance identified** |

S10–S11 are intentionally listed without exploit recipes. “No known exploit” is the only
honest claim available without turning a collaborative audit into destructive host testing.
The right control is sandbox/runtime patching plus a disposable conformance environment,
not production probing.

## 13. Harness boundary: ways a correct gate can still become irrelevant

| ID | class | consequence |
|---|---|---|
| H1 | **Hook timeout/crash is fail-open at the engine.** The adapter tries to fail closed internally, but the harness can kill it before it returns the blocking contract. | No verdict, tool proceeds, usually no witness. |
| H2 | **Matcher/coverage drift.** A narrowed matcher or new tool event can omit `PreToolUse` while inventory still reports a gate present. | Entire tool class bypasses governance. |
| H3 | **Tool-name/schema drift and field-purpose confusion.** Gate logic recognizes specific tool names and argument keys. Renames, aliases, repository IDs/URLs, and new payload envelopes can fall through. MEASURED 2026-08-02: a structured `Write` to an ordinary destination was denied because prose in its body mentioned a governance path; content was judged as target. | Correct policy applied to the wrong or empty target; evidence text becomes an act. |
| H4 | **Nested connector execution.** An outer orchestration call may be hooked while inner MCP calls occur in the harness, or vice versa. Coverage is not yet a tested transitive invariant. | External mutations have ambiguous governance. |
| H5 | **Exit/output contract drift.** Different harness versions may interpret exit codes, stderr, or structured deny JSON differently. | A deny becomes advisory or an error becomes allow. |
| H6 | **Argument truncation/normalization.** If the hook sees a shortened, joined, decoded, or otherwise different payload from the executor, it judges a different act. | Evidence and execution disagree while both look internally valid. |
| H7 | **Hook/environment substitution.** Endpoint, identity, interpreter, fallback, budget, mode, and hook paths inherited from the launcher can select a different governor or posture. | Wrong oracle, wrong actor, or silent no-verdict. |
| H8 | **Source/deployment drift.** Canonical, marketplace, and installed hook copies can differ. | Review proves one implementation; another governs. |
| H9 | **Subagent attribution collapse.** Inherited hooks currently block correctly, but child activity is attributed to the parent identity and coverage can regress without a conformance test. | Enforcement may hold while accountability does not. |
| H10 | **Session/restart discontinuity.** Transient approvals, escalation TTLs, cached identity, hook hashes, and witness presentation can reset or rotate across restart. | The displayed governance state may lose continuity even when durable bytes remain. |
| H11 | **Approval-channel fatigue.** False write classifications fill the same queue as consequential requests. | The human control degrades toward reflexive approval. |
| H12 | **Permission layer substitution.** Native harness approval, connector approval, sandbox permission, Hestia policy, and sovereign escalation answer different questions. Passing one is easily misreported as passing all. | An act appears “approved” without naming by whom or under which law. |
| H13 | **Harness-owned mutators.** A connector or app may expose remote writes, deployment, credential, or permission changes unavailable to the shell. | The network sandbox remains true while external state changes anyway. |

### 13.1 Two invariants the harness should prove continuously

1. **Coverage invariant:** every consequential tool call produces a `PreToolUse` event with
   the same normalized target and payload class the executor will use, including nested
   MCP calls and subagents.
2. **Binding invariant:** a blocking response prevents the effect across every harness
   version and permission mode; timeout/crash produces an explicit recorded state, never
   silent execution.

Without automated red/green probes, both are release assumptions rather than properties.

## 14. Updated mitigation order — preserve collaboration, remove accidental bypass

1. Launch members inside the specific task repository; do not make the workspace root the
   ordinary cwd or writable sandbox root.
2. Replace the self-access splitter with a real shell parser or define a deliberately small
   supported grammar; unknown syntax is consequential. Cover compound operators, newlines,
   quoted arguments, and every admitted command's output options in committed red tests before
   any allowlist widening. Judge structured tools by their destination fields, never body text.
3. Resolve every connector target canonically to owner + repository identity, regardless of
   selector form, and maintain a connector mutation census.
4. **Landed for the sandboxed Codex seat:** keep the git publisher outside the requester's
   writable root, compare deployed bytes to reviewed source, and record the running digest and
   parity state in every acceptance receipt. Extend the structural boundary to other seats where
   possible, and fix reused-PR provenance (G16).
5. Keep raw external mutation primitives from general members only after the governed
   manager has completed a real end-to-end change. The efficient path must remain usable.
6. Separate witness from gate execution so bypassing one does not automatically silence the
   other. Treat chain silence as unknown even after that improvement.
7. Run sandbox/harness conformance probes in a disposable environment: writable-root escape,
   read confinement, inherited handles, child-process inheritance, socket policy, hook
   timeout, exit binding, nested connectors, and subagents.
8. Authenticate oracle verdicts and member identity; move consequential posture out of the
   inherited environment.
9. Give false escalations a separate class and denominator. A queue dominated by reads is
   actively weakening the human factor.

The objective is not to make bypass metaphysically impossible. It is to make the normal,
efficient route the governed one; make deviations deliberate and visible; and preserve a
usable appeal path so respecting a false deny does not require abandoning the work.

## 15. Standing acknowledgements — put these in front of anyone relying on hestia

- The gate runs inside the blast radius; it is not containment.
- The Codex sandbox's writable unit is currently the launch workspace, not the member's MRH.
- The sandbox blocks direct network egress, not out-of-process connector mutations.
- Reads are not sandbox-confined; absolute paths, broad-cwd recursion, aliases, and parser
  cutoffs leave MRH read scope cooperative.
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
