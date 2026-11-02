# Held governed patch for web4#904 (build ids name only release tags)

`deploy/install-members.sh` is on the closure floor (`exact_paths` in
`hooks-gt/_shared/hestia_governance_closure.py`): a write to it is a governed act. It is one of the
producers of build-id strings: it records `build_id` in the deployment authority
(`current-build.json`) that the dashboard compares with the running binary's `--version`. Every
other producer on this branch (core/build.rs, hestia-deploy.sh, the member-mesh watcher, the
upgrade-path harness) now describes with `--match 'v[0-9]*'`. This one is held here as ONE
digest-named patch and is **not applied** on this branch. Landing it is one `git apply` by whoever
the escalation authorises:

    sha256sum held/2061045557f5ad007b1238fa68719c9c4ca41cf02aa25773a861902f70848c44.patch   # must print the name
    git apply held/2061045557f5ad007b1238fa68719c9c4ca41cf02aa25773a861902f70848c44.patch

| | sha256 |
|---|---|
| patch | `2061045557f5ad007b1238fa68719c9c4ca41cf02aa25773a861902f70848c44` |
| `deploy/install-members.sh` before (main `68447776`, which already carries the #1250 held patch) | `d714973bd4009eebee8b138d2b063a1db192ed0b87f2f72027c50fa9cfb83b3b` |
| `deploy/install-members.sh` after | `be97f423eaa4eac2160bb6975851e3121320c81bbf23a58c149974ebc90829ab` |

Nothing else on this branch touches that file. `git apply --check` is clean against the `before`
bytes (checked in a scratch copy, never the live tree).

## What it does

One line, plus a three-line comment:

```diff
-build_id="$(git -C "$REPO_ROOT" describe --tags --always --dirty 2>/dev/null || echo unknown)"
+build_id="$(git -C "$REPO_ROOT" describe --tags --match 'v[0-9]*' --always --dirty 2>/dev/null || echo unknown)"
```

## Why it matters, and what happens until it lands

- **Today the strings are identical.** On main `68447776` both describes print
  `v0.0.4-1070-g68447776`: every `app-v*` tag predates `v0.0.4`. So holding this patch changes
  nothing observable now.
- **The hazard is real, not hypothetical.** On 2026-08-08 the reference daemon and its manifest
  both named `app-v0.1.2-761-g9a6a5c2` (docs/STATUS_AUDIT_2026-08-08.md).
- **If an `app-v*` tag lands before this patch does**, the binary would say
  `v0.3.0-N-g<sha>` and the manifest `app-vX-M-g<sha>`. The dashboard still reads that as current,
  because `same_deployed_build` compares the commit (the manifest's `head_sha`). Only an `app-v*`
  tag sitting **exactly** on the deployed commit would differ in a way no consumer can bridge
  (`app-vX` carries no sha). With lockstep there should be no new `app-v*` tags at all: the app now
  releases under `vX.Y.Z`.
- `tools/build_tag_match_test.py` accepts the unmatched line in this file **only** while this patch
  exists under `held/` and adds exactly the matched line; once it is applied the test requires the
  matched form like every other producer.
