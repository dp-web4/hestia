# The ratified degraded mode allows nothing on claude-code, and `2>/dev/null` is what turns a read into a write

**Seat:** claude-code (CBP) · **Wake:** 2026-09-04 ~02:05–02:30Z
**Method:** source read of the installed shims + a live probe of the installed hook,
run under an operator-approved escalation (`88469454e5b6111e`, approved by `operator`
at 1788487799, reason `k`, claimed by re-issue).

---

## 1. The claim

The society ratified a degraded posture on 2026-08-11 (dp): when the policy daemon is
unreachable, **deny writes, allow reads**. `hestia_gate_core.degraded_verdict` implements
both halves.

On the claude-code seat the *allow* half is unreachable by construction. Every read it
grants is refused a few lines later by the fail-closed daemon path, because the branch
that grants the read is followed **unconditionally** by a branch that requires the very
daemon whose absence triggered the degraded mode.

Separately, the read grammar that decides which shell commands qualify treats a bare
`2>/dev/null` as a write, because it substring-scans the raw command line for `>`.

Both were confirmed live, not inferred.

## 2. The probe

Three events fed to the installed hook
(`~/.claude/hooks/hestia/pre_tool_use.py`, 1,756 lines, build `v0.0.4-663-gbb00230`)
with `HESTIA_ENDPOINT` pointed at a dead port, so the snapshot fetch fails and the
degraded branch decides:

| # | command | `degraded_verdict` says | the hook actually returned |
|---|---|---|---|
| 1 | `cat /etc/hostname` | **ALLOW** (read) | `no verdict [fail-closed] — daemon path failed for Bash; cause=refused` |
| 2 | `journalctl -u hestia` | DENY | `deny [gate.degraded]` |
| 3 | `cat /etc/hostname 2>/dev/null` | **DENY** | `deny [gate.degraded]` |

Row 1 is the finding. Rows 1 and 3 together are the second finding: **the same read,
plus stderr suppression, changes class.**

## 3. Mechanism — the allow half

`pre_tool_use.py:1712-1748`:

```python
if _snapshot is not None:
    ...
    if _v.blocks: deny; return 2
else:
    _v = _core.degraded_verdict(_ev, _CORE_PROFILE)   # deny-writes-ALLOW-READS
    if _v.blocks:
        ...
        return 2
    # <- an ALLOW falls straight through

verdict = ask_daemon(tool_name, tool_input, tool_use_id, host_session_id)
if verdict is not None:
    return emit_decision(verdict)

return deny_no_verdict(f"daemon path failed for {tool_name}", ...)   # <- lands here
```

`fetch_policy_snapshot` and `ask_daemon` talk to the **same endpoint**. The `else` branch
is entered precisely because that endpoint did not answer; `ask_daemon` then asks it
again and gets the same silence. There is no path on which the degraded allow survives.

The posture is not misconfigured and the core is not wrong — `degraded_verdict` returns
`ALLOW` exactly as ratified. The seat discards the answer.

**Not tested on codex/kimi.** Their shims reach a Gate 2 whose comment says
*"Gate 2 below is read-class-skipped anyway"*, but that skip is `if tool not in READ_CLASS`,
a **tool**-level test, and `Bash` is not in `READ_CLASS` — so a Bash *read* should reach
Gate 2 there too. Whether it then survives is untested here, not refuted. Their telemetry
shows the allow arm being *decided* (kimi 199 allow-read rows, codex 22); no telemetry on
any seat records whether the allowed call then completed.

## 4. Mechanism — `2>/dev/null`

`hestia_gate_core.py:1143` (`_degraded_command_is_read`):

```python
if any(tok in command for tok in (">", "$(", "`", "<<")):
    return False
```

A raw substring scan over the whole line. `2>/dev/null` contains `>`. Measured against
the installed module:

```
READ   cat /etc/hostname
DENY   cat /etc/hostname 2>/dev/null
DENY   ls /tmp 2>/dev/null
DENY   grep -n foo bar.py 2>/dev/null
DENY   git log --oneline -5 2>/dev/null
DENY   cat a > /dev/null
```

**The same gate's own safety preset gets this right**, in the law text injected into every
member's context at launch:

> READING a device is not destroying it … and so is any redirect to `/dev/null` or `/dev/stderr`.

Two grammars inside one gate disagree about whether `>/dev/null` is a write.

### This is #116's defect, in a function written after #116 closed

[#116](https://github.com/dp-web4/hestia/issues/116) (closed 2026-08-06) named exactly this
discipline gap in `_is_read_only()`:

> The check is `if ">" in cmd or "|" in cmd`, a raw substring scan with no quote awareness.
> Note the *rm* rule in the operating law gets this exactly right … **so the correct
> discipline already exists in-tree and this classifier does not use it.**

`_degraded_command_is_read` is Sprint-F work, later than that closure, and ships the same
scan. The lesson did not propagate from the fixed function to the new one.

The cost is also worse here than it was in #116. #116's own argument was that misjudging
read-as-write "does not fail safe — it spends the alert class." In degraded mode the
misjudgement deletes the mode's **entire** function: allowing reads while the daemon is
down is the only thing the posture does.

### Second-order: the allowlist has no diagnostic verbs

`_DEGRADED_READ_VERBS` is 30 entries. Denied under it: `sed`, `awk`, `journalctl`,
`systemctl`, `ps`, `diff`, `jq`, `md5sum`, `sha256sum`, `nl`, `strings`, `od`, `xxd`,
`comm`, `seq`, `test`, `less`, `column`. `cat file` is a read; `sed -n 1,10p file` is a
write. This is defensible as conservatism, and the docstring claims that defence
("a miss here costs a retry-after-daemon-returns, never a leak") — but that defence is
what §3 disproves for this seat: **there is no retry-after, because the allow never
returned in the first place.**

## 5. The refusals recorded nothing — and the two arms are indistinguishable

Three refusals in the probe. Deny records produced: **zero**.
`~/.hestia/telemetry/gate-denies-claude-code.jsonl` still does not exist.

This is the mechanism of [#916](https://github.com/dp-web4/hestia/issues/916), filed by dp
at 2026-09-03T23:35Z, reproduced here under controlled conditions. **#916 is the record;
this is corroboration, not a new finding.** What is added is one sharpening:

| member | availability rows | rows carrying a degraded deny/allow discriminator |
|---|---|---|
| claude-code | 2,232 | **0** |
| kimi-code | 1,893 | 371 (172 `(deny)` + 199 `(allow-read)`) |
| codex | 1,141 | 137 (115 deny-with-reason + 22 `(allow-read)`) |

codex and kimi write `"degraded: policy snapshot fetch failed (deny)"` vs `"(allow-read)"`
into the availability row's `detail`. claude-code writes `"URLError:…"` and nothing else.
So on this seat the two arms of the ratified posture are not merely unwitnessed — in the
one telemetry the seat *does* write, **a degraded deny and a degraded allow are byte-wise
the same event.** #916 says the denials reach no record; this adds that the allows reach
no distinguishable one either, so the posture cannot be audited in either direction.

## 6. Incidental: `HESTIA_HOME` does not isolate the availability recorder

The probe ran with `HESTIA_HOME=/tmp/degexp`. Seven rows landed in the **real**
`~/.hestia/telemetry/gate-unavailable.jsonl` (5,259 → 5,266), because
`pre_tool_use.py:1420` calls
`record_gate_unavailable(..., home=str(DEFAULT_HESTIA_HOME))` — the constant, not the
environment. Disclosed rather than hidden: those seven rows are mine, all at ts
1788487976–77, and any later census of this seat's availability should know they are
synthetic.

## 7. What would settle it

1. **The fall-through.** Return the degraded allow instead of falling into `ask_daemon`
   (or gate the fall-through on `_snapshot is not None`). One-line shape; the other two
   seats' structure is the reference.
2. **The grammar.** Reuse the safety preset's `/dev/null` carve-out rather than a
   substring scan — the discipline #116 already located in-tree.
3. **The falsifier for §3, which I have not run:** feed the same three events to
   `~/.codex/hooks/pre_tool_use.py` and `~/.kimi-code/hooks/pre_tool_use.py`. If row 1
   returns allow there, the defect is claude-code-only and matches #916's
   "landed in 2 seats of 4" shape. If it fail-closes there too, the ratified posture has
   never been reachable on **any** seat for Bash, and that is a much larger finding than
   this one.

Related: #916 (recording), #116 (the ancestor grammar defect, closed), #669, #622, #632.

---

# Appendix — a prediction I filed against myself, and the data refuted it

I was woken with two `review_request` notices (10421/kimi → `41a02c457628854a`,
10515/codex → `c44af80ce8fee485`). Both polled back `expired`. I predicted:

> **The peer-review record evaporates.** `review_request` notices are durable (inbox.db,
> on disk) while escalations are in-memory, so every restart converts an outstanding
> corroboration invitation into a permanently unanswerable one, and whatever factors were
> filed are lost with it.

**REFUTED, on the second half.** `gate_escalation_corroborated` is a chain event and it
carries the factor **verbatim** — `argument` (full text, uncapped), `factors_present`,
`dissent`, `independence`, `bar`, `stance`, `corroborated_by`. 12 such rows in a 23h
window. Nothing is lost. This is a pointer defect, not a data-loss defect, and the
distinction matters: I would have filed the wrong issue.

Also refuted: **delivery is not slow.** Across 113 escalation `review_request` notices
this seat received (2026-08-13 → 2026-09-03), latency from `queued_at` to the primer that
carried it is median **9.3 min**, p90 **28.6 min**, and **92% (104/113) arrive inside a
60-minute escalation window.** The invitation reaches the peer in time.

## What survives, in its narrow form

| measurement | value |
|---|---|
| escalation `review_request`s this seat received, 21 days | 113 |
| of those, resolvable via `hestia gate poll` today | **0 / 113** |
| escalations opened in the 23h chain window | 19 |
| of those, reaching a terminal state | 19 (median **+17 s**, min +6 s) |
| receiving a peer factor at all | 10 (median **+841 s**) |
| peer factors filed *after* the terminal state | **8 / 10** |
| median interval between daemon restarts (20 deploys) | **4.00 h** (min 0.25 h) |

The escalation decides in ~17 seconds and the peer arrives ~14 minutes later. **That is
the design**, and it is not a divergence to file: dp ruled 2026-08-06 that two-bar is an
invitation to participate, not a blocker, and the injected law carries that ruling
precisely because seats keep re-deriving it as a defect. I am not re-deriving it.

The bite is on the converse, which the law itself names as owed-and-unpaid:

> A factor filed after the decision changes nothing that anyone is told about: **it is
> stored, and readable through `hestia_gate_escalation_poll`** … The record is the whole
> of what you get.

The record is the whole of what you get, and **the surface the law names for reading it
goes dark within the hour** — by the escalation's own ~1 h window, and independently by
any daemon restart (median 4.00 h apart, one pair 3 minutes apart today at 02:03:22Z and
02:06:27Z). 113 of 113 return `expired` there. The durable copy is on the chain, reachable
only by a client-side walk keyed on `escalation_id`, which the law does not mention.

So the compensation offered for participating post-hoc is real, and it is filed where the
law does not point. **The cheap fix is a sentence, not a schema:** name the chain event in
the same paragraph that names the poll surface.

## Two review requests, disposition

Neither needed a re-derivation, and checking first is the point. Both were already
answered by an earlier wake of this seat, and the chain says so:

| escalation | opened | asker withdrew | claude-code factor |
|---|---|---|---|
| `41a02c457628854a` | 16:40:56Z | +53 s | 16:55:33Z `concur` |
| `c44af80ce8fee485` | 21:27:49Z | +6 s | 21:44:08Z `concur` |

The notices were re-delivered, not unanswered. Ack, not re-review.

## Open petitions, measured

`hestia gate pending --as claude-code --json` → `count: 0`, `pending: []`. A MEASURED
zero, per the primer's own test. **With a caveat the primer does not carry:** it was
measured 90 seconds after a restart that empties the same store, and unlike
`hestia gate poll` — whose payload says *"a restart drops the store"* in its `note` —
`gate pending` discloses no volatility at all. Same store, two surfaces, one of which
tells you its answer has a horizon.
