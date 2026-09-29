# The deploy's repair hint named a cause it had not hit, and promised a repair that cannot happen

**Seat:** claude-code / CBP · **date:** 2026-08-31 · **branch:** `cbp/deploy-rule0-remedy`

Found while orienting at wake start: `systemctl --user list-units` showed
`hestia-deploy.service … failed`. It has been failing every cycle for a day, and the reason it
kept failing is not the reason its own log gave.

## 1. What the log says, seven times

`~/.hestia/deploy.log`, every four hours from `2026-08-30T03:18:27Z` to `2026-08-31T03:18:26Z`
(7 cycles, `grep -c "HALF-DEPLOYED"` = 7, `grep -c "REFUSED members' install"` = 7 — every
cycle since the rule-0 auditor landed):

```
REFUSED members' install: FAILED(rule-0: settings.json: <a gate path> in
  /mnt/c/exe/projects/ai-agents/claude-code) — the daemon deploy stands
HALF-DEPLOYED v0.0.4-529-g6a12873: binary current, manifest not written
  (hooks=refused(FAILED(rule-0: …)));
  the members' installer refuses inside a governed session (CLAUDECODE/HESTIA_ROLE set);
  the next timer cycle repairs it, or run hestia-deploy --hooks-only from an operator shell
```

Both halves of that last sentence are false for this arm:

* **The stated cause is not the one hit.** The installer never ran. `install_hooks` refused on
  a *preflight* verdict, before the installer was invoked. Nothing here has to do with
  `CLAUDECODE` or a governed session — the refusing party was the timer's own cycle, which is
  not a session.
* **The promised repair cannot happen.** `preflight_gate` is called from inside
  `install_hooks`, which is the single function the timer path, the `CURRENT`-with-stale-manifest
  repair path and `--hooks-only` all go through. So the next timer cycle re-runs the identical
  check and refuses identically — as it then did, six more times — and an operator shell running
  `--hooks-only` hits exactly the same wall.

The log is its own falsifier: the line predicting the repair is followed by six more copies of
itself.

**Why the first refusal is at 03:18 and not at 01:16.** The rule-0 auditor landed in `95e6357`
(2026-08-29 12:46 PDT), merged as `c991e12`, and `c991e12` is what the `2026-08-30T01:16:59Z`
cycle deployed — with `hooks=ok`. It did not refuse because the *running* script was still the
previous one: `hestia-deploy` self-installs to `~/.local/bin`, and bash holds the script it is
executing on an open fd, so the new bytes landed at `01:15Z` and did not decide anything until
the next fire. The `committed → … → RESTARTED → measured` chain, one level below the daemon: a
check can be merged, deployed and on disk and still not have run.

## 2. The defect

`hooks_repair_hint()` keyed on the glob `refused*`. That was written when `refused(…)` had one
producer — `rc=3`, the installer declining inside a governed session, for which the advice is
true. A second producer was added later at

```sh
hooks="refused($preflight)"     # install_hooks, on a FAILED* preflight verdict
```

which shares the prefix and inherited the first producer's remedy wholesale.

This is the **third** instance of a class this same script has already named and fixed twice —
its own comments describe `flock-absent-reads-as-SKIP` and `installer-rc=0-reads-as-ok`, and the
rule-0 block argues at length that *absence is its own arm*. Each time the fix has the same
shape: stop keying on a surface feature two causes happen to share, key on the cause. The
regression is not carelessness about the class; it is that the class was fixed **in the
producers** and the **consumer** was left keyed on a prefix.

## 3. What was actually stale, and on which seats

The refusal is not cosmetic. The members' governance surface stopped moving on
`2026-08-30T01:16:59Z` while the daemon kept deploying. Measured by hash, not by log line:

| file | installed | `origin/main` (6a12873) | |
|---|---|---|---|
| shared engine `hestia_gate_mechanism.py` | `93e02c18` | `00846297` | **STALE** |
| codex seat gate | `75698b0e` | `df9e9eb4` | **STALE** |
| kimi seat gate | `46fb485c` | `cc3c9580` | **STALE** |
| claude-code seat gate | `092369ab` | `092369ab` | current |
| claude-code `witness.py` | `2aeb8a47` | = | current |
| claude-code `law_inject.py` | `73a7b41f` | = | current |
| gemini `before_tool.py` | `efece255` | = | current |
| shared `hestia_gate_core.py`, `hestia_governance_closure.py` | | = | current |

`~/.hestia/current-build.json` reads `v0.0.4-516-gc991e12` (written `2026-08-30T01:16:59Z`); the
running daemon answers `initialize` with `v0.0.4-529-g6a12873`.

The missing change is exactly one commit: **bd76eb9** (PR #612), *"collapse(slice 1):
emit_attestation moves to the engine; two seats stop carrying it"*. So the three stale files are
the two halves of one atomic move. They are stale **together**, which is the lucky case — the
engine gained the function and the two seats dropped their copies in one commit, and a partial
install would have produced either a duplicate or a missing `emit_attestation`. Nothing here
argues that the refusal was wrong; refusing the whole members' install is what kept that move
atomic. The defect is only in what the refusal *told the reader to do next*.

The deploy checkout itself is fine: `~/.hestia/deploy/hestia/plugins/{codex,kimi}/hooks/` carry
the current bytes. The sync works. Only the install step is refused.

**Consequence for measurement, not just for ops.** Anything measured on the codex or kimi seat
between 2026-08-30 and now describes bytes `origin/main` no longer has. Fleet-comparison work
that treats "seat" as the variable inherits "build" as a confounder for that window.

## 4. The rule-0 finding is a true positive with teeth

Worth stating plainly, because the refusal reads like a technicality and is not one.

On CBP the *enforcing* gate is registered outside any checkout. What rule 0 caught is the other
spelling: `env.HESTIA_LEGACY_FALLBACK` in the harness settings, pointing at
`/mnt/c/exe/projects/ai-agents/claude-code/…`, inside a git worktree. The auditor is explicit
that it treats both spellings as registrations, and it is right to:

`invoke_legacy_fallback()` runs `python3 $HESTIA_LEGACY_FALLBACK` with the tool payload on stdin
and **returns its exit code as the gate's verdict** (2 denies, 0 allows). It is reached whenever
the daemon returns no verdict and `fail_closed()` is false — which is this seat's configuration.
So the fallback is not documentation: it is the live decider for every tool call during any
daemon hiccup, and it is a file that `git pull` in that checkout rewrites, unreviewed,
mid-session. That is precisely what rule 0 exists to catch.

## 5. What this change does, and what it deliberately does not

**Does:** `hooks_repair_hint()` now discriminates its producers — `refused(governed session)`
keeps the advice that is true for it; `refused(FAILED(rule-0: …))` and `refused(FAILED(…))` say
the preflight refused, say that no timer cycle and no `--hooks-only` run repairs a preflight
verdict, and the rule-0 arm names the **registration** as the thing to move, in **both**
spellings — a remedy naming only `hooks[].command` would leave the env spelling in place and the
next cycle would refuse again.

`deploy/from-main/hooks_repair_hint_test.py` pins the discrimination rather than the prose: the
two `refused(` producers must not yield the same sentence, the preflight arms must not promise a
timer repair or attribute the refusal to rc=3's cause, and — the fact the wording rests on —
`preflight_gate` must still be called inside `install_hooks`. If someone moves the preflight off
the shared path, the test goes red and the wording gets revisited instead of quietly becoming
wrong again. RED under the pre-fix script: 9 failures, with the two untouched arms staying green.
GREEN after: 17/17.

**Does not:** touch the registration. A governed session has no in-band route to the rule-0
remedy, by design and correctly — the script's own comments say so. **This needs dp:** move
`HESTIA_LEGACY_FALLBACK` out of `/mnt/c/exe/projects/ai-agents/claude-code`, or drop it, or set
`HESTIA_DEPLOY_RULE0=warn` to unblock the fleet's hook installs while the fix is queued. Until
then codex and kimi keep enforcing pre-#612 bytes and `hestia-deploy.service` stays permanently
`failed` — which is its own quiet cost: a unit that is always red no longer discriminates, so the
*next* deploy failure arrives invisible.

## Accountability self-audit

```
surface: deploy/from-main/hestia-deploy.sh :: hooks_repair_hint
  act: emit the operator-facing remedy for a failed members' install
S: low/reversible [construct: pure function, printf only; no dispatch, no state, no exit code
   changed — the case arms map to the same exits as before]
R: n/a   W: n/a   O: n/a [construct: no side effects to order]
A: n/a [construct: the cycle's own log line is the record; this changes its wording, not whether
   it is written]
V: n/a
verdict: PASS
```

The measurement half of this document is read-only: `sha256sum`, `diff -qr`, `git log`, one
`initialize` POST to the daemon.
