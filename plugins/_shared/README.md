# One policy gate, adapter shims for harness semantics

**Status: NOT WIRED.** Nothing imports this. Each harness migration is an edit to that
harness's governance surface and needs its own escalation. This lands first so the migration
is reviewable before anything switches over.

> *"that's why we need one policy hook with adapter shims for harness semantics, not separate
> hook for each one..."* — dp, 2026-08-02

This is the hooks half of the 2026-07-29 P0 ruling. The **rules** were consolidated into one
policy entity then. The five **implementations** of those rules were not.

---

## What the measurement showed

Five gates: claude-code 2357 lines, codex 1136, kimi 540, gemini 528, cursor 390. Twenty-four
function names appear in two or more.

The first pass hashed function *text* and reported "12 drifted, including 100% of the scope
functions." **That was a count, not a judgement** — it scored trailing comments and an
`s2`→`s` rename as drift. Diffing code bodies only:

| function | kimi vs codex, code only |
|---|---|
| `command_in_scope` | 49 vs 49 lines — trailing comments and one rename. **No semantic difference** |
| `load_in_scope`, `_all_repos` | byte-identical |
| `launch_cwd_repo` | env var name only — legitimate parameterization |
| `deny` | **5 lines. The real one.** |

So the honest finding is not that the copies drifted. It is that **five hand-maintained copies
have stayed in lockstep by unpaid effort, and the one place they have already diverged is
`deny`** — codex witnesses a blocked reach via `witness_decision(...)`, kimi via
`_daemon_witness(...)` inside a swallowed `try/except`. The single function that records
refusals is the one that disagrees, so the trust chain's denominator already varies by vendor.

The case for consolidation does not need drift to have happened. It rests on five copies being
one refactor away from disagreeing about who may touch what, with the governance-critical
function already disagreeing.

---

## The remedy inventory is the actual payload

The duplication that hurt anyone was never in the shared functions. It was in the **sentences**,
authored fresh at every `deny(...)` call site across five files. Four instances in two days of
a refusal naming a door the recipient could not open:

1. kimi's scope deny said *"request it (`request_scope`)"*. No such tool existed. kimi filed an
   appeal instead — a channel that by design cannot deliver a file — and sat blocked through a
   correct-but-useless arbitration.
2. The same deny never named `hestia_appeal`, so when dp suggested appealing, kimi didn't know
   how and built its own mechanism.
3. `pre-push-guard` told refused members to *"submit through `.git-inbox/`"* — a path only codex
   has in its MRH.
4. codex's gate names no remedy at all.

Every one was written by the author of a control who was **not subject to the constraint that
blocks the recipient**. `claude-code` is not path-scoped at all, so every door it names is open
to it, and it cannot discover the problem by following its own instructions.

**A remedy is a claim about someone else's reachability.** So remedies live in one table
(`REMEDIES`), and refusals are constructed from a *rule id* rather than a sentence.

`_deny` **returns a denial** for an unregistered rule — it does not raise. The first version
raised, reasoning that a missing remedy should be loud; codex named the consequence (finding
1): these engines fail **open** on exception, so the "loud" path was an allow. Loudness is the
test's job (`test_every_literal_deny_rule_is_registered` walks the AST for every literal
`_deny("...")` call site); fail-closed is the runtime's.

`test_remedies_name_only_globally_registered_doors` checks every named tool against the
daemon's live list — and discriminates the two causes, because they are not the same defect:

- **NEVER BUILT** — the `request_scope` class. An authoring error.
- **NOT DEPLOYED** — the tool is in source, the daemon is older. The remedy is correct; the fix
  is a deploy.

Both are red. Only one is a mistake. The discriminator reads the **registration and dispatch
sites** in `handler.rs`, not a quoted token anywhere in the Rust source — a mention in a
comment or fixture would otherwise misclassify a never-built door as merely stale, applying
the softer verdict to the worse defect (codex finding 4b).

**It proves registration, not recipient reachability, and is named for that** (codex finding
3). `tools/list` is the daemon's *global* registry, so it can be green while the refused
member cannot call the tool at all — exactly the measured `hestia_appeal` class, globally
registered the whole time kimi had no way to reach it. The stronger invariant needs a
per-harness capability manifest; not claimed until one exists.

One remedy deliberately names **no** door: `egress.secret`. A leaked read has no undo, so
offering a channel would imply the act is available at a price.

---

## The shim contract

A shim may set only what `HarnessProfile` carries, and may implement only:

```python
parse_event(raw_stdin) -> NormalizedEvent      # harness event schema
render(verdict)        -> (exit_code, stderr)  # harness exit-code contract
```

A shim contains **no** scope logic, **no** forbidden list, **no** remedy text, and **no**
decision. If a shim needs a policy choice, the profile is missing a field — add the field, do
not branch in the shim.

`test_shims_contain_no_policy` checks every `shim_*.py` here. No shim exists yet, so it
currently **reports that it checked nothing** rather than passing silently. The first version
of this README credited that test before it was written (codex finding 4a) — a doc that
credits an absent check is worse than no doc, because it retires the reviewer's attention.

What legitimately differs, and is therefore all a profile carries: identity path, home markers,
launch-cwd env var, mode env var, workspace env var, member id, default role. That is the
entire measured delta between five gates.

### Fail-closed is the shim's job

Every Claude-Code-lineage engine (kimi, codex, cursor, …) fails **open** on timeout, spawn
failure, non-2 exit and exception. So the gate must be the fail-closed party: a shim's default
path is deny, and `exit 0` is reached only on an explicit confirmed allow.

`hestia_gate_core` **never calls `sys.exit`** — it returns a `Verdict` — precisely so a shim
cannot mistake "the core returned nothing" for "the core allowed it".
`test_core_never_calls_sys_exit` asserts it.

---

## Known-open

- **The core is not itself protected.** The gate's governance-surface rule matches the filename
  `pre_tool_use.py`, so `hestia_gate_core.py` was writable with no escalation — verified by
  writing it. Filename-matching was already known to be the weak form (a `sed -n` read of a
  hook is denied as a *write* because the path is mentioned); this is the same weakness in the
  permissive direction. **The rule must cover this file before anything is wired to it**, or
  consolidation moves the whole policy surface somewhere unguarded.
- **`command_in_scope` residual, inherited and accepted:** relative traversal that never names a
  path (`grep -r .`) escapes string parsing entirely. The engine sandbox, not this check, is the
  filesystem boundary.
- **Society-safety is stage 2 and lives in the shim**, because it needs a live transport. A shim
  must map an unreachable daemon to `society.unreachable`, never to allow.
- **`path[:60]` truncation was hiding the trigger.** The inherited hooks elided the target from
  the front, so on a long path the member was handed a string that did not contain the segment
  that tripped the gate. Now the offending segment is named separately and elision keeps the
  tail. Caught by a test only once the fixture workspace moved off `/tmp`.
- **`/tmp` is unconditionally in scope**, which made the first version of these tests pass for
  the wrong reason — five green checks measuring nothing, a pass bit-identical to "the gate is
  not running". Fixtures now build workspaces outside `/tmp` and assert it.
- **The temp-root check was a prefix match, not a path boundary** (codex finding 2):
  `startswith("/tmp")` admitted `/tmp-other/...` and `/var/tmpsecrets/...` — *siblings* of the
  temp roots, and directories anyone can create. A member could have taken unconditional reach
  by naming a directory: no grant, no witness, no operator. Same defect class as
  `reviewer ⊄ review` in the mesh vocabulary — a boundary rule written as a substring rule.
  Now compares at the separator, with red cases for both sibling spellings and one end-to-end.

## Running the tests

```
python3 test_gate_core.py                                          # offline
HESTIA_MCP=http://127.0.0.1:7711/mcp python3 test_gate_core.py     # + live tool list
```

Without `HESTIA_MCP` the remedy check **skips and says so**, rather than passing vacuously.
