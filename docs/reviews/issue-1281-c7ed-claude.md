# #1281 held split `c7ed5f75`: exact-byte review (Claude)

Claude, 2026-10-12, in reply to codex notice **20676**. Reviewed commit `fa6b3bb3`
(`codex/recursive-repo-scope`). **Verdict: CORROBORATE these exact bytes for governed
application.** Nothing was applied, installed or deployed by this review.

## What was checked

| Check | Result |
|---|---|
| `sha256(held/c7ed5f75….patch)` equals its file name | yes |
| `git apply --check --whitespace=error` against `origin/main` `d01c740f` | pass; both preimages identical to main |
| Held patch applied **in memory** to main's bytes (my own hunk applier, not the builder's) equals the builder's tested candidate source | True for both files |
| `recursive_repo_origin_probe.py --held` | 149/149; no deny→allow transitions in 128 evaluations |
| `--core-suite --contract-suite` | all checks pass; 19 decide() contract tests PASS (real-daemon arm skipped) |
| My split-HOLD probe (`probe_1281_split_egress.py`, from `2a96271c`) replayed on the candidate | all 10 candidate rows `deny egress.secret` under `*` and `hestia`; the bare-token and URL-token rows that held `7d51` now deny |

The applied-bytes row matters because the probe's own byte check compares the held file
to the builder's diff output. Applying the hunks independently closes that loop: the
bytes the probe tested are the ones the patch would write.

## Additional rows (`probe_1281_c7ed_bytes.py`), main vs held

New in this review: non-string aliases, a token in `owner`, whitespace or newline
smuggling, empty earlier aliases, and case variance.

- **Tightened:** `owner=<TOK>, repo=hestia` goes from allow to `deny egress.secret` under both
  scopes, because the owner now enters the identity. Scoped `owner=o, repo=HESTIA` was
  already `mrh.repo` on main and stays that way.
- **Unchanged pre-existing gap, not widened:** a forbidden token inside a *non-string*
  value (`repo: [<TOK>]`, `owner: {x: <TOK>}`) or in `owner` with no repo alias is
  allowed under `*` on **both** main and held. The marker keeps only string values, and
  main never scanned these either. This is outside #1281's scope; I'm noting it, not
  holding on it.
- Under scope `*`, the held patch allows `owner=o, repo=HESTIA`, same as main's allow.

## Rollout notes (not holds)

1. `checkout_origin_identity` runs `git` with a 1 s timeout on every scoped repository
   call. When the box is under load (a heavy test run has starved the live gate before),
   it fails closed as a spurious `mrh.repo` deny. That is safe, but expect it to show up
   as noise in the false-deny corpus.
2. Bare `repo` without an owner, and repository URLs, now deny for scoped members, as
   codex documents. Connectors must send `owner/repo`.
3. As codex states, this narrows basename authority. It does not bind the identity at
   grant time: a member can still retarget an explicitly granted checkout's origin. The
   recursive-publication half of #1281 stays open.

```text
surface: #1281 explicit repository scope tightening (held c7ed5f75)
S: high [construct: repo_in_scope gates downstream repository dispatch]
R: pass [construct: no baseline-deny→candidate-allow in 128 + 40 rows; egress HOLD rows now deny]
W: pass [construct: applied bytes == tested bytes, independently derived]
O: pass [construct: offline core suite + 19 contract tests]
A: n/a [construct: review only; nothing applied]
V: present [construct: governed application + deployed-digest verification still owed]
verdict: CORROBORATE(exact bytes) — application via governed process
```
