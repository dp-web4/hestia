#!/usr/bin/env python3
"""Two #1250 frictions, pinned against the real functions in hestia-deploy.sh.

1. ONE BUILD, MANY SPELLINGS. `git describe` sizes its abbreviated sha by the object count of the
   clone it runs in, so one commit reads `-g588684d` in one clone and `-g588684d6` in another. The
   deploy compared those strings, so a current binary or manifest could read stale for no reason
   (the upgrade-path harness measured `-g9c880de` vs `-g9c880def`). `same_build` compares the
   COMMIT both spellings resolve to in the deploy checkout.

2. A FRESH HOST COULD NOT INSTALL FROM THE TIMER. The preflight probes each gate under its seat
   projection, and the only writer of projections (the seat seeder) ran at the end of
   install-members.sh -- after the preflight refused. `seed_seats` runs the seeder BEFORE the
   preflight; this pins its arms (governed session, no seeder, no operator key, opt-out, a seeder
   that fails, one that adds, one that finds every seat complete) with the seeder stubbed.

The functions are brace-matched out of the real script and run under `set -euo pipefail`.
Run: python3 build_identity_test.py     (no pytest needed; exit 1 on failure)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "hestia-deploy.sh"
TEXT = SCRIPT.read_text()
FAILS: list[str] = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def extract_function(fname: str) -> str:
    m = re.search(rf"^{re.escape(fname)}\(\) *\{{", TEXT, re.M)
    assert m, f"{fname}() not found in hestia-deploy.sh"
    depth = 0
    for j in range(m.start(), len(TEXT)):
        if TEXT[j] == "{":
            depth += 1
        elif TEXT[j] == "}":
            depth -= 1
            if depth == 0:
                return TEXT[m.start():j + 1]
    raise AssertionError(f"{fname}() never closes")


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@invalid"}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


# ---- 1. same_build ------------------------------------------------------------------------
FUNCS = (extract_function("build_hex") + "\n" + extract_function("build_commit") + "\n"
         + extract_function("same_build") + "\n")

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    repo = root / "hestia"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "commit", "-q", "--allow-empty", "-m", "a")
    git(repo, "tag", "v0.0.4")
    git(repo, "commit", "-q", "--allow-empty", "-m", "b")
    b_full = git(repo, "rev-parse", "HEAD")
    git(repo, "commit", "-q", "--allow-empty", "-m", "c")
    c_full = git(repo, "rev-parse", "HEAD")

    def same(a: str, b: str) -> bool:
        r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + FUNCS
                            + 'if same_build "$1" "$2"; then echo yes; else echo no; fi', "_", a, b],
                           capture_output=True, text=True, env={**os.environ, "DEPLOY_ROOT": str(root)})
        if r.returncode != 0:
            FAILS.append(f"same_build {a!r} {b!r} crashed rc={r.returncode}: {r.stderr.strip()}")
        return r.stdout.strip() == "yes"

    b7, b9, b12 = (f"v0.0.4-1-g{b_full[:n]}" for n in (7, 9, 12))
    check("identical strings", same(b7, b7), True)
    check("one commit, 7 vs 9 hex (the #1250 clone pair)", same(b7, b9), True)
    check("one commit, 12 vs 7 hex", same(b12, b7), True)
    check("a moved tag renames the count, not the commit", same(f"v0.0.4-5-g{b_full[:8]}", b9), True)
    check("a bare sha (a clone without tags) is the same commit", same(b_full[:10], b7), True)
    check("different commits are not the same build", same(b9, f"v0.0.4-2-g{c_full[:9]}"), False)
    check("dirty vs clean is not the same build", same(b9 + "-dirty", b7), False)
    check("dirty vs dirty of one commit is", same(b9 + "-dirty", b7 + "-dirty"), True)
    check("empty is never the same build", same("", b7), False)
    check("unknown is never the same build", same("unknown", b7), False)
    check("a commit the checkout cannot resolve is not the same build",
          same("v0.0.4-9-gdeadbee", "v0.0.4-9-gdeadbeef"), False)
    check("an exact tag equals only itself", same("v0.0.4", "v0.0.4"), True)
    check("an exact tag is not a describe of another commit", same("v0.0.4", b7), False)
    git(repo, "tag", "v0.0.5", b_full)
    check("a release tag landing on the deployed commit renames it, not rebuilds it", same("v0.0.5", b9), True)
    check("an exact tag the checkout lacks is not the same build", same("v9.9.9", b9), False)
    check("a dirty exact tag is not the clean build", same("v0.0.5-dirty", b9), False)

# Every comparison site uses it: no build id is compared as a string any more.
for pattern in (r'"\$running" [!=]= "\$target"', r'"\$ondisk" [!=]= "\$target"',
                r'"\$manifest" [!=]= "\$target"', r'"\$after" [!=]= "\$target"',
                r'"\$newv" = "\$target"', r'"\$got" = "\$newv"'):
    check(f"no string compare left: {pattern}", re.search(r"\[ " + pattern, TEXT) is None, True)

# ---- 2. seed_seats ------------------------------------------------------------------------
SEED = 'seats="not-run"\nlog() { printf \'%s\\n\' "$*" >&2; }\n' + extract_function("seed_seats")


def seed(stub: str | None, *, key: bool = True, env: dict | None = None) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        home = root / "hh"
        home.mkdir()
        if key:
            (home / "operator.key").write_text("{}")
        tools = root / "deploy" / "hestia" / "tools"
        tools.mkdir(parents=True)
        if stub is not None:
            (tools / "seed_seat_config.py").write_text(stub)
        full = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "HESTIA_ROLE")}
        full.update({"DEPLOY_ROOT": str(root / "deploy"), "HESTIA_HOME": str(home),
                     "LOG": str(root / "log")})
        full.update(env or {})
        r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + SEED + '\nseed_seats\necho "SEATS=$seats"'],
                           capture_output=True, text=True, env=full)
        log = (root / "log").read_text() if (root / "log").exists() else ""
        m = re.search(r"^SEATS=(.*)$", r.stdout, re.M)
        return r.returncode, (m.group(1) if m else ""), log


ADDS = ("import sys\nassert sys.argv[1:] == ['--add-missing', '--apply'], sys.argv\n"
        "print('host h, operator o')\nprint('Seeded 5 in one act (intent abc).')\n"
        "print('Every seeded seat\\'s projection rendered with its keys.')\n")
COMPLETE = "print('EVERY INSTALLED SEAT HAS A DOCUMENT - nothing to add.'.replace(' - ', ' — '))\n"
BROKEN = "import sys\nprint('need an Ed25519 backend: pip install pynacl OR cryptography')\nsys.exit(1)\n"

rc, seats, log = seed(ADDS)
check("adds: rc", rc, 0)
check("adds: verdict", seats, "ok(added)")
check("adds: the seeder's own lines reach the deploy log", "seed-seats: Seeded 5" in log, True)
rc, seats, _ = seed(COMPLETE)
check("complete: verdict", (rc, seats), (0, "ok(complete)"))
rc, seats, _ = seed(BROKEN)
check("a failing seeder never ends the cycle", rc, 0)
check("a failing seeder is named", seats.startswith("FAILED(rc=1: need an Ed25519 backend"), True)
rc, seats, _ = seed(None)
check("no seeder in the checkout", (rc, seats), (0, "skipped(no seeder in the checkout)"))
rc, seats, _ = seed(ADDS, key=False)
check("no operator key", (rc, seats), (0, "skipped(no operator key in HESTIA_HOME)"))
rc, seats, _ = seed(ADDS, env={"CLAUDECODE": "1"})
check("governed session (CLAUDECODE)", (rc, seats), (0, "refused(governed session)"))
rc, seats, _ = seed(ADDS, env={"HESTIA_ROLE": "role:x"})
check("governed session (HESTIA_ROLE)", (rc, seats), (0, "refused(governed session)"))
rc, seats, _ = seed(ADDS, env={"HESTIA_DEPLOY_SEED_SEATS": "0"})
check("explicit opt-out", (rc, seats), (0, "skipped(HESTIA_DEPLOY_SEED_SEATS=0)"))

# The inline claude-code probe declares the timeout it enforces: a fresh host has no registration
# for a stage-C gate to read one from, and the gate refuses gate.harness_timeout_unknown without it.
pg = extract_function("preflight_gate")
check("the inline probe declares HESTIA_HOOK_TIMEOUT_S", 'HESTIA_HOOK_TIMEOUT_S="$PROBE_TIMEOUT_S"' in pg, True)
gp = (HERE / "gate-preflight.py").read_text()
m = re.search(r"^PROBE_TIMEOUT_S = (\d+)", gp, re.M)
m2 = re.search(r"^PROBE_TIMEOUT_S=(\d+)", TEXT, re.M)
check("both preflight arms use one probe bound", (m and m.group(1), m2 and m2.group(1)),
      (m and m.group(1), m and m.group(1)))

# The ORDER is the fix: seed_seats runs inside install_hooks, before preflight_gate.
ih = extract_function("install_hooks")
check("install_hooks seeds before it preflights",
      0 <= ih.find("seed_seats") < ih.find("preflight_gate"), True)

if FAILS:
    print("FAIL\n  " + "\n  ".join(FAILS))
    sys.exit(1)
print("ok: same_build compares commits not spellings; seed_seats runs before the preflight and every arm is named")
