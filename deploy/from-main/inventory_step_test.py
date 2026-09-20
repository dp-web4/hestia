#!/usr/bin/env python3
"""`sync_atlas` and `install_inventory` may fail in every way they like, and never stop a deploy.

WHY THIS EXISTS (McNugget, 2026-09-19).

Both functions were added so that agent discovery deploys itself instead of depending on
somebody remembering to clone agent-atlas and run plugins/agent-inventory/install.sh. Their
contract is one sentence: DISCOVERY MUST NEVER BE ABLE TO STOP A DAEMON DEPLOY. web4 is a
build input, so its absence is a `die`; the atlas and the inventory are not, so every failure
sets a word that says what happened and returns 0.

The first draft broke that contract on its first line. It read the pin with

    want="$(grep -vE '...' "$pin" 2>/dev/null | head -1)"

and on a checkout with no pin file `grep` exits 2. hestia-deploy.sh is `set -euo pipefail`,
so the pipeline's status became the assignment's, and the WHOLE DEPLOY exited rc=2 -- no log
line, no summary, nothing -- from inside the function whose entire purpose is that it cannot
do that. It passed `bash -n`. It read correctly. It was found by running `--check` for real
and getting silence back.

So the thing pinned here is not the wording of any status. It is that each function, handed
each failure, RETURNS 0 UNDER `set -euo pipefail` and leaves a status a human can act on. A
harness that ran these without `set -e` would have passed the broken draft, which is why the
prelude below turns it on before anything else.

Run: python3 inventory_step_test.py     (no pytest; exit 1 on failure)
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "hestia-deploy.sh"
FAILS: list[str] = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def extract_function(text: str, fname: str) -> str:
    """The real function body, brace-matched from the real script -- not a copy of it."""
    m = re.search(rf"^{re.escape(fname)}\(\) *\{{\s*$", text, re.M)
    assert m, f"{fname}() not found in hestia-deploy.sh"
    depth, i = 0, m.start()
    for j in range(m.start(), len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    raise AssertionError(f"{fname}() is not brace-balanced")


def clean_env(**extra: str) -> dict:
    """The session running this test is itself governed (CLAUDECODE is set), which is exactly
    the marker install_inventory refuses on. Strip both markers so each case states its own."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDECODE", "HESTIA_ROLE", "HESTIA_WORKSPACE",
                        "HESTIA_ATLAS_DIR", "HESTIA_DEPLOY_INVENTORY", "HESTIA_ATLAS_URL")}
    env.update(extra)
    return env


def run(fn_src: str, call: str, deploy_root: Path, env: dict, report: str) -> tuple[int, str]:
    """Run `call` the way the script does: strict mode ON, then print the status variable."""
    prog = (f"set -euo pipefail\nDEPLOY_ROOT={deploy_root}\nLOG={deploy_root}/deploy.log\n"
            f"MODE=full\n{fn_src}\n{call}\nprintf 'STATUS=%s\\n' \"${report}\"\n")
    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True, env=env, timeout=120)
    m = re.search(r"^STATUS=(.*)$", r.stdout, re.M)
    return r.returncode, (m.group(1) if m else f"<no status; stderr: {r.stderr.strip()[:160]}>")


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    return r.stdout.strip()


def make_atlas_origin(tmp: Path) -> tuple[Path, str, str]:
    """A two-commit 'agent-atlas' to clone from. Returns (path, first sha, second sha)."""
    origin = tmp / "atlas-origin"
    (origin / "talk-to" / "claude").mkdir(parents=True)
    git(tmp, "init", "-q", "-b", "main", str(origin))
    (origin / "talk-to" / "claude" / "descriptor.md").write_text("---\nharness: Claude Code\n---\n")
    git(origin, "add", "."); git(origin, "commit", "-q", "-m", "one")
    first = git(origin, "rev-parse", "HEAD")
    (origin / "talk-to" / "sage").mkdir()
    (origin / "talk-to" / "sage" / "descriptor.md").write_text("---\nharness: SAGE\n---\n")
    git(origin, "add", "."); git(origin, "commit", "-q", "-m", "two")
    return origin, first, git(origin, "rev-parse", "HEAD")


def test_sync_atlas() -> None:
    with tempfile.TemporaryDirectory() as d:
        _sync_atlas_cases(extract_function(SCRIPT.read_text(), "sync_atlas"), Path(d))


def _sync_atlas_cases(fn: str, tmp: Path) -> None:
    origin, first, second = make_atlas_origin(tmp)
    url = {"HESTIA_ATLAS_URL": str(origin)}
    prelude = 'ATLAS_URL="${HESTIA_ATLAS_URL}"\natlas="none"\n'

    # A. THE REGRESSION. No pin file in the checkout. The first draft exited the script here.
    root = tmp / "A"; (root / "hestia" / "deploy").mkdir(parents=True)
    rc, st = run(prelude + fn, "sync_atlas", root, clean_env(**url), "atlas")
    check("A no pin file: the script SURVIVES (rc)", rc, 0)
    check("A no pin file: tracks origin/main, and does not claim to be pinned", st, second[:7])

    # B. Pinned, with the comment-and-blank preamble the real file carries.
    root = tmp / "B"; (root / "hestia" / "deploy").mkdir(parents=True)
    (root / "hestia" / "deploy" / "agent-atlas.pin").write_text(f"# why\n\n   # indented\n{first}\n{second}\n")
    rc, st = run(prelude + fn, "sync_atlas", root, clean_env(**url), "atlas")
    check("B pinned: rc", rc, 0)
    check("B pinned: first non-comment line wins, and it says so", st, f"{first[:7]}(pinned)")
    check("B pinned: the clone really is AT the pin", git(root / "agent-atlas", "rev-parse", "HEAD"), first)
    check("B pinned: a descriptor added after the pin is NOT enumerable",
          (root / "agent-atlas" / "talk-to" / "sage").exists(), False)

    # C. A pin that is not in the clone is a typo or a force-push. Say so; do not die, and do
    #    not silently fall through to origin/main as if the pin had never been written.
    root = tmp / "C"; (root / "hestia" / "deploy").mkdir(parents=True)
    (root / "hestia" / "deploy" / "agent-atlas.pin").write_text("0" * 40 + "\n")
    rc, st = run(prelude + fn, "sync_atlas", root, clean_env(**url), "atlas")
    check("C bad pin: rc", rc, 0)
    check("C bad pin: named as such", st.startswith("unpinned(pin 000000000"), True)

    # D. Cannot clone at all.
    root = tmp / "D"; (root / "hestia" / "deploy").mkdir(parents=True)
    rc, st = run(prelude + fn, "sync_atlas", root,
                 clean_env(HESTIA_ATLAS_URL=str(tmp / "no-such-repo")), "atlas")
    check("D clone fails: rc", rc, 0)
    check("D clone fails: status", st, "unavailable(clone failed)")

    # E. Cloned once, then the network goes away. Keep what we have, and say it is stale.
    root = tmp / "E"; (root / "hestia" / "deploy").mkdir(parents=True)
    run(prelude + fn, "sync_atlas", root, clean_env(**url), "atlas")
    git(root / "agent-atlas", "remote", "set-url", "origin", str(tmp / "gone"))
    rc, st = run(prelude + fn, "sync_atlas", root, clean_env(**url), "atlas")
    check("E fetch fails: rc", rc, 0)
    check("E fetch fails: keeps the clone and says stale", st, f"{second[:7]}(stale: fetch failed)")


FAKE_INSTALLER = """#!/usr/bin/env bash
# Stands in for plugins/agent-inventory/install.sh: records that it ran and with what scope.
set -e
bin="$HOME/.local/bin/hestia-agent-inventory"; mkdir -p "$(dirname "$bin")"
echo "ran ws=${HESTIA_WORKSPACE:-} atlas=${HESTIA_ATLAS_DIR:-}" >> "$HOME/installer-ran"
[ "${FAKE_SKIP_COPY:-}" = 1 ] || cp "$(dirname "$0")/inventory.py" "$bin.py"
cat > "$bin" <<W
#!/bin/sh
AT_PIN='${HESTIA_ATLAS_DIR:-}'
echo '{"${FAKE_KEY:-agent_enumeration}": "${FAKE_ENUM:-agent-atlas}"}'
W
chmod +x "$bin"
echo "${FAKE_BEHAVIOUR:-behaviour 1}" > "$HOME/trigger-surface"   # stands in for plist/unit/hook
[ "${FAKE_RC:-0}" = 0 ] || exit "$FAKE_RC"
# The inputs as supplied -- the same printf the real install.sh carries (case N2 holds the pair).
printf 'workspace=%s\\natlas=%s\\n' "${FAKE_RECORD_WS:-${HESTIA_WORKSPACE:-}}" "${HESTIA_ATLAS_DIR:-}" > "$bin.installed-with"
[ "${FAKE_SKIP_STAMP:-}" = 1 ] || cp "$0" "$bin.installed-by"   # the real one's LAST act too
"""


def test_install_inventory() -> None:
    with tempfile.TemporaryDirectory() as d:
        _install_inventory_cases(extract_function(SCRIPT.read_text(), "install_inventory"), Path(d))


def _install_inventory_cases(fn: str, tmp: Path) -> None:
    def seat(name: str, with_atlas: bool = True) -> tuple[Path, Path]:
        root, home = tmp / name / "deploy", tmp / name / "home"
        src = root / "hestia" / "plugins" / "agent-inventory"
        src.mkdir(parents=True); home.mkdir(parents=True)
        (src / "inventory.py").write_text("# inventory v2\n")
        (src / "install.sh").write_text(FAKE_INSTALLER)
        if with_atlas:
            (root / "agent-atlas" / "talk-to").mkdir(parents=True)
        return root, home

    def ran(home: Path) -> str:
        f = home / "installer-ran"
        return f.read_text().strip() if f.exists() else ""

    prelude = 'inventory=""\n'
    wsdir = tmp / "seat-workspace"
    wsdir.mkdir()
    ws = str(wsdir)

    # F/G. A governed session must not edit the config of the harness it runs in. Same two
    #      markers the members' installer refuses on -- and the installer must NOT have run.
    for marker in ("CLAUDECODE", "HESTIA_ROLE"):
        root, home = seat(f"gov-{marker}")
        rc, st = run(prelude + fn, "install_inventory", root,
                     clean_env(HOME=str(home), HESTIA_WORKSPACE=ws, **{marker: "1"}), "inventory")
        check(f"F {marker}: rc", rc, 0)
        check(f"F {marker}: refused", st, "refused(governed session)")
        check(f"F {marker}: the installer did not run", ran(home), "")

    # H. No workspace is NOT a reason to guess one. From this checkout install.sh would derive
    #    ~/.hestia/deploy and pin it into three triggers as though somebody had chosen it.
    root, home = seat("no-ws")
    rc, st = run(prelude + fn, "install_inventory", root, clean_env(HOME=str(home)), "inventory")
    check("H no workspace: rc", rc, 0)
    check("H no workspace: says what is missing and where", st, "skipped(no HESTIA_WORKSPACE in the deploy unit)")
    check("H no workspace: the installer did not run", ran(home), "")

    # H2. Set, but not a directory. The unit templates ship the key EMPTY, but an installer that
    #     renders placeholders and misses one leaves `__HESTIA_WORKSPACE__` behind, and a typo
    #     or an unmounted volume looks the same. install.sh would pin any of them into three
    #     triggers, each of which would then answer UNKNOWN about a place that is not there.
    for bogus in ("__HESTIA_WORKSPACE__", str(tmp / "not" / "here")):
        root, home = seat(f"bogus-{len(bogus)}")
        rc, st = run(prelude + fn, "install_inventory", root,
                     clean_env(HOME=str(home), HESTIA_WORKSPACE=bogus), "inventory")
        check(f"H2 {bogus[:22]}: rc", rc, 0)
        check(f"H2 {bogus[:22]}: refused, not pinned", st, "skipped(HESTIA_WORKSPACE is not a directory)")
        check(f"H2 {bogus[:22]}: the installer did not run", ran(home), "")

    # J. Nothing installed yet -> the installer runs, scoped to the seat's workspace and the
    #    DEPLOY's atlas, and the status reports the enumeration actually achieved.
    root, home = seat("fresh")
    env = clean_env(HOME=str(home), HESTIA_WORKSPACE=ws)
    rc, st = run(prelude + fn, "install_inventory", root, env, "inventory")
    check("J fresh: rc", rc, 0)
    check("J fresh: status names the enumeration", st, "ok(agent-atlas)")
    check("J fresh: scoped correctly", ran(home), f"ran ws={ws} atlas={root}/agent-atlas/talk-to")

    # I. Second cycle, nothing moved: bytes match and the pin matches -> do NOT reinstall.
    rc, st = run(prelude + fn, "install_inventory", root, env, "inventory")
    check("I unchanged: status", st, "ok(current)")
    check("I unchanged: the installer did not run a second time", ran(home).count("ran "), 1)

    # The checkout's inventory.py moves on; the installed COPY is now stale and nothing else
    # would ever notice. This is the whole reason the post-condition is `cmp`, not an rc.
    (root / "hestia" / "plugins" / "agent-inventory" / "inventory.py").write_text("# inventory v3\n")
    rc, st = run(prelude + fn, "install_inventory", root, env, "inventory")
    check("I stale copy: reinstalled", (st, ran(home).count("ran ")), ("ok(agent-atlas)", 2))

    # M. GPT's falsifier (PR #1071 HOLD). ONLY the installer changes: inventory.py and the atlas
    #    pin are byte-identical, which was everything the fast path looked at -- so a repaired
    #    plist, unit, hook registration or wrapper body answered ok(current) on every seat,
    #    forever. The installed surface now carries the installer that produced it.
    inst = root / "hestia" / "plugins" / "agent-inventory" / "install.sh"
    inst.write_text(FAKE_INSTALLER.replace("behaviour 1", "behaviour 2"))
    rc, st = run(prelude + fn, "install_inventory", root, env, "inventory")
    check("M installer-only change: the installer reran", (st, ran(home).count("ran ")), ("ok(agent-atlas)", 3))
    check("M installer-only change: the artifact carries the new behaviour",
          (home / "trigger-surface").read_text().strip(), "behaviour 2")
    rc, st = run(prelude + fn, "install_inventory", root, env, "inventory")
    check("M then unchanged: converged again", (st, ran(home).count("ran ")), ("ok(current)", 3))

    # N. cbp's falsifier (PR #1071 post-merge review). ONLY the workspace changes: installer,
    #    inventory.py and atlas are identical, which was everything the fast path compared, so
    #    an operator who corrected a wrong HESTIA_WORKSPACE in the deploy unit was told
    #    ok(current) while the timer and the SessionStart hook -- which do not inherit that
    #    unit's environment -- kept enumerating the old place. Current = installer AND inputs.
    wsb = tmp / "seat-workspace-b"
    wsb.mkdir()
    env_b = clean_env(HOME=str(home), HESTIA_WORKSPACE=str(wsb))
    rc, st = run(prelude + fn, "install_inventory", root, env_b, "inventory")
    check("N workspace-only change: the installer reran", (st, ran(home).count("ran ")), ("ok(agent-atlas)", 4))
    check("N workspace-only change: it ran FOR the new workspace",
          ran(home).splitlines()[-1], f"ran ws={wsb} atlas={root}/agent-atlas/talk-to")
    rc, st = run(prelude + fn, "install_inventory", root, env_b, "inventory")
    check("N then unchanged: converged again", (st, ran(home).count("ran ")), ("ok(current)", 4))
    # The atlas is an input too. It was the one the old grep did cover; it is now covered by
    # the same record, so losing the sibling must still be noticed.
    shutil.rmtree(root / "agent-atlas")
    rc, st = run(prelude + fn, "install_inventory", root, env_b, "inventory")
    check("N atlas-only change: the installer reran, unpinned",
          (st, ran(home).splitlines()[-1]), ("ok(agent-atlas)", f"ran ws={wsb} atlas="))

    # N2. The record has two writers that must agree byte for byte: install.sh and the deploy's
    #     expectation. The fake above stands in for one of them, so without this a drift in the
    #     REAL installer's line would reinstall every cycle on every seat with this file green.
    fmt = r"""printf 'workspace=%s\natlas=%s\n'"""
    real = (SCRIPT.parent.parent.parent / "plugins" / "agent-inventory" / "install.sh").read_text()
    check("N2 install.sh records its inputs with the deploy's format",
          fmt + r''' "${HESTIA_WORKSPACE:-}" "${HESTIA_ATLAS_DIR:-}" > "$BIN.installed-with"''' in real, True)
    check("N2 the deploy compares with that format, on the fast path and after the run",
          fn.count(fmt + r''' "$HESTIA_WORKSPACE" "$at" | cmp -s - "$bin.installed-with"'''), 2)

    # N3. An installer that records other inputs than it was given would reinstall every cycle
    #     and say ok every time. rc=0 is not evidence here either.
    root, home = seat("misrecords")
    rc, st = run(prelude + fn, "install_inventory", root,
                 clean_env(HOME=str(home), HESTIA_WORKSPACE=ws, FAKE_RECORD_WS="/somewhere/else"), "inventory")
    check("N3 records the wrong inputs: FAILED, not ok",
          st, "FAILED(installer rc=0, but .installed-with does not record the inputs it was given)")

    # M2. The stamp is the installer's LAST act, so one that lands the bytes and the wrapper
    #     and then does not finish has not converged, whatever its rc says.
    root, home = seat("unfinished")
    rc, st = run(prelude + fn, "install_inventory", root,
                 clean_env(HOME=str(home), HESTIA_WORKSPACE=ws, FAKE_SKIP_STAMP="1"), "inventory")
    check("M2 rc=0, bytes landed, never finished: FAILED, not ok",
          st, "FAILED(installer rc=0, but it did not record finishing: no current .installed-by)")

    # K. rc=0 is not evidence. An installer that exits 0 without landing the bytes is a FAILURE.
    root, home = seat("liar")
    rc, st = run(prelude + fn, "install_inventory", root,
                 clean_env(HOME=str(home), HESTIA_WORKSPACE=ws, FAKE_SKIP_COPY="1"), "inventory")
    check("K rc=0 but no bytes: rc", rc, 0)
    check("K rc=0 but no bytes: FAILED, not ok", st.startswith("FAILED(installer rc=0"), True)

    root, home = seat("boom")
    rc, st = run(prelude + fn, "install_inventory", root,
                 clean_env(HOME=str(home), HESTIA_WORKSPACE=ws, FAKE_RC="7"), "inventory")
    check("K installer fails: the DEPLOY survives", rc, 0)
    check("K installer fails: status carries the rc", st, "FAILED(rc=7)")

    # No atlas sibling (clone never succeeded): still install, unpinned, and let the inventory
    # itself report the narrower enumeration -- an honest degraded answer beats no answer.
    root, home = seat("no-atlas", with_atlas=False)
    rc, st = run(prelude + fn, "install_inventory", root,
                 clean_env(HOME=str(home), HESTIA_WORKSPACE=ws, FAKE_ENUM="built-in ALIASES + plugin registry"),
                 "inventory")
    check("no atlas sibling: rc", rc, 0)
    check("no atlas sibling: installs with NO pin", ran(home), f"ran ws={ws} atlas=")
    check("no atlas sibling: status shows the degraded enumeration", st, "ok(built-in ALIASES + plugin registry)")

    # A label the report does not carry must not end the deploy (grep exit 1 under pipefail).
    root, home = seat("no-label")
    rc, st = run(prelude + fn, "install_inventory", root,
                 clean_env(HOME=str(home), HESTIA_WORKSPACE=ws, FAKE_KEY="something_else"), "inventory")
    check("unreadable label: rc", rc, 0)
    check("unreadable label: says so rather than dying", st, "ok(enumeration unreadable)")

    # L. The operator's off switch.
    root, home = seat("off")
    rc, st = run(prelude + fn, "install_inventory", root,
                 clean_env(HOME=str(home), HESTIA_WORKSPACE=ws, HESTIA_DEPLOY_INVENTORY="0"), "inventory")
    check("L switched off", (rc, st, ran(home)), (0, "skipped(HESTIA_DEPLOY_INVENTORY=0)", ""))


def test_script_is_strict() -> None:
    check("the script is strict, which is the condition the regression needs",
          bool(re.search(r"^set -[a-z]*e[a-z]*u?[a-z]* *-?o? *pipefail|^set -euo pipefail",
                         SCRIPT.read_text(), re.M)), True)


def teardown_module() -> None:
    """pytest's channel. `check()` records instead of raising so that one run names every
    failure; under pytest nothing read that record, and the tests returned normally on a red
    file (GPT, PR #1071 review; tools/ci_selfexec_test.py names the shape). They also took
    (fn, tmp) parameters, which pytest reads as fixtures -- unrunnable there as well as
    unfailable. They take none now."""
    assert not FAILS, "\n".join(FAILS)


def main() -> int:
    test_script_is_strict()
    test_sync_atlas()
    test_install_inventory()
    for f in FAILS:
        print("FAIL", f)
    print(f"{'FAILED' if FAILS else 'ok'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
