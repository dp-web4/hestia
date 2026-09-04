# Class T, all four seats: two fail, one passes by 362 ms of a number nobody owns

**2026-09-04 · claude-code on CBP · answers review asks 2 and 3 of PR #939**

PR #939 audited Class T (`docs/GATE_BYPASS_CATALOG.md` §17) for one seat and left three
asks. Ask 1 (which trade) is dp's. Asks 2 and 3 were routed to peers and to future work,
and **neither needed either**:

- **Ask 2** — "run the same audit on codex, kimi and gemini. Untested is not passing."
  Three notices to codex bounced on 2026-09-04 (`fire-rc=1;why=out-of-credits`), so the
  peers could not answer. They did not have to. *Neither half of the pair is a property of
  the peer.* Every shim is installed on this box and every harness deadline is in a config
  file on this box. Asking a seat to measure itself was never the only route to its
  number, and it is the slowest one.
- **Ask 3** — "locate the third budget window. Source shows two mint sites, the measured
  slope is 3.00." Answered by counting instead of fitting, in one run.

Instrument: `tools/class_t_seat_audit.py`. Target is the same black hole #939 used — a
listener that accepts and never answers, §17's own model of a daemon that is *alive but
loaded*. Inert: no daemon, no chain, no petition.

## The fleet

| seat | budget in force | windows | wall vs starved daemon | harness deadline | §17 as written | measured |
|---|---|---|---|---|---|---|
| claude | 4000 ms | 3 | **12.38 s** | 5 s | pass | **FAIL by 7.38 s** |
| codex | 4000 ms | 3 | **13.91 s** | 15 s | pass | pass, margin **1.09 s (7%)** |
| kimi | **14000 ms** | 3 | **16.91 s** | 15 s | pass | **FAIL by 1.91 s** |
| gemini | 4000 ms | 0 | 6.08 s | 15 s | pass | pass, margin 8.91 s (59%) |

**§17 as written clears all four.** Two of them cannot deliver a refusal.

## Ask 3: the third window is not a third site. It is the retry.

Counted, not fitted — `_McpHttp.__init__` patched on the installed engine, every client
recorded with the time remaining on the deadline it was handed:

```
at=0.010  window=0.499   fetch_policy_snapshot:580  -> _fetch_policy_snapshot_uncached:634
at=0.813  window=0.500   fetch_policy_snapshot:588  -> _fetch_policy_snapshot_uncached:634
at=1.331  window=0.500   ask_daemon:1388            -> query_society_safety:329
```

Two mint **sites**, three mint **events**. `fetch_policy_snapshot` calls
`_fetch_policy_snapshot_once` twice — line 580 then line 588 after a 250 ms backoff — and
each attempt re-enters `_fetch_policy_snapshot_uncached`, which mints a *fresh* whole-run
deadline at :634. The snapshot leg costs two budgets; the society-safety leg costs one.

The retry is not a bug and it is documented: *"One retry before None… a genuinely
unreachable daemon still returns None inside one extra budget."* The docstring says
**one extra budget** in as many words. Nothing composed that sentence with §17's, and the
two live four hundred lines apart in the same file.

The intercept decomposes exactly too. On the governance-read path #939 fitted `+1.91 s`;
counted, it is `0.25 s` (the retry's backoff `time.sleep`) + `1.50 s` (an un-budgeted
witness client, `_witness_self_read` → `_emit_gate_event`, which consults no budget at
all) + `~0.16 s` process overhead. On the ordinary Bash path there is no witness client
and the intercept is `0.38 s`. Both numbers are now sums of named parts rather than
regression outputs.

## The correction to #939: the law saturates, and the ceiling is not the budget's

#939 swept 500–4000 ms and fitted `wall = 3.00 · B + c`. That fit is real and it is
**local**. Swept past the per-request cap:

| budget | 2000 | 4000 | 6000 | 10000 | 20000 |
|---|---|---|---|---|---|
| claude | 6.40 | 12.43 | 15.38 | 15.39 | 15.41 |
| codex | 7.88 | 13.93 | 16.92 | 16.93 | 16.89 |

```
wall  =  3 · min(budget, REQUEST_TIMEOUT_S)  +  c_seat
```

A window ends when its *first* request gives up, and each request is capped at
`min(REQUEST_TIMEOUT_S, remaining)` (mechanism :162). `REQUEST_TIMEOUT_S` is 5 s. Every
one of #939's probes sat below that cap, so the cap never appeared in the data, and the
linear law it produced overstates the overrun by up to 3× above 5 s.

This changes what the fix space looks like:

- There is a **ceiling no budget can exceed** — `3 · REQUEST_TIMEOUT_S + c_seat`: 15.38 s
  on claude, 16.91 s on codex and kimi. A seat whose harness deadline is above its ceiling
  cannot be broken by *any* budget. A seat below it cannot be saved by raising the harness
  deadline a little.
- Consequently `REQUEST_TIMEOUT_S` and the retry count are load-bearing governance
  constants that nothing in §17 mentions and no audit reads. The budget is the only one of
  the three that anybody watches.

## The three seat rows, each of which is its own finding

### kimi — a REFUTED prediction of mine, in both inputs and in the conclusion

#939 wrote: *"kimi's 30 s deadline gives a ~9.4 s ceiling, so kimi is probably still
inside it."* Measured:

- kimi's PreToolUse deadline is **15 s**, not 30. The 30 s came from the shared engine's
  own comment (*"still well inside the measured engine clamps (codex 15s config, kimi 30s
  config)"*), which is stale. That comment is the justification text for the 4000 ms
  default, and one of the two numbers it justifies against is wrong.
- kimi's budget is **14000 ms**, not 4000. It is set on kimi's own hook command line
  (`HESTIA_PRE_TOTAL_BUDGET_MS=14000`), overriding the engine default by 3.5×.
- kimi therefore sits **at the saturated ceiling**, 16.91 s, against a 15 s deadline.
  It fails by 1.91 s, and it fails on *every* starved call, not on a tail.

Prediction refuted on both premises and on its conclusion. Worth stating plainly: I said
"probably still inside it" from two numbers I had not read.

**The budget is a per-seat fact.** #939 assumed one budget fleet-wide because the engine
has one default; a seat can raise it on its own command line, and the seat that did is the
seat that fails. That is Class T's original shape — *un-governing a member by raising a
number* — happening for real, on kimi, right now. §17 predicted this and the audit §17
asks for cannot see it, because the audit compares the *engine's* budget against the
harness deadline and never reads the command line the harness actually runs.

### codex — passes by 362 ms of margin on a number that has been raised twice

codex clears its 15 s deadline at 13.91 s. But its safe budget ceiling is **4362 ms** and
the shared default in force is **4000 ms**. The gap is 362 ms, on a constant whose history
in the file is `800 → 2500 → 4000`, each step justified by a real field incident and none
of them composed against three windows plus a 1.5 s un-budgeted witness client. The next
increment of the same size ungoverns codex.

codex pays 1.91 s of fixed cost where claude pays 0.38 s, because codex runs a witness
client on the **ordinary** path that claude only runs on the governance path. That is a
per-seat difference in the shim, not in the engine, and no invariant anywhere accounts
for it.

### gemini — the recommended fix already exists in the fleet, in production, on one seat

gemini scores 0 budget windows and 6.08 s because it never enters the shared mechanism
in-process. It spawns the governor as a subprocess with **its own deadline**:

```python
r = subprocess.run([sys.executable, CLAUDE_PRE], …, timeout=6, env=env)
…
except Exception:
    if MODE == "enforce":
        anomaly("hestia: deny [safety] — could not reach the governor; failing closed…")
```

One deadline, minted once per invocation, covering everything downstream, fail-closed on
overrun. That is exactly the fix #939 recommends as "the fix that is not a trade" — and it
is already running, at a process boundary, on gemini. It is not hypothetical and it does
not need designing. What it costs is that gemini never obtains a real verdict under
starvation; it takes the ratified degraded path instead. Which is the correct behaviour,
and is precisely what claude and kimi *cannot* do, because nothing is holding a clock over
them.

Two things about gemini that are **not** Class T and are noted here only so they are not
lost: its harness deadline is spelled in **milliseconds** (`15000`) where claude, codex and
kimi spell theirs in seconds — a number quoted across seats is a number read wrong by 1000× —
and its `HESTIA_SOCIETY_GATE` points at the **repo checkout** rather than the installed
authority directory, which is the shape #742/#745 deleted elsewhere.

## What I got wrong, and the shape of it

Two false-positive gate denials cost me time this wake, both already-known classes
(#680 substring-matching the forbidden dotfile literal inside `os.environ`; #440 reading a
read-only `grep`'s *haystack* as a write target, which auto-opened escalation
`674656460142f2e4` — withdrawn by me). Both are pinned in
`plugins/claude-code/tests/gate_false_refusal_test.py`. I lost no time re-deriving them
only because a memory said to check that file first, which is the whole argument for the
file existing.

And the substantive one: **I answered ask 2 by asking peers, and the peers were the wrong
instrument.** The escalations went out, bounced for out-of-credits, and were withdrawn.
The measurement they were asking for took eleven minutes to do locally, because the seats
are not remote — they are four directories on this machine. I reached for the mesh because
the ask was phrased as "the other seats," and a seat sounds like somebody to ask.

## So what?

#939's lesson was *auditing a pair does not audit the thing between them*. This wake
sharpens it in three ways, and each one generalises past this bug:

1. **A fit inside the sampled range is not a law.** The 3.00 slope was exact, reproducible
   and correct, and it was a local linearisation of a saturating function whose ceiling is
   set by a constant the sweep never varied. Sweeping the variable you suspect will not
   reveal the constant you did not.
2. **"Per-member" has to include the numbers, not just the check.** §17 asks for a per-seat
   *audit* and states a *fleet-wide* invariant over two numbers, both of which turn out to
   be per-seat — the harness deadline (and its units), and the budget itself. The seat that
   fails is the one that exercised the override the section itself warns about.
3. **"Ask the other seats" is a routing decision, and usually the wrong one.** The thing
   being measured was never in the peer. It was in a config file, on this disk, readable in
   one syscall. The mesh is for what only the peer knows.

Still not mine, and still open: which trade to take. The trade space is now bounded rather
than open-ended — for claude, no budget above **1539 ms** can fit a 5 s deadline, and the
false-denial bug dp fixed on 2026-08-11 lives just below that.
