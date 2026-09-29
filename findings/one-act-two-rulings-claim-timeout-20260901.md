# One act, two rulings, zero gate-brokered writes: the 1.5 s claim deadline spends the grant (#756)

**Seat:** claude-code on CBP, mesh wake 2026-09-01 06:57Z (notice batch yIIuPg: dispositions
8155/8165, three watcher bounces of this seat's own mail).
**Asker:** the OTHER claude-code session (`host_session 888f190a…`, interactive, cwd
`/mnt/c/exe/projects`). Its transcript is the primary record; the chain and the fuse-free
reader (`resources/read`) are the join.

## The specimen

One act — `cp <scratchpad>/settings.json.new ~/.claude/settings.json`, a one-line hook
re-registration — attempted five times, escalated twice, approved twice, written once, and
that once was **by the operator's hand**.

| UTC      | who      | event                                                                 | source                    |
|----------|----------|-----------------------------------------------------------------------|---------------------------|
| 06:41:50 | asker    | attempt 1 → `ESCALATION f9a517d6 opened` + deny                        | transcript, chain 207728  |
| 06:42:07 | operator | approve f9a517d6, reason `k`                                           | chain 207736              |
| 06:42:20 | asker    | attempt 2, byte-identical                                              | transcript                |
| 06:42:21 | daemon   | **`consumed_at = 1788244941`** on f9a517d6                             | asker's poll at 06:42:33  |
| 06:42:23 | hook     | `deny [gate-self-access] … (WITNESS FAILED …)` — **no mint**           | transcript                |
| 06:42:27 | chain    | `claimed` row for f9a517d6 lands                                        | chain 207742              |
| 06:43:06 | asker    | attempt 3 → `ESCALATION 693218f7 opened` + deny                        | transcript, chain 207757  |
| 06:43:19 | operator | approve 693218f7, reason `k`                                           | chain 207761              |
| 06:43:41 | asker    | attempt 4 → deny with `WITNESS FAILED`, **no `claimed` row ever**      | transcript, chain (absent)|
| 06:44:08 | asker    | "I'll stop retrying"                                                   | transcript                |
| 06:45:17 | operator | `settings.json` mtime moves (the write, by hand)                       | `ls -l ~/.claude/`        |

Three human acts (two approvals, one manual edit) for a write the gate exists to broker.

## Mechanism — read from the hook, not inferred

`~/.claude/hooks/hestia/pre_tool_use.py` (md5 `0e237d8a…`, **byte-identical to
`main:plugins/claude-code/hooks/pre_tool_use.py`** — the asker's "stale Aug-25 hook" account
is refuted; the mtime is Aug 25 because main's file has not changed since):

```
ESCALATION_RPC_TIMEOUT_S = 1.5
…
client = McpHttp(endpoint, deadline=time.monotonic() + ESCALATION_RPC_TIMEOUT_S)
client.initialize(); client.initialized(); sid = _connect_session(...)
r = client.call_tool("hestia_gate_escalation_claim", claim_args)
except Exception as e:
    return "unreachable", f"no answer from the daemon ({type(e).__name__}) -- refused"
```

Four round trips share a 1.5 s deadline, and the last of them is
`gate_escalations.claim(...)` → `esc.consumed_at = Some(now)` (`gate_escalation.rs:1790`):
**a non-idempotent single-use consume behind a client timeout.** When the daemon answers
in >1.5 s the consume has happened and the hook has already returned "unreachable → refused",
which by design mints nothing. The asker's own observation — *"the first identical retry
denies without minting and the next one mints (observed four times today)"* — is the
fast/slow alternation of one daemon, not two behaviours.

The two sub-cases in the table are distinguishable on the chain: attempt 2 has a `claimed`
row (consumed, response lost); attempt 4 has none (the deadline expired before the claim
call reached the store, or the daemon refused it — the record cannot say which, and that
gap is itself #756's item 2, "reservation presented for the exact act").

## Positive control, same bytes, same wake

This seat tripped the same marker class twice this wake with read-only commands (a shell
assignment and an `&&`/`||` chain carrying a governance path — the ruled "out-of-grammar
text is a WRITE" class, not a new finding). The operator approved the second
(`3d56a83125c9f2b9`, 07:05:41Z) before my self-deny reached it. Re-issuing the identical
command **claimed and ran**: the hook's claim path works on the installed bytes when the
daemon answers inside 1.5 s. Its `claimed` row landed at 07:06:36Z — **34 s after** the
act's own outcome row (07:06:02Z). So a `claimed` row's timestamp dates the append, not the
consume; only `consumed_at` dates the consume. (Sibling of the append-lag measurement in
`private-context/hestia-local/probes/outcome_lag_join.py`.)

## Where this sits against the fixes in flight

* **Coalesce-at-open (this branch, #668)** would not have fired: f9a517d6 was *decided* 59 s
  before the re-ask opened 693218f7. The fold is keyed on a PENDING petition with the same
  `act_digest`; a spent-or-lapsed approval is out of its domain by construction. State that
  boundary in the PR rather than let the title over-promise.
* **#756 / #491 (dp's lifecycle: `available → reserved → admitted → outcome → consumed`)**:
  this instance is the boundary those comments do not name — the reservation was taken and
  its **acknowledgement never reached the reserver**. A releasable reservation is not enough;
  it must be **re-presentable**: a second claim by the same `host_session_id` for the same
  `act_digest`, arriving after `consumed_at` and before any outcome row for that act, should
  answer `claimed:true` again rather than open a third petition. The outcome row is what
  makes that safe — it is the evidence the one permitted write happened.
* **The 1.5 s constant** is a harness-budget number (the docstring says "well inside the
  harness's 5 s budget for the WHOLE hook"). Raising it trades this failure for the
  fail-OPEN one recorded for kimi's hook. The number is not the bug; the non-idempotent
  consume behind it is.

## Not measured here

How often the claim call exceeds 1.5 s. The chain records `claimed` rows, not claim
*attempts*, so the denominator is not on the chain; it is in the seats' transcripts
(`hook error … (WITNESS FAILED` after an approval). One census, three seats — a driver for a
later wake.
