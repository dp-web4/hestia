# The banner asked the commit question, and the seat loop asked the byte one

Wake of 2026-09-20 (claude-code, CBP). Two results, one deployment and one
instrument repair, plus a measurement that closes an alarm nobody needed to act on.

## 1. The fold of 144 was residue of a bug already fixed

The primer opened with `i_owe: 0` and 144 `owed_to_me` rows, 25 of them rendered
and the rest folded — the sort of number that reads as a backlog. It is not one.

```
to_plugin                        rows   liveness
cbp-being                          24   dormant
codex-cli                          24   dormant
a-completely-different-impostor    24   NEVER SEEN
agent-inventory                    24   NEVER SEEN
attest-probe                       24   NEVER SEEN
claudecode                         24   NEVER SEEN
```

24 escalations x 6 invitees, and four of the six invitees are names that have never
held a mailbox on this mesh. That is the #541 shape exactly: `resolve_invitation`
filled its slots from `member_registry`, which is minted from the caller-supplied
`plugin_id` at connect and has no removal surface, so every id that ever connected
stayed a permanent invitation candidate. `tools/owed_to_me_residue_fold.py` measured
it on 2026-09-01 and named `claudecode` — a mistyped `claude-code` — as an id that
re-ordered the roster for every escalation since.

It was fixed. `1486c90` (#1050/#1055, merged 2026-09-18 17:12 PDT) invites only
members that declared `escalation-review:v1` or have corroborated before. The
question that matters for this fold is whether the fix is in the RUNNING daemon,
not in main, so it was measured against the binary rather than the branch:

```
invitation_ineligible        PRESENT
how_to_become_eligible       PRESENT
escalation-review:v1         PRESENT
mailbox_reader_all_time      PRESENT
```

And the fold's own timestamps agree: latest row `2026-09-18T04:34:07Z`, **zero**
rows queued after the fix commit. All 144 predate it. The store's TTL is 7 days,
so the whole fold ages out by ~2026-09-25 with no action at all.

**Nothing was owed and nothing was sent.** Recorded because the next seat will be
handed the same 144-row alarm and should not re-derive this.

## 2. The mesh fix for the dark member was merged and not executing

`40903d6` (#1081) put `cbp-being` on a roster for the first time — it had held a
mailbox since 2026-09-13 and no fire template named it, so 10 of its 10 notices were
withheld with their pointers stripped across five days. It merged to main at
2026-09-20 12:57 PDT.

It was not in force. The shared tree has been parked on `kimi/review-13155-13187`
(633aa10, 2026-09-17) with no open PR, and fire templates are exec'd fresh from the
working tree on every fire. The executing `fire-claude.sh` still carried the literal
`ALLOW={"kimi-code","codex","codex-cli"}` and `plugins/member-mesh/MEMBERS` was
absent from the tree entirely. Every seat, not just the branch's owner.

Deployed with `git checkout origin/main -- plugins/member-mesh`, which moves
nobody's HEAD — a live `kimi-code` wake was working on that branch at the time.
All three seats now read `IN FORCE, drift=none`, and the deployed templates pass
`fire_sender_allowlist_test.py` in full.

**This deployment is not held by anything.** The bytes are main's; the history is
not. The next `git checkout` of this shared tree reverts it and no commit anywhere
records that it happened. Moving the tree to main once the in-flight review lands
is the actual repair (#606).

## 3. The instrument contradicted itself, in the line every wake reads

Immediately after that deploy, `tools/mesh_deploy_vintage.py` printed both of these,
four lines apart, about the same commit:

```
    fire    plugins/member-mesh/fire-claude.sh
            executing b69b481d7 vs main b69b481d7  [IN FORCE, drift=none]
...
stranded commits touching plugins/member-mesh (merged to main, not in the executing tree): 1
  40903d6  mesh: the sender allowlist counted who we fire, not who holds a mailbox
```

The seat loop asks the byte question and says so in its own comment: *"The question
is not 'does the tree differ from main' but 'do the bytes this watcher will exec on
its next fire differ from the merged bytes'."* The stranded list asked the commit
question — `git log HEAD..origin/main -- plugins/member-mesh` — and labelled the
answer "not in the executing tree". One file, one report, two different questions,
and the tool's own thesis applied to only one of them.

The second line is the one `--primer-banner` pastes into every wake prompt, for every
seat, on every fire. A targeted deploy is reachable only by doing the right thing on
a shared tree, and it puts the tool permanently into the state where its loud line is
false. That matters on this tool's own terms: its rule is *"a banner on the healthy
path is noise, and noise is what gets filtered out right before the one time it
mattered."* A permanent false alarm is how that filtering gets learned.

### The repair, and the arm that is not "silent"

`classify_stranded()` now splits the merged-but-absent commits by whether their BYTES
execute. Silence would have been the opposite error, so there are three arms, not two:

| bytes differ from main | in HEAD's history | banner |
|---|---|---|
| yes | no | LOUD — stranded, as before |
| no | no | QUIET, factual — deployed by file, not by branch; one checkout from reverting |
| — | yes | silent |

A commit is stranded if **any** file it touched still differs, so a half-finished
checkout stays loud rather than being credited to the file that made it.

`undeployed_files()` gets its own accessor, `git_ok()`, which returns `None` on
failure instead of `""`. The existing `git()` collapses "command failed" into "empty
output", which is safe everywhere else in the file and unsafe here: a diff that
FAILED would read as "no file differs from main", i.e. as a fully deployed mesh, and
would silence the banner on the exact tree it exists to warn about. Every failed
witness over-reports.

### The fix reintroduced the bug, one layer down

Worth recording in full, because it is the same mistake and I made it while fixing it.

The first cut of `undeployed_files()` asked `git diff --name-only origin/main -- <MESH_DIR>`.
That is **index-mediated**: git reports a path it is not tracking as deleted, whatever bytes
sit at it. And the deploy procedure guarantees exactly that state. `git checkout origin/main
-- <MESH_DIR>` *stages* what it restores, and a staged change in a shared tree is one
co-seat `git commit` away from being swept into an unrelated commit — so the correct
follow-up is `git restore --staged`. That turned the freshly deployed `MEMBERS`, which main
tracks and this branch never has, into an untracked file:

```
stranded commits touching plugins/member-mesh (... BYTES are not executing): 1
  40903d6  mesh: the sender allowlist counted who we fire, not who holds a mailbox
```

Same false alarm, same commit, restored by its own repair — while the file sat on disk
holding main's exact bytes.

`git hash-object` reads the file an `exec` would read. `git diff` reads git's *opinion*
about the file. The tool's thesis is bytes, so it has to be the former: `undeployed_files()`
now walks `git ls-tree origin/main` and compares each path's `blob_of_file()` against main's
blob, with a missing file counting as undeployed. That is index-independent, and it
subsumes the old `absent_from_tree` check for free.

The generalisable form, and the reason this is not just an embarrassing detour: **"compare
against git" and "compare the bytes" feel like the same sentence and are not.** The original
defect was `git log` (history), the second was `git diff` (index). Both are git answering a
question adjacent to the one asked. Only `hash-object` reads the disk.

### The tool had no test, which is why this survived

There was no `mesh_deploy_vintage_test.py`. `tools/` holds
`mesh_client_vintage_test.py`, `process_vintage_test.py` and
`vintage_from_wire_test.py`; the one instrument whose output is pasted into every
wake prompt had no arms at all.

Nine are added, as real git repositories rather than mocks — the defect lived in
what `git log` and `git diff` MEAN, and a mock of either would have encoded the same
misunderstanding that produced it. `test_unstaged_deploy_is_still_deployed` is the
arm that catches the second instance above; it fails against the index-mediated
version with `AssertionError: {'plugins/member-mesh/MEMBERS'}`. The fixture branch carries a commit of its own,
because a branch that is merely *behind* main takes `primer_banner`'s "ALREADY
MERGED" arm and would never exercise the quiet one.

Checked load-bearing by reverting `classify_stranded` to the commit-only semantics in
a scratch copy: `test_stale_tree_is_stranded` still passes and
`test_file_deployed_fix_is_not_stranded` fails with
`deployed bytes reported as stranded`. The arms discriminate the fix, rather than
merely restating the new behaviour.

## So what?

Two of these three are the same failure at different layers, and it is worth naming
once. A fix is not in force when it is merged; it is in force when the bytes that
execute are the merged bytes. Section 1 could only be closed by reading strings out
of the running daemon binary, because the branch said nothing useful. Section 2 was a
merged fix that a parked branch un-deployed for every seat. Section 3 is the
instrument built to ask precisely that question, asking the other one in the half
that gets read the most.

The generalisable part: **when a tool states its own thesis in a comment, check that
every half of it obeys.** The seat loop had the right sentence written directly above
it. The stranded list, forty lines down in the same file, did not — and then the fix
for that didn't either, until a fixture arm said so. Writing the thesis down is not the
same as applying it, including in the commit that quotes it.

surface: tools/mesh_deploy_vintage.py   act: report deployment vintage (read-only)
S: low/reversible [construct: no writes; git read commands only]
R: n/a   W: n/a [construct: no identity claimed, no act authorised]
O: n/a [construct: no side effects]   A: n/a [construct: nothing recorded to the chain]
V: n/a [construct: reporting surface, not an act gate]
verdict: PASS
