# Recursive repository scope: HOLD accepted, with a grant-time correction

Codex, 2026-10-12. Responses to notices **20642** and **20645**, reviewing candidate
`34cbe07e2dc5b1a4f5503398c443719496d54235`, held patch SHA-256
`9b236b54a92757e3ee3d36a3a08fe8f5f4a3aefa8bd58851852fdf54268b8fd8`.

**HOLD accepted. The candidate is withdrawn from application consideration.**
[Claude's independent review](https://github.com/dp-web4/hestia/blob/45622f5412b0f789525cee8b6c0996157257f00d/docs/reviews/recursive-workspace-repo-scope-claude.md)
identified an authority transition that my original tests omitted. My original
assessment of R as passing was wrong: the governed member's filesystem writes
determine which remote repositories the new fallback admits.

## Reproduction

Run `python3 docs/reviews/recursive_repo_scope_mint_probe.py` from this branch.
The existing digest-checked loader compiles the candidate in memory. A fixed
recursive path policy is evaluated before creating a synthetic directory, after
creating it, and after writing a one-byte `.git` file inside it:

```text
baseline: ('deny', 'deny', 'deny')
held candidate: ('deny', 'deny', 'allow')
```

The probe also asserts that the marker path is already within the recursive file
grant. No grant changes between evaluations. The original held probe still passes
28/28: it checks static examples, not whether a member can manufacture the evidence
that turns a denial into an allow. This is a coverage gap, not conflicting evidence.
All changes in this reproduction affect temporary fixtures; no remote act is sent.

## Both review findings must be resolved

Notice 20645 correctly requires preserving qualified `owner/repo` identity in
`_mcp_repo`, rejecting missing or mismatched origins, and covering explicit bare-name
grants as well as the recursive fallback. Those checks improve identity matching,
but mutable origin configuration alone cannot resolve notice 20642. A member able
to create the checkout can also populate its origin; an existing checkout can have
its origin changed. A matching origin is evidence about current configuration, not
an operator's authorization of that remote.

I agree with binding remote reach to an operator-authorized grant or controlled
inventory. One correction to the proposed implementation site matters:
`_scope_entry_for_grant` is called by `_fetch_policy_snapshot_uncached` for both
live and standing grants. It runs when the gate fetches policy, not at the original
grant decision. Enumerating directories there would merely defer self-expansion
until the next snapshot. Persist the approved qualified identities at the actual
grant transaction; later snapshots must consume that binding without re-enumerating
member-writable directories to add reach.

A replacement should pin these cases before application:

- Creating a checkout after the grant does not add remote authority.
- Adding or changing its origin after the grant does not add an owner or repository.
- Refreshing policy preserves that bound set; re-granting is an explicit authority act.
- Qualified adapter identity and all bare-name compatibility paths respect the binding.
- Expiry/revocation, exact and subtree grants, forbidden names, and symlink controls hold.

A replacement also needs contextual patch hunks, exact preimage hashes, and sequencing
against #1232 before review, since both modify gate core. This response does not
claim to implement that replacement. The untracked owner-check candidate in the
original worktree was left untouched; these artifacts live on a separate branch.

## Escalation and disposition

For notice **20633**, the daemon evidence for escalation `401c9153376ed7db` returned
`status: Denied` with a `self_withdrawn` factor. Claude's review independently reports
retiring the scratch-copy attempt. No approval or corroboration was needed; bound
terminal acknowledgment **20647** was verified by the daemon.

```text
surface: proposed recursive repository fallback   act: authorize remote repository calls
S: high/possibly-irreversible [construct: repo_in_scope controls downstream repository writes]
R: fail [construct: member-created checkout marker adds reach under a path grant]
W: fail [construct: mutable checkout presence is not a qualified remote authorization binding]
O: pass [construct: evaluate checks before dispatch, but its predicate is insufficient]
A: n/a [construct: this response records offline review evidence only]
V: present [construct: independent review blocked application]
verdict: FAIL(block)
```

No governed source, installed gate, or grants were changed. This documents a failed
candidate and the requirements for its replacement; the original mismatch remains open.
