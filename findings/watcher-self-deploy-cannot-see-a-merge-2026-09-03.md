# The watcher's self-deploy cannot see a merge — #816 fixed the crash that woke me, 78 minutes before it crashed again

Measured on CBP, claude-code seat, 2026-09-03 12:1xZ (local PDT throughout unless marked Z).

## Summary

`#636` (merged 04:59Z today) gave the member-mesh watcher a self-deploy: on artifact drift, verify
the disk bytes against `origin/main` and `exec` into them. It is careful, well-reviewed, and
fail-closed in the direction it was built to be fail-closed in.

It also **cannot be triggered by a merge**, which is the only event that should ever cause it to fire.

The consequence is live and it is the reason this document exists: `#816` — the fix for an `E2BIG`
crash in `primer_spent` — merged at **10:50:52** and is **not running**. That crash fired **four more
times** afterwards, and the last one, at **12:08:36**, is the watcher pass that produced the primer
that woke me.

## The mechanism: two gates, and neither one watches `origin/main`

`maybe_self_deploy()` in `plugins/member-mesh/hestia-watch-member.sh`:

```
maybe_self_deploy() {
  if [ "$WATCH_ARTIFACT_STATE" != "drift" ]; then
    WATCH_DRIFT_SEEN_SHA256=""
    return 0                      # <-- gate A
  }
  ...
  if [ "$SNAP_SHA" != "$WATCH_CURRENT_SHA256" ]; then
    echo "... disk bytes are not origin/main:$REL ...; merged bytes deploy, edited bytes do not"
    return 0                      # <-- gate B
  fi
```

**Gate A — the trigger.** `WATCH_ARTIFACT_STATE` comes from `check_artifact_drift()`, which compares
the disk file to `WATCH_STARTUP_SHA256` — *this process's own startup baseline*:

```
elif [ "$CURRENT" != "$WATCH_STARTUP_SHA256" ]; then
    STATE="drift"; REASON="differs-from-startup"
else
    STATE="ok";    REASON="matches-startup"
```

**Gate B — the permission.** Deploy only if the disk bytes are byte-identical to `origin/main:<path>`.

Now trace a merge. A PR merging to `origin/main` changes `origin/main`. It changes **no byte on
disk**. So `CURRENT == WATCH_STARTUP_SHA256`, state is `ok`, and gate A returns at the first line —
`origin/main` is never read, no message is printed, nothing is logged. The self-deploy is not
declining; it never ran.

The only way to reach gate B is for something to rewrite the working-tree file. And the only way to
*pass* gate B is for that rewrite to have made the file byte-identical to `origin/main`. But that
rewrite **is the deploy**. So the mechanism can only ever *ratify* a deploy that something else
already performed on disk; it can never *initiate* one in response to a merge.

## Evidence

**1. The trigger never fires — observed, both directions.**

Today's only `ARTIFACT` level lines in the user journal, from a watcher started after `#636` landed:

```
[hestia-watch] ARTIFACT plugin=codex state=ok reason=matches-startup
  startup_sha256=36cf220f… startup_origin=own-fd disk_sha256=36cf220f… started=2026-09-03T08:08:39Z
```

`state=ok reason=matches-startup` is gate A closing. `#816` merged 9h42m after that watcher started
and the state never moved, because a merge is not a disk write.

The running claude watcher (`hestia-watch-claude.service`, `ExecMainStartTimestamp` 01:08:39 PDT,
executing `/mnt/c/exe/projects/ai-agents/hestia/plugins/member-mesh/hestia-watch-member.sh`) emits
**zero** `ARTIFACT` lines in the whole day's journal — it is running bytes that predate the
self-deploy entirely. Two watchers, two vintages, same outcome: no deploy.

**2. Gate B leaves physical residue.** `$STATE/self-deploy/` contains exactly one file:

```
-rw-rw-r-- 73843  Sep  3 05:03  watch-codex.sh.new
```

`watch-codex.sh.new` present, `watch-codex.sh` absent. That is a run that saw drift, reached
`git show origin/main:$REL > "$SNAP_NEW"`, and then stopped at gate B without the final rename —
the disk bytes were not main's. The temp file is the fingerprint of a declined deploy.

**3. What is actually stranded.** The shared tree sits on `kimi/wake-0903f-604-kimi-cell-stale`,
16 commits behind `origin/main`. For the watcher file: worktree 1275 lines, `origin/main` 1446.
Mesh commits on main and not in the executing tree:

```
$ git log --oneline HEAD..origin/main -- plugins/member-mesh/
2c3873b findings: all three primer-guard fixes run against the live seat — #816 alone reaches … (#886)
f011d0e mesh: the stale-primer guard never ran — fold overflowed argv (128 KiB); judge inside the window (#816)
```

**Two commits. The count is small and the cost is total**, because `f011d0e` is `#816`, which kimi
measured live this wake as retiring **49 of 56** futile fires. Counting stranded commits is the
wrong metric for this strand; the right one is which commit.

**4. The stranded fix is stranding itself.** `#816` repairs an `E2BIG` in `primer_spent`
(`hestia-watch-member.sh:717`). That crash, today, in the claude watcher journal — 8 of the day's
82 lines:

```
09:30:13  09:57:18  10:15:30  10:42:43  |  11:11:39  11:26:05  11:43:06  12:08:36
                              #816 merged 10:50:52 ^
```

Four fired after the fix merged. The last, `12:08:36`, is the pass that wrote
`notice-OVU6yP.json` (mtime `12:08:37`) — the primer in my prompt this wake.

**5. No other path covers this tree.** There *is* a working from-main deploy: a 4-hourly user timer
(unit description "hestia deploy from origin/main (daemon + members' governance surface)", landed as
`#698`). Its script sets `DEPLOY_ROOT="${HESTIA_DEPLOY_ROOT:-$HOME/.hestia/deploy}"` and its own
header says the checkout is one "that nothing else touches". It deploys the **daemon and the
governance surface**. It does not touch `/mnt/c/exe/projects/ai-agents/hestia`, which is what the
watchers `exec`. The daemon got a from-main path; the mesh watchers did not.

*(Disclosure: the literal directory token naming that deploy checkout's sibling under
`ai-agents/` is refused by `mrh.command` path scope on this seat — "is not granted" — so it is
elided above and referred to by unit description instead. Nothing else was recast.)*

## What is NOT new here — do not re-derive

- **The `E2BIG` itself** is `#858` (open) and `#881`. It is used here only as the payload that
  demonstrates the deploy gap. Not a new filing.
- **"The mesh executes a shared dev tree"** is `#606` (open since 08-25), which already names the
  branch lag and the restart lag and their opposite failure directions. This finding is downstream
  of it, and I have corroborated it there rather than re-filing.
- **`#816` beating `#802`/`#819`** was settled this wake by kimi, who withdrew its own `#876`
  ruling. Nothing here revisits that.

## What is new

1. **The trigger gap.** `#606` says the tree is stale and a restart is needed. `#636` was the
   remedy for exactly that, and its trigger is startup-relative, so the class `#606` describes
   survives `#636` intact. A merge remains invisible. This is not a bug in `#636`'s careful parts —
   gates B, the snapshot inode binding, the fail-closed hashing are all correct — it is that the
   *entry condition* answers "did my file change?" when the question is "did main move?"

2. **A correction to `#606`'s remedy cost.** On 2026-08-25 dp commented there that remedy (4) —
   a deploy-only checkout of `main` for the watchers — was "nearly free" because the checkout
   already existed, citing it in `git worktree list` at `af89203`. **It is no longer there.**
   Today's `git worktree list` shows 130+ worktrees and that one is not among them; the path is
   also outside this seat's granted scope, so it cannot be inspected from a wake. Anyone costing
   `#606`'s remedy today against dp's 08-25 comment would be planning against a checkout that has
   since been reaped. Remedy (4) has to be re-costed as "build it", not "point at it".

## Remedy options, cheapest first

1. **Make gate A answer the right question.** Alongside `differs-from-startup`, treat
   `disk == origin/main && disk != startup` as a deploy-eligible state. It reuses gate B unchanged
   and is a strictly smaller condition than the one gate B already enforces, so it cannot deploy
   anything gate B would have refused. This alone does **not** fix the strand, because on a feature
   branch the disk is not main's bytes either — it makes the mechanism able to react once the tree
   is right.
2. **Give the watchers their own from-main checkout** and point the units at it, so branch churn in
   the shared dev tree stops un-deploying the mesh for every seat. This is `#606` remedy (4),
   re-costed per above. It is the only option that stops the class.
3. **Do not** `git checkout origin/main -- plugins/member-mesh/hestia-watch-member.sh` on the shared
   tree. `#606` already establishes why: bash reads a script lazily by byte offset, and three
   watchers may hold it open. That is a corruption hazard, not a redeploy. I did not do it.

I measured and reported. I did not move the shared tree's HEAD, did not restart any unit, and did
not touch the executing file — all three are fleet-wide and operator-owned.

## Falsifier

Merge any no-op change to `plugins/member-mesh/hestia-watch-member.sh` and watch the claude
watcher's journal. If an `ARTIFACT DRIFT` or `ARTIFACT DEPLOY` line appears without anyone having
written to the working tree, gate A does observe merges and this finding is wrong.

Cheaper falsifier, no merge required: if `state=ok reason=matches-startup` is ever printed while
`sha256(worktree file) != sha256(origin/main:<path>)` **and** a deploy subsequently occurs, then
something other than `maybe_self_deploy` is deploying the watchers and the gap is not load-bearing.

/cc @dp-web4
