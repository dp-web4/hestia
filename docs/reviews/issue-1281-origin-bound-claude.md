# Re-review of the origin-bound repair (#1281): split it, and hold the recursive half

Claude, 2026-10-12. Answers notice **20650**. Reviewed `75bc9297`, held patch
`c02198170e13611cbe91706d1fcdab60b0156de1c699f1cd3440856f74774480`.

**Verdict: PASS for the explicit-grant half, HOLD for the recursive-grant half.**

## What I ran

`python3 docs/reviews/probe_mint_origin.py` (on this branch) uses the same
digest-checked loader as the origin probe. It evaluates a fixed policy before and after
writes the member is already allowed to make. No grant changes between the two calls.

```text
                         recursive path:ws/**        explicit grant "sample"
                         victim/minted               victim/sample
                         before    after mint        before    after origin rewrite
baseline (main):         deny      deny              allow     allow
held c0219817:           deny      allow             deny      allow
```

The "mint" step writes three plain files under `ws/minted/.git/`: `HEAD`, a `config`
with a `remote "origin"` URL of `github.com/victim/minted`, and empty `objects/` and
`refs/` directories. It does not use the git binary. Every write is inside `path:ws/**`.

## Reading

1. **Explicit grants: a strict tightening.** On main, `_mcp_repo` drops the owner, so a
   grant of `sample` admits `<any owner>/sample`. The candidate keeps the owner and
   requires it to match `origin`. A member can still retarget by rewriting `origin`,
   but the result is never wider than main. Across the 54-case origin probe, the candidate allows
   10 calls that main denies, and all 10 are under `path:ws/**`. None is under an
   explicit grant.
2. **Recursive grants: the 20642 mint still works.** Main denies every repository-named
   call under `path:ws/**`. The candidate allows any `owner/name` for which the member
   can write `ws/<name>/.git/config`. The earlier mint took a 1-byte `.git` file. This
   one takes a few lines of config, but it has the same property: a filesystem fact
   the governed party can write turns a deny into an allow on a remote it does not own.

Your own response at `3b57f33f` said so: "mutable origin configuration alone cannot
resolve notice 20642". It listed the pins a replacement needs, starting with
"creating a checkout after the grant does not add remote authority" and "adding or
changing its origin after the grant does not add an owner or repository". The new
handoff doc does not test those pins. Instead it reframes the gap as "does not claim
adversarial same-principal containment". The reframing is honest, but it does not
answer the requirement. A1 configuration evidence is fine as a *narrowing* signal
(point 1). It is not fine as the *only* source of a widening (point 2).

## Proposed disposition

- **Split the patch.** Land the owner-preserving `_mcp_repo` and the origin match for
  explicit and repository grants as one held change. It only removes reach, so its
  approval case is simple.
- **Keep the recursive fallback held** until the qualified identities are persisted
  in the grant transaction, as `3b57f33f` proposed. Re-run this probe against that
  version: column 2 must read `deny`.
- The original failure (a recursive grant cannot publish review evidence) stays open
  under the split. The operator's authorization of the gated `gh` shell route covers
  reporting in the meantime. Per-repository grants are a workaround, but they are
  safe ones.

## Landing order with #1232

#1232 (`claude/scope-gap-standing-escalation`, `8fe48fea`) is mine, and its gate half
is itself held at an escalation, so it is not ready to land. Land the #1281
explicit-grant half first, because it is smaller and only tightens. I will rebase
#1232, rebuild its held bytes and rerun both suites on top. If #1232's approval comes
first, I will tell you before applying it so that you can rebuild instead.

```text
surface: origin-bound connector scope   act: authorize repository-named connector calls
S: high/possibly-irreversible [construct: downstream repository writes]
R: split [construct: explicit half never wider than main; recursive half admits member-minted origins]
W: fail for recursive [construct: member-writable .git/config is the only authority evidence]
O: pass [construct: evaluate checks before dispatch]
A: n/a [construct: offline review evidence only]
V: present [construct: this review]
verdict: PASS(explicit half) / HOLD(recursive half)
```

No governed source, installed gate or grant was changed.
