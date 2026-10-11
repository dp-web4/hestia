# Held governed patch for #1250 (identity seeds)

`deploy/install-members.sh` is on the closure floor (`exact_paths`, `hestia_governance_closure.py`):
a write to it is a governed act. #1250's "identity seeds are not installed" lives in that file, so
it is kept here as ONE digest-named patch and is **not applied** on this branch. Landing it is one
`git apply` by whoever the escalation authorises:

    sha256sum held/a538a1386d0887ab94ab8c403930053a82dff6fbb77b56399fe7a7bb7b1e92f4.patch   # must print the name
    git apply held/a538a1386d0887ab94ab8c403930053a82dff6fbb77b56399fe7a7bb7b1e92f4.patch

| | sha256 |
|---|---|
| patch | `a538a1386d0887ab94ab8c403930053a82dff6fbb77b56399fe7a7bb7b1e92f4` |
| `deploy/install-members.sh` before (main `7e901d3c`) | `6f6b152df3be8afce04dec67e36f8b684a0a9cce4a6232f75d60bb9f8a6b7414` |
| `deploy/install-members.sh` after | `40bae83ed8e4bfe41f79f79d7ea2d4bef9a6fac8db77660bb37419a765f137ec` |

Base: `origin/main` `7e901d3c`. Nothing else on this branch touches that file, so the patch applies
to the branch head (`git apply --check` clean).

## What it does

For every member that ships `plugins/<member>/instance/identity.seed.json` (codex, gemini, kimi
today; claude-code ships none) and that this run installed, the installer places the seed at
`<directory the member's hooks run from>/../instance/identity.seed.json`. That is exactly where
each hydrate hook looks when no `*_PLUGIN_ROOT` is supplied
(`SEED="${X_PLUGIN_ROOT:-$(dirname "$0")/..}/instance/identity.seed.json"`). The anchor is the
directory the hooks were installed to (hydrate.sh's own when it is one of the files), derived from
the registration like every other target here, never from the declared `dest`.

- **Never overwritten.** A seed already present is this host's and is authoritative. It is
  reported (`present`, or `present and differs from this build's`) and left byte for byte. Only an
  absent seed is written, via a temp file and `mv -n`, so a writer that races the check wins.
- **Verified** after writing (invariant 3), and **DRY_RUN** names it (`would identity.seed.json`)
  without writing.
- **Recorded** in `current-build.json` as an additive `identity_seeds` list
  (`{member, path, state: installed|present}`). Seeds are continuity, not law, so they get no digest
  and no place in the gate-integrity set.

## How it was measured (without writing the governed file)

The patch is computed in memory from a read of the file and written only under `held/`. A copy of
the patched script under a neutral name was run hermetically: a fake HOME with all four harness
homes, a fake repo whose `plugins/`, `tools/` and `register-members.py` link to this branch, and no
daemon. Results:

    PASS seed placed at ~/.codex/instance, ~/.kimi-code/instance, ~/.gemini/hestia-plugins/gemini/instance
    PASS claude-code ships no seed and gets none
    PASS manifest identity_seeds: codex=installed gemini=installed kimi=installed
    PASS kimi hydrate's $(dirname $0)/.. fallback finds the seed
    PASS existing seeds byte-identical after a re-install (customised kimi kept)
    PASS the customised seed is reported as differing, kept
    PASS manifest identity_seeds: codex=present gemini=present kimi=present
    PASS dry run wrote no seed / names the seed it would place

Until this lands, `tools/upgrade_path_test.py`'s fresh-host arm fails `f3` (no identity seed for
codex, gemini, kimi) on this branch. That failure is correct, and it should clear once the patch is
applied.

## Left in place: codex's `CODEX_PLUGIN_ROOT=@HESTIA_PLUGIN_SOURCE@` (#1245 stopgap)

With seeds installed, codex's hydrate line no longer needs to point at the deploy clone: its
`$(dirname "$0")/..` fallback finds the installed seed, as kimi's and gemini's already do. The
stopgap is kept anyway, for three reasons:

1. It lives in `plugins/codex/hooks/hooks.json`, a governed template with a `hooks-gt/` copy and
   manifest. Removing it is a second governed patch plus a GT republish.
2. It is only safe after this patch has landed and run on a host. Removing it first would leave
   codex's hydrate with no seed on every host whose seed was never placed by hand.
3. It still works. The deploy clone carries the seed, and `git clean -qfd` keeps tracked files.

Follow-up: once this patch is deployed, drop `CODEX_PLUGIN_ROOT=@HESTIA_PLUGIN_SOURCE@` from the
codex template, republish `hooks-gt/codex`, and update
`tools/register_members_test.py::test_codex_hydrate_is_pointed_at_the_plugin_source_where_its_seed_lives`.
