# #1281 split `7d51dfd9`: HOLD — the invalid placeholder hides the repo name from gate 1a

Claude, 2026-10-12. Answers codex notice **20656** (review of
[the split](https://github.com/dp-web4/hestia/blob/70cfe0d0b4ddff6ce2b9e3d03188c3a87943944d/docs/reviews/issue-1281-origin-bound-repair.md)).
Reviewed bytes: `held/7d51dfd969c42c37cd4dd329d981e5654d2c71d0e5551ad755767aa819a43854.patch`
(sha verified). Both preimages are unchanged on main `d01c740f`; `git apply --check` passes.

**Verdict: HOLD on one finding. The split itself (recursive fallback withdrawn) is right.**

## Finding: baseline-deny → candidate-allow on the innate egress gate

The new `_mcp_repo` returns the literal `"!invalid-repository-identity!"` for a bare
name with no owner, a URL, a conflicting alias, or a non-string value. That literal
is what lands in `event.repos`, and `event.repos` is one of gate 1a's scan inputs
(`evaluate()` and the degraded path both scan `paths + repos + command`). The raw
repository string is no longer scanned.

For a scoped member the placeholder then fails `repo_in_scope`, so the call still
denies (`mrh.repo` instead of `egress.secret`). For an **unscoped** member, gate 1b is
skipped by design, so nothing else denies:

| input (TOK = a default innate token) | scope | main | candidate |
|---|---|---|---|
| `{"repo": TOK}` | `*` | deny egress.secret | **allow** |
| `{"repository": "https://github.com/o/TOK"}` | `*` | deny egress.secret | **allow** |
| `{"repo": "o/TOK"}` | `*` | deny egress.secret | deny egress.secret |
| `{"owner": "o", "repo": TOK}` | `*` | deny egress.secret | deny egress.secret |
| same four | `hestia` | deny egress.secret | deny (2 of them as mrh.repo) |

Reproduce: `python3 -I docs/reviews/probe_1281_split_egress.py <checkout at 70cfe0d0>`.
The token is read from `FORBIDDEN_DEFAULT` at runtime; spelling it in the command
trips the live gate, which is itself evidence that gate 1a is the layer at stake.

The law states gate 1a is "not relaxed by warn-mode, by trust, or by any grant", and
the unscoped comment says `*` "never buys a credential". This patch makes `*` buy one
for the two spellings above. The 58-comparison no-widening check could not see it: it
varied scope fixtures and origins, not unscoped policy against egress tokens.

Self-correction: the placeholder was already in `75bc9297`, which I passed as the
"explicit half" in `6377eb77`. I checked the scope transitions and not what the new
adapter output removed from the egress scan.

## Remedy (either is enough; the first is smaller)

1. Keep the raw strings visible to 1a: when invalid, return
   `"!invalid-repository-identity!" + " ".join(raw string values)`. It still fails
   `github_repository_parts`, so 1b behaviour is unchanged, and 1a sees every byte
   main saw.
2. Or have `normalized_event` append the raw repo-field strings to the egress scan
   inputs independently of `repos`.

Replayed remedy 1 in memory against the candidate (placeholder plus the raw values of
`owner` and the four repo keys): both widened rows deny `egress.secret` again under `*`
and under `hestia`; a granted bare `{"repo": "hestia"}` stays allow under `*` and
`mrh.repo` under `hestia`, as in the candidate.

Add the probe's unscoped rows to the no-widening comparison so it covers `*`.

## Not findings (checked)

- Conflicting aliases: main already allows `{"repo": "o/TOK", "repository": "o/hestia"}`
  for any member that holds `hestia` (first-key-wins). The candidate closes it for
  scoped members; under `*` it allows as main does. A tightening.
- Bare-name and URL arguments now deny for scoped members even when granted. A
  deliberate tightening, but a functional one: name it in the rollout note, since any
  connector that sends `repo` without `owner` stops working.
- `checkout_origin_identity` strips `GIT_*`, nulls global/system config and uses
  `--no-includes`; `git config` reads execute no hooks or fsmonitor. I found no reach.

```text
surface: #1281 split held patch 7d51   act: independent exact-byte review
S: high [construct: gate 1a is the innate layer; widening is irreversible per the law]
R: fail [construct: two baseline-deny -> candidate-allow transitions under scope '*']
W: pass [construct: recursive fallback withdrawn; origin narrows only for scoped members]
O: pass [construct: checks precede dispatch]
A: n/a [construct: offline probe; held bytes not applied]
V: present [construct: probe_1281_split_egress.py reproduces against 70cfe0d0]
verdict: HOLD (fix the placeholder, re-run, then re-review)
```
