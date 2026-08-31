# I changed the gate. The gate that runs is a different file, and I structurally cannot deploy it.

**Seat:** claude-code (CBP) · **Date:** 2026-08-31
**Context:** implementing dp's ruling — *"there shouldn't be legacy fallback period, and
fail closed shouldn't be optional."* Landed at `a88ff41`.

## What landed, and what did not

The edit is real, escalated, approved, claimed, verified and committed:

- escalation `1ce70d10cbcb0a5f`, approved by the operator, **claimed 17:24:12Z**
- installed bytes `sha256 86a3d975…` — bit-identical to the copy I tested
- GATE_BYPASS_CATALOG #2 repro: **before `rc=0` silent, after `rc=2` with stderr**
- negative control: live daemon + benign command still `rc=0` on both. A tightening,
  not a brick.

**And none of it is in force.** The running gate on this seat is
`~/.claude/hooks/hestia/pre_tool_use.py` — a *separate file*, which the harness invokes
and which the repo copy does not shadow. Before my edit the two were byte-identical
(`092369ab…` both), so there is no hidden drift in the file itself; there is simply no
link. The seat is still running the fail-open gate with the legacy fallback, and its own
launcher still exports `HESTIA_LEGACY_FALLBACK`, which the deny messages in this session
print verbatim on every refusal.

## The sanctioned remedy the deny names does not exist for the deployed path

Two writes of the same content, same session, 36 seconds apart:

| target | marker | result |
|---|---|---|
| `hestia/plugins/claude-code/hooks/pre_tool_use.py` | `plugins/*/hooks` | `gate_escalation_opened` → approved → claimed → **write landed** |
| `~/.claude/hooks/hestia/pre_tool_use.py` | `pre_tool_use.py` | `gate_self_access` row, deny text saying *"ESCALATE"* — **no escalation minted, `hestia gate pending` empty** |

I first read this as "the `pre_tool_use.py` marker has no escalation route." **That is
refuted**: over 08-16..08-31 that marker opened **71** escalations. So the marker is not
the cause and I am not claiming a mechanism. What is *observed* is narrower and still
matters: for this act the deny named a remedy that was not available, and a member
following the instruction in the refusal text lands nowhere.

## But the closure is working — this is by design, not a defect

`deploy/install-members.sh:87` refuses to run when `CLAUDECODE` or `HESTIA_ROLE` is set,
exempting only `DRY_RUN=1`. **A governed member cannot deploy its own gate.** That is the
correct design and the right answer to "an agent that can edit the thing that governs it
is not governed." The gap is not that I am blocked. The gap is that nothing tells the
member *"your change is repo-only until a human runs the installer"* — the approval, the
claim and the verified write all report success, and success reads as *in force*.

## Deploying is a WIDER act than the one that was approved

`DRY_RUN=1 bash deploy/install-members.sh` on this seat, at `a88ff41`:

```
MEMBER claude-code   would pre_tool_use.py            -> ~/.claude/hooks/hestia
MEMBER codex         would witness.py                 -> ~/.codex/hooks
SHARED ENGINE        would hestia_gate_core.py        -> ~/.hestia/shared
                     would hestia_gate_mechanism.py   -> ~/.hestia/shared
                     would hestia_governance_closure.py -> ~/.hestia/shared
```

**Five files. One is mine.** The other four are accumulated deploy lag — including all
three shared-engine modules, which are the gate's actual decision core. An operator who
approves "install the fail-closed hook" and runs the installer also ships six days of
engine drift they were never shown. The escalation record says `Bash: cp … pre_tool_use.py`;
the deployment that makes it real touches four more files that no escalation ever named.

This is the same shape as the #583 cutover finding, one layer out: **the unit that gets
approved is a file, and the unit that gets deployed is a manifest.**

## Asks for dp

1. **Run the installer** to put the ruling in force — it must be you, from a shell with
   neither `CLAUDECODE` nor `HESTIA_ROLE` set. Please read the dry run above first: it
   ships four files besides mine.
2. Consider whether the deployed-vs-repo split should be visible to the member. Right now
   a fully successful governed write is indistinguishable from a deployed one.

## A coordination note

Another session was working this same ruling concurrently in the same working tree —
escalation `033e052edafc8620` ("Step 2 of dp's 2026-08-31 ruling"), `54b0d771b893fa80`
(an `Edit` to the same directory, approved 17:24:12Z, the same second my `cp` claimed),
and commits landing on `claude/review-7451` under me mid-session. My bytes survived, but
that was luck, not interlock.
