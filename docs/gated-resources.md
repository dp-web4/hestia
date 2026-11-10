# Gated resources

Design and history: [#1548](https://github.com/dp-web4/hestia/issues/1548).

A gated resource is a scarce thing on one machine (scratch disk, memory, a GPU) declared in that machine's society law. When an act consumes it, the gate asks the question dp put to it on 2026-11-10: **can the community afford this act right now?** If an act crashes the machine or interrupts a critical process, everyone loses.

The gate answers from live readings (metabolic proprioception, at community level), prices the act in ATP at those readings, and records the whole exchange as an R6 transaction.

## What a declaration says

| Field | Meaning |
|---|---|
| `consumers` | The acts that consume the resource. These use the same match fields as a rule's `match`, except `rate_limit`, which is refused because under a limit a rule skips firing, and an affordability check must never become optional. |
| `floors` | Conditions on live probes. `disk_free` (MB), `disk_free_permille` (tenths of a percent), `mem_available` (MB) and `process_running` (count). An act is unaffordable while a reading is below `min` or above `max`. |
| `comfortable` | The reading at or above which the price is the base price. Between `min` and `comfortable` the price surges as `(comfortable - min) / (reading - min)`. At the floor it is unbounded. |
| `pricing.base_milli_atp` | The price of one act at comfortable readings. |
| `runner` | The sanctioned way to run a consumer, for example `cargo-serial`. A consuming act that does not invoke it at an executable position is refused for routing. |
| `alternatives` | What a refused act may do instead: a smaller job, a later run, or a place in the queue. |
| `remedy` | What the operator is asked to fix when a floor fails for scarcity. |
| `mode` | `observe` or `enforce`. |

Probes run off the gate's workers, under a 400 ms deadline, and are cached for 5 s. A reading that cannot be taken (for example a hung Windows drive bridge) is *unknown*. An unknown reading never refuses an act, and it is recorded as unknown.

## What the gate does

- **Every consuming act** gets a `resource_observation` chain row carrying its R6 record. R6 has six parts:
  - Rules: the law hash and the resource.
  - Role: the actor and its role.
  - Request: the tool and the redacted command.
  - Reference: the readings.
  - Resource: the price at those readings, whether the act is affordable, why not, and the alternatives.
  - Result: pending until settlement.

  Allowed acts get this row too. The same records are returned in the gate reply as `resources`.
- **`observe`** never changes the verdict. The row records "would refuse because …".
- **`enforce`** adds an enforced deny to the strictest fold.
  - The deny's reason is a negotiation: why, then what is allowed instead.
  - An assessment can only add a deny. A destructive-command deny on the same act keeps its attribution, and nothing here turns a deny into an allow.
  - The readings commit in the `policy_decision` row as `resource_assessments`.
- **A floor that fails for scarcity** opens one remedy request addressed to the operator.
  - It is witnessed as `resource_remedy_requested` and shown on the dashboard and in the app's Decide page.
  - It counts the acts that meet the failed floor while it is open.
  - It closes, witnessed as `resource_remedy_cleared`, at the first later reading that meets the floor.
  - Contention, such as a critical process running, refuses or would refuse an act, but pages nobody: it passes by itself.

Open remedy requests are rebuilt from the chain when the daemon starts, so a daemon that crashes while the disk is short comes back still asking. A probe that stops answering for two minutes (a hung filesystem or Windows drive bridge) opens a `health` remedy request of its own and clears when the probe answers. A probe this platform cannot read at all (`/proc` on macOS) reads `unsupported`, distinct from `unknown`, and `set-resource` refuses a declaration that uses one.

Resources are published in `hestia_operating_law`, so members read what binds them before they meet it. A society without resources publishes exactly the law, and the hashes, it did before.

## Operating it

```
hestia policy set-resource --file <declaration.json>   # validated before it is stored
hestia policy rm-resource <id>
hestia policy show                                      # lists resources with their law text
```

As with rules, a running daemon picks the change up on restart.

## Not yet

- **Settlement.** The R6 Result is not yet recorded: no measured consumption (wall time, the change in free disk, peak memory) and no ATP discharged to ADP. The R6 record and the price are written now so that settlement has something to settle.
- **Member ATP balances.** Until they exist, only a floor (an unbounded price) refuses.
- **The lease service** (#1548 slice 2). This covers session-bound leases, atomic acquire, TTL with quarantine, and `hestia resource run`. Until then the runner (`cargo-serial`) holds the lock.
- **Push notice to the operator.** Remedy requests appear on the polled surfaces only. Nothing interrupts the operator yet.
