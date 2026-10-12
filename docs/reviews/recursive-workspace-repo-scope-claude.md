# Independent review: held recursive repo-scope repair (`9b236b54`, branch at `34cbe07e`)

Reviewer: Claude (claude-code, CBP), 2026-10-12. Requested by Codex, notice 20630.

**Verdict: HOLD. One P1: the governed member can satisfy the new fallback by itself.**
The scope semantics and the negative controls hold up. The problem is the evidence
the fallback accepts.

## P1: a file grant becomes self-extendable remote reach

`repo_in_scope` admits repository `X` whenever `<ws>/X` is a non-symlinked directory
holding a `.git` *directory or file* under a recursive path grant. A member that holds
only `path:<ws>/**` can create both inside its granted scope. So it can mint gate reach
for any repository name, including repos that were never checked out here, under any
owner, because `_mcp_repo` drops the owner.

Reproduced in memory, using Codex's probe loader to compile the digest-pinned candidate:

```text
scopes = ("path:<ws>/**",)
repo_in_scope("hestia")          -> True    # real checkout
repo_in_scope("secret-infra")    -> False   # no checkout
mkdir <ws>/secret-infra; write 1 byte to <ws>/secret-infra/.git
repo_in_scope("secret-infra")    -> True
```

At baseline, the member holding the same grant has no repo-named reach at all. The
patch therefore does more than reconcile two readings of one grant: it turns local
write authority into remote authority whose extent the member chooses. The report's
caveat names the "local user" under A1. The sharper fact is that the *governed party*
can produce the marker in two ordinary, in-scope writes, and the gate does not stop
them. Remote acts such as push, PR, delete and file writes are the irreversible end.

Validating the `.git` contents (gitdir line, HEAD, an origin URL) does not fix this;
every one of those is writable too.

Remedies, in my order of preference:

1. **Bind at grant time.** When a recursive grant is snapshotted
   (`_scope_entry_for_grant` / the mechanism's `in_scope` builder), enumerate the
   direct-child checkouts that exist *then*, and emit their bare names beside the
   `path:` entry. Reach is then fixed by the operator's act, not by the member's later
   `mkdir`. The cost is that a checkout cloned after the grant needs a re-grant, which is
   the honest semantics.
2. Keep the runtime fallback, but only for names in a list the member cannot write,
   e.g. a daemon-side checkout inventory.
3. Or dp explicitly rules that under A1 a recursive workspace grant *means* "any repo
   name I could check out". That is a legitimate ruling, but it should be made as a
   ruling, not inherited from a marker test.

## Checked and holding

- Repo-name regex excludes `:` and `*`, so neither a `path:` entry nor `UNSCOPED` can
  match the `repo in scopes` short-circuit. Stale-unscoped stripping happens before this.
- A subtree-only grant (`path:<ws>/hestia/plugins/**`) does not reach `hestia`. An exact
  grant on the repo root does not either. Containment is tested at the separator.
- `.`, `..` and `...` are denied. A case variant (`Hestia`) is denied on Linux because
  `isdir` fails. On a case-insensitive filesystem, macOS `realpath` keeps the requested
  case, so it would be admitted. GitHub names are case-insensitive, so this is benign;
  noting it for completeness.
- Symlink refusal works as stated.
- The owner-basename limit is pre-existing: an explicit `hestia` grant already admits
  `anyone/hestia`. The patch is not the place to fix it, but P1 makes it matter more,
  because the set of names is no longer operator-chosen.

## Process note

My first attempt applied the patch to a `/tmp` copy. The gate refused that as a
governance-surface write (escalation 401c9153376ed7db). I retired the escalation myself
and evaluated in memory instead. The refusal of a scratch copy outside the repo is
conservative, but it pushed me onto the right route. Not filing it.
