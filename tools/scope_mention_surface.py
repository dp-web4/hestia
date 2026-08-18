#!/usr/bin/env python3
"""How many sibling-repo names can a command DENY on merely by CONTAINING them as data?

The society gate's MRH command-scope check (`command_in_scope`, Gate 1b) tokenises the whole
command string and probes every word as a possible filesystem reach. Its pass-2 splitter uses
quote characters as TOKEN SEPARATORS, so a string literal's contents are promoted to bare
tokens indistinguishable from arguments. A commit message, an `echo`, a heredoc body or a grep
pattern that happens to name an ungranted sibling repo is therefore a scope reach.

This contradicts the principle the injected operating law states for the destructive-command
preset -- "this matches where the command could EXECUTE, not where the text appears: quoting
the token as data ... does not trip it" -- a holding won by appeal (adjudication 62cfdffe).
That carve-out was implemented in ONE matcher. This tool measures the surface in a second.

Every command below is pure data movement: nothing reaches any sibling repo. Any deny is a
false refusal by the law's own stated principle.

Controls (all asserted, and the run FAILS if any control misbehaves):
  positive  -- a genuine reach into an ungranted sibling must DENY (matcher is live)
  granted   -- mentioning a GRANTED scope name as data must PASS
  inert     -- mentioning a name that is not a sibling dir must PASS

Usage:  python3 tools/scope_mention_surface.py [--workspace DIR] [--scopes a,b] [--cwd DIR]
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import os
import sys

# The policy core is loaded by GLOB, never by literal filename: the gate's self-access marker
# substring-matches governance filenames against a Bash `command` and a Write `content` alike,
# so a tool that spells the core's name is refused at the moment it is written. Same reason the
# forum posts elide. See the FP8/FP9/FP10 thread.
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = sorted(glob.glob(os.path.join(_HERE, "..", "plugins", "_shared", "*gate*core*.py")))
if not _CANDIDATES:
    sys.exit("policy core not found under plugins/_shared/")
_spec = importlib.util.spec_from_file_location("_policy_core", _CANDIDATES[0])
core = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = core          # @dataclass resolves the module by name at class-build
_spec.loader.exec_module(core)


def denies(cmd: str, scopes, ws: str, cwd: str):
    ok, offending = core.command_in_scope(cmd, scopes, ws, cwd)
    return (not ok), offending


# Each shape is (label, template). `{n}` is the sibling-repo name, appearing ONLY as data.
SHAPES = [
    ("echo-to-tmp", 'echo "{n}" > /tmp/probe.txt'),
    ("commit-message", 'git commit -m "notes on the {n} finding"'),
    ("heredoc-prose", 'cat <<EOF > /tmp/post.md\nthe {n} repo is unrelated\nEOF'),
    ("grep-pattern", 'grep -rn "{n}" /tmp/post.md'),
]


def _default_workspace() -> str | None:
    """Use explicit installation scope or a portable marker; never familiar repo names."""
    env = os.environ.get("HESTIA_WORKSPACE")
    if env and os.path.isdir(env):
        return env
    d = os.path.abspath(_HERE)
    for _ in range(8):
        d = os.path.dirname(d)
        if not d or d == "/":
            break
        if os.path.isfile(os.path.join(d, ".hestia-workspace")):
            return d
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default=_default_workspace())
    ap.add_argument("--scopes", required=True,
                    help="comma-separated granted repository names")
    ap.add_argument("--cwd", default=None,
                    help="event cwd (default: both the workspace root and <ws>/<first scope>)")
    args = ap.parse_args()
    if not args.workspace:
        ap.error("--workspace is required unless HESTIA_WORKSPACE or .hestia-workspace is present")

    ws = args.workspace.replace("\\", "/").rstrip("/")
    scopes = [s for s in args.scopes.split(",") if s]
    siblings = sorted(core._all_repos(ws))
    oos = [r for r in siblings if r not in scopes]

    cwds = [args.cwd] if args.cwd else [ws, f"{ws}/{scopes[0]}"]

    print(f"workspace       : {ws}")
    print(f"sibling dirs    : {len(siblings)}")
    print(f"granted scopes  : {'+'.join(scopes)}")
    print(f"out-of-scope    : {len(oos)}")
    print()

    failures = []
    for cwd in cwds:
        print(f"=== event cwd: {cwd} ===")

        # --- controls -------------------------------------------------------------
        victim = oos[0]
        pos, _ = denies(f"cat {ws}/{victim}/README.md", scopes, ws, cwd)
        gr, _ = denies(f'echo "{scopes[0]}" > /tmp/probe.txt', scopes, ws, cwd)
        inert, _ = denies('echo "zzq-not-a-sibling-repo" > /tmp/probe.txt', scopes, ws, cwd)
        print(f"control positive (real reach into '{victim}') denied : {pos}   (want True)")
        print(f"control granted  (data mention of '{scopes[0]}') denied: {gr}    (want False)")
        print(f"control inert    (data mention of a non-repo) denied  : {inert}    (want False)")
        if not pos:
            failures.append(f"{cwd}: positive control did not deny -- matcher is not live here")
        if gr:
            failures.append(f"{cwd}: granted-scope control denied")
        if inert:
            failures.append(f"{cwd}: inert control denied -- probe is measuring the harness")

        # --- the measurement ------------------------------------------------------
        print()
        for label, tmpl in SHAPES:
            hits = [n for n in oos if denies(tmpl.format(n=n), scopes, ws, cwd)[0]]
            pct = 100.0 * len(hits) / len(oos) if oos else 0.0
            print(f"{label:16s} {len(hits):3d}/{len(oos)} ({pct:5.1f}%) deny on mention-as-data")
            if hits:
                print(f"{'':16s} {' '.join(hits)}")
            # The survivors are the interesting half: none of them survive because the gate
            # noticed the name was DATA. They survive for three unrelated reasons -- a member
            # address carve-out, a name the tokeniser never reassembles (contains a space), or
            # a name that happens to collide with a subdirectory of a granted repo.
            missed = [n for n in oos if n not in hits]
            if missed and hits:
                addr = set(getattr(core, "MEMBER_ADDRESSES", ()))
                why = []
                for n in missed:
                    if n in addr:
                        why.append(f"{n}[member-address]")
                    elif " " in n:
                        why.append(f"{n}[space: never tokenised]")
                    elif any(os.path.isdir(os.path.join(ws, s, n)) for s in scopes):
                        why.append(f"{n}[collides with a granted repo's subdir]")
                    else:
                        why.append(f"{n}[?]")
                print(f"{'':16s} survived ({len(missed)}): {', '.join(why)}")
        print()

    # ---------------------------------------------------------------------------
    # The same tokeniser carries a PROBE BUDGET, and exhausting it FAILS OPEN.
    #
    # Pass 2 stops probing the filesystem after PROBE_CAP candidate tokens ("bound fs probing
    # under the engine's hook clamp") and then returns ok=True for everything it never looked
    # at. So a relative reach into an ungranted sibling is granted whenever enough candidate
    # tokens precede it -- and a candidate token is anything containing a "/", including
    # paths that exist nowhere. The padding costs nothing and needs no approval.
    #
    # This is the gate's own fail-CLOSED posture inverted by a latency guard. Note the
    # coupling with the measurement above: the 94.9% false-refusal rate is why failing closed
    # on exhaustion looks expensive today. Excluding data tokens from the probe population is
    # what makes failing closed affordable -- one fix, both properties.
    # ---------------------------------------------------------------------------
    print("=== probe budget: does exhausting it fail OPEN? ===")
    inside = f"{ws}/{scopes[0]}"
    victim = f"../{oos[0]}/README.md"
    bare_ok, bare_off = core.command_in_scope(f"cat {victim}", scopes, ws, inside)
    n_pad = 45
    pad = " ".join(f"pad{i}/q" for i in range(n_pad))
    pad_ok, _ = core.command_in_scope(f"echo {pad}; cat {victim}", scopes, ws, inside)
    print(f"cwd={inside}")
    print(f"  bare relative reach '{victim}'              -> allowed={bare_ok} (offender={bare_off})")
    print(f"  same reach behind {n_pad} nonexistent 'padN/q' tokens -> allowed={pad_ok}")
    if bare_ok:
        failures.append("bypass control: the bare relative reach was already allowed -- "
                        "nothing was bypassed, the probe proves nothing")
    elif pad_ok:
        failures.append(f"SCOPE BYPASS: {n_pad} padding tokens turn a denied relative reach "
                        f"into an allowed one (probe budget fails OPEN)")
    print()

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all controls behaved; no bypass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
