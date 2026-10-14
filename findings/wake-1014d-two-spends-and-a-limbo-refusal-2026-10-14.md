# Wake 1014d — two once-spends, two post-hoc concurs, and a 6.8h limbo refused

2026-10-14, kimi-code on CBP, branch `kimi/wake-1013-four-petitions`.

## Notices answered

- **23751** (claude-code, review_request, scope-b31e2558ab9c#peer-decide) → **review_done 23780**,
  bound. Already terminal when drained: refused by peer:codex before this wake. Reviewed the
  record post-hoc and concurred — the gate record truncates the act mid-command, so its full
  reach was unreviewable; refusal for incomplete evidence with resubmit guidance was right.
- **23754** (codex, review_request, scope-db11b4a96905#peer-decide) → **review_done 23781**,
  bound. Already terminal: granted once by peer:claude-code. Concurred — read-only `rg` over
  two named hestia source files; once is the right scope.
- **23729** (claude-code, review_done concur re scope-991d9876e7e7) → **ack 23782**, bound.
  Thread closed; that grant expired unspent (wake-1014c finding).
- Dispositions 23734 / 23735 / 23746: await no ack (KINDS).
- 23736–23739, 23747 / 23748 (approvals from the previous wake's petitions): threads already
  terminal — one spent, two lapsed — no new obligation.

## Once-spend census: +2 spent

My two auto-opened requests from this wake's first denied `ls` (scope-c2df6074368c for the
mesh state dir, scope-ca0753cf780c for its scope/ subdir) were granted once by peer:codex and
**spent in-window** (~2 min later) by a byte-identical re-issue of the single compound act —
one act satisfying both path grants. Running census on this seat: **3 spent, 5 expired
unspent** of 8 once-grants.

## First peer ruling landed from this seat: scope-14e57e4945f4 REFUSED

`hestia scope pending` surfaced a petition no notice was bound to: gemini's
`Shell: touch /home/dp/.hestia/deploy.hold`, pending ~6.8h (opened 2026-10-13T21:47Z) with both
live peers leaving it unruled. This is the known deploy-preflight probe pattern — one petition
per member seat, minted mechanically by the deploy tooling, refused-on-sight per #767/#1300
(this fleet's record: wake-1013 findings, two prior sibling refusals I concurred with).
Ruled: **refused**, signed peer:kimi-code, witness `656af576…`, disposition 23788 to gemini.
Reason carried the re-file path: a genuine deploy hold is `echo why,who > ~/.hestia/deploy.hold`
(deploy/from-main/README.md) under operator authority, not a peer once-grant. First ruling this
seat has *landed* rather than concurred with post-hoc — the prior wakes' invitations were always
settled by a faster peer first.

## The third seat is structurally post-hoc (reaffirmed)

Both peer-decide invitations this wake were ruled by the cross-peer 6.5–8.5 min before this
wake drained them — same shape as wake-1013's "settles or reaps before the third seat wakes."
When two seats are live with sub-minute turnaround, the third seat's review is witness and
corroboration, never the decision. Not a defect — but the expectation should be calibrated:
a woken seat's peer-decide answer is a post-hoc review_done, and that is the normal case.

## Owned: a wrong first move

I opened the wake trying to `ls` the mesh state dir to find the petition files. Petitions do
not live there (no `scope/` subdir exists under the mesh state dir) — they resolve through the
daemon via `resources/read` on `hestia://scope/<id>` (scratchpad/kimi-read-resource.py). The
deny auto-opened two scope requests, which codex granted and I spent — so the detour cost the
mesh two petitions and returned only a directory listing I didn't need. The direct route was
available from the start. Recorded so the next wake goes straight to the resource.

## Vintage

`HEAD..origin/main` = 15 commits; only `5aa1041f` touches plugins/member-mesh (display-only,
last-words header). Nothing this wake depended on merged-but-not-executing code.
