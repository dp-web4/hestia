#!/usr/bin/env python3
"""Tests for the owner-scoped `governed` demotion (inventory.py).

WHY THESE EXIST AND NOT OTHERS. The split between MISWIRED (ours or unattributable —
demotes) and MISWIRED-3P (positively a stranger's — loud, never demotes) has one failure
mode that matters and it is SILENT: if an unrecognised dead gate is filed as third-party,
`governed` stays true while hestia's enforcement is gone (kimi-code, id=133 §2). The case
that must never regress is therefore case D — a dead gate with no marker either way — and
it is the one the live filesystem can no longer produce.

Which is the second reason this file exists. The split was written against a real
MISWIRED on CBP: `ruvector/.claude/settings.json` pointing at a devcontainer path.
(Historical: that fix was later REVERTED — ruvector is a fork of external work and was not
ours to rewrite — and the clone has since been deleted, so the case no longer exists on any
live filesystem. The fixtures below preserve it precisely because the world moved on.)
The config changed between the baseline run and the verification run, so the live evidence
for the change disappeared while the change was being made. A verdict this load-bearing cannot be checked by "run it and look
at today's machine" — today's machine is edited by other members mid-session.

Run: python3 test_inventory.py     (no pytest; exit 1 on failure)
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import inventory

FAILS: list[str] = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


# --- unit: attribution ------------------------------------------------------------
# Ownership is decided once, where the evidence is. `is_hestia` arrives pre-computed
# because for a MISSING target the content cannot be asked and the caller is the only
# place that could still read a live sibling target.
def test_attribute():
    check("hestia by flag",
          inventory.attribute("node /x/y.js", ["/x/y.js"], True)[0], "hestia")
    check("3p by command marker",
          inventory.attribute("npx claude-flow@alpha hooks pre-command", [], False)[0],
          "third-party")
    check("3p by target marker",
          inventory.attribute("node /w/.claude/helpers/hook-handler.cjs pre-bash",
                              ["/w/.claude/helpers/hook-handler.cjs"], False)[0],
          "third-party")
    # The default, and the whole point: a stranger we have never heard of is treated as
    # ours. Erring toward innocence is what makes a gate failure silent.
    check("unknown name is unattributable, not third-party",
          inventory.attribute("node /w/.claude/helpers/mystery-tool.js", [], False)[0],
          "unattributable")
    # Evidence rides with the verdict — a bare "third-party" nobody can audit is the
    # allowlist drifting in the dark.
    check("3p carries which marker matched",
          "claude-flow" in inventory.attribute("npx claude-flow hooks", [], False)[1],
          True)


# --- unit: tag matching -----------------------------------------------------------
# `startswith("MISWIRED")` also matches "MISWIRED-3P" — i.e. the naive predicate would
# have re-created the exact demotion the split removes, silently and in both consumers.
def test_has_tag():
    findings = ["MISWIRED-3P: PreToolUse enabled, target does not exist (owner: ...)",
                "DEAD_HOOK: Stop enabled, target does not exist (owner: ...)",
                "FRAGILE: hook target on the 9p mount"]
    check("3P does not match MISWIRED", inventory.has_tag(findings, "MISWIRED"), False)
    check("3P matches its own tag", inventory.has_tag(findings, "MISWIRED-3P"), True)
    check("MISWIRED matches itself",
          inventory.has_tag(["MISWIRED: x"], "MISWIRED"), True)


# --- integration: the verdict -----------------------------------------------------
class _FakeRegistry:
    """The registry seam, stubbed at the object rather than at its callers.

    `claude-code` is present and declares the roles; everything else is absent — which is
    also the production shape, since B is read from `origin/main` and most atlas ids name
    no plugin dir at all.
    """

    source = "origin/main"
    ref = "test"
    degraded = None

    def __init__(self, declared: dict):
        self._declared = declared

    def has(self, plugin_dir: str) -> bool:
        return plugin_dir == "claude-code"

    def harnesses(self) -> list[str]:
        return ["claude-code"]

    def expects(self, plugin_dir: str) -> dict:
        return dict(self._declared) if self.has(plugin_dir) else {}


def build(tmp: Path, extra_hooks: list[tuple[str, str]]) -> dict:
    """One agent record, from a config holding a LIVE hestia gate plus `extra_hooks`.

    The live gate is the control: every case below is governed-but-for the extra hook,
    so a difference in `governed` is attributable to the extra hook and nothing else.
    """
    gate = tmp / "hestia-gate.py"          # named so owned_by_hestia sees it by path...
    gate.write_text("# hestia gate\nimport sys\n")
    witness = tmp / "witness.py"           # ...and this one only by content, as deployed
    witness.write_text("# hestia witness\n")
    hooks: dict[str, list] = {
        "PreToolUse": [{"hooks": [{"type": "command", "command": f"python3 {gate}"}]}],
        "PostToolUse": [{"hooks": [{"type": "command", "command": f"python3 {witness}"}]}],
    }
    for event, command in extra_hooks:
        hooks.setdefault(event, []).append(
            {"hooks": [{"type": "command", "command": command}]})
    cfg = tmp / "settings.json"
    cfg.write_text(json.dumps({"hooks": hooks}))

    plugins = tmp / "plugins"
    (plugins / "claude-code").mkdir(parents=True, exist_ok=True)
    orig = (inventory.PLUGINS, inventory.config_scopes,
            inventory.real_executable, inventory.REGISTRY)
    inventory.PLUGINS = plugins
    inventory.config_scopes = lambda dirnames: [(cfg, None, "user")]
    inventory.real_executable = lambda exes, roots: "/usr/bin/claude"
    # ONE seam, because `inspect` now asks the registry TWICE — `has()` for B
    # (plugin_available) and `expects()` for the roles — and patching only the second
    # leaves `REGISTRY is None`, whose `plugin_available = ... if REGISTRY else False`
    # reads as "no plugin exists" and demotes `governed` for a reason the case under test
    # has nothing to do with. That is how these tests failed when the registry landed:
    # every case went False, including the two controls, so the suite reported the split
    # broken when what had moved was the fixture. Stub the object, not the functions.
    inventory.REGISTRY = _FakeRegistry({"gate": ["PreToolUse"], "witness": ["PostToolUse"]})
    try:
        return inventory.inspect("claude", [])
    finally:
        (inventory.PLUGINS, inventory.config_scopes,
         inventory.real_executable, inventory.REGISTRY) = orig


def test_verdict(tmp: Path):
    # A. control — hestia wired, nothing dead.
    a = build(tmp, [])
    check("A governed", a["governed"], True)
    check("A not miswired", a["miswired"], False)
    check("A gate_wired", a["gate_wired"], True)

    # B. a stranger's dead gate. Still a finding, still fails open, still loud — but the
    # remedy is in a repo we do not own, so it must not pin the machine.
    b = build(tmp, [("PreToolUse", f"node {tmp}/gone/.claude/helpers/hook-handler.cjs x")])
    check("B governed despite 3p dead gate", b["governed"], True)
    check("B flagged 3p", b["miswired_3p"], True)
    check("B not miswired", b["miswired"], False)
    check("B classify: own bucket", inventory.classify([b])["miswired_3p"], ["claude"])
    check("B classify: not miswired", inventory.classify([b])["miswired"], [])
    # ...and not swallowed into another gap either: the 3p bucket is a separate `if`, so
    # a real hestia gap on the same agent still gets reported alongside it.
    check("B classify: not ungoverned", inventory.classify([b])["ungoverned"], [])

    # C. our own dead gate. The founding case; must demote.
    c = build(tmp, [("PreToolUse", f"python3 {tmp}/gone/hestia-gate.py")])
    check("C demoted", c["governed"], False)
    check("C miswired", c["miswired"], True)

    # D. THE REGRESSION kimi named. hestia's migrated gates live at nameless ext4 paths
    # (`~/.claude/hooks/pre_tool_use.py`) precisely so the path does not say "hestia" —
    # and once the file is deleted there is no content left to ask. If unattributable
    # meant "not ours", this exact deletion would read as governed with enforcement gone.
    d = build(tmp, [("PreToolUse", f"python3 {tmp}/gone/pre_tool_use.py")])
    check("D unattributable demotes", d["governed"], False)
    check("D miswired", d["miswired"], True)
    check("D not filed as 3p", d["miswired_3p"], False)

    # E. a dead NON-gate hook is still DEAD_HOOK regardless of owner — the split changes
    # which findings are fatal, not which findings exist.
    e = build(tmp, [("PostToolUse", f"node {tmp}/gone/hook-handler.cjs x")])
    check("E dead observer is not miswired", e["miswired"], False)
    check("E dead observer is not 3p-miswired", e["miswired_3p"], False)
    check("E dead observer still reported",
          inventory.has_tag(e["findings"], "DEAD_HOOK"), True)


# --- unit: the fallback enumeration ------------------------------------------------
# The atlas guard used to be a hard `return` before search_roots(), so an atlas-less
# machine got no findings at all — including the ones that never needed atlas. What it
# actually loses is the ENUMERATION, and the property that must hold is the one that
# makes the degradation safe: a run on the short list can still report every finding, and
# can NEVER report OK. Sabotage-checked on CBP 2026-07-28 by deleting the unknowns append:
# the degraded run went straight to `OK ... 4 installed, 6 plugins, 4 governed`.
def test_fallback_enumeration():
    reg = _FakeRegistry({})
    ids = inventory.fallback_agent_ids(reg)
    # Every aliased id survives, so the harnesses whose on-disk names diverge from their
    # atlas id are still looked for by the right names.
    check("aliased ids kept", set(inventory.ALIASES) <= set(ids), True)
    # ...and `claude-code` does NOT appear as an id of its own. It is the PLUGIN dir for
    # atlas id `claude`, so adding it would inspect a phantom agent looking for a `.claude-code`
    # config dir and a `claude-code` executable that no machine has.
    check("plugin dir of an aliased id is not re-added", "claude-code" in ids, False)
    check("its atlas id is what is looked for", "claude" in ids, True)
    # A registry harness with no alias entry IS an id — that is how codex/gemini/cursor
    # stay in the universe on a machine with no atlas.
    reg2 = _FakeRegistry({})
    reg2.harnesses = lambda: ["claude-code", "codex", "gemini"]
    ids2 = inventory.fallback_agent_ids(reg2)
    check("unaliased plugin dirs become ids", {"codex", "gemini"} <= set(ids2), True)
    check("still no phantom claude-code", "claude-code" in ids2, False)
    # Sorted and de-duplicated: `known` is enumerated once per id and a repeat is a
    # doubled inspect() plus a doubled entry in every list downstream.
    check("sorted, unique", ids2 == sorted(set(ids2)), True)


# --- unit: this check's own third trigger -------------------------------------------
# install.sh installs the binary at step 1 and wires the schedule at step 2, so an abort
# in between (exit 127 on Darwin, where there is no systemctl) leaves a machine that
# answers on demand and never runs on its own. Nothing after the fact said so.
def test_periodic_trigger(tmp: Path):
    home = tmp / "home"
    (home / ".config" / "systemd" / "user").mkdir(parents=True)
    orig = inventory.HOME
    inventory.HOME = home
    try:
        check("no unit, no plist -> absent", inventory.periodic_trigger()[0], "absent")
        unit = home / ".config/systemd/user" / f"{inventory.INSTALLED_BIN_NAME}.timer"
        unit.write_text("[Timer]\n")
        # The distinction install.sh already draws in prose: written != enabled. A unit
        # file with no wants-symlink is a timer systemd has never been told to start.
        check("unit alone is not enabled", inventory.periodic_trigger()[0],
              "systemd-user-timer-installed-not-enabled")
        wants = home / ".config/systemd/user/timers.target.wants"
        wants.mkdir()
        (wants / f"{inventory.INSTALLED_BIN_NAME}.timer").write_text("")
        check("wants-symlink is the enable", inventory.periodic_trigger()[0],
              "systemd-user-timer-enabled")
        # Darwin's half, exercised from Linux: the launchd branch is reached by the plist
        # glob and `plistlib`, so it is testable on a box that has never seen launchctl.
        home2 = tmp / "home2"
        agents = home2 / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        inventory.HOME = home2
        plist = agents / f"io.hestia-{inventory.INSTALLED_BIN_NAME}.plist"

        # THE CASE THE GLOB GOT WRONG. A LaunchAgent with RunAtLoad and no schedule key
        # fires at login and never again; `launchctl bootstrap` takes it without comment
        # and `ls` cannot tell it from the real thing. Presence was never the schedule.
        def write(d):
            with plist.open("wb") as fh:
                plistlib.dump(d, fh)

        write({"Label": "x", "RunAtLoad": True})
        check("RunAtLoad alone is not a schedule", inventory.periodic_trigger()[0],
              "launchd-agent-installed-no-schedule")
        write({"Label": "x", "StartInterval": 3600})
        check("StartInterval is a schedule", inventory.periodic_trigger()[0],
              "launchd-agent-installed")
        write({"Label": "x", "StartCalendarInterval": {"Minute": 0}})
        check("StartCalendarInterval is a schedule", inventory.periodic_trigger()[0],
              "launchd-agent-installed")
        # launchctl would refuse this too, so nothing is scheduled either way — but "fix
        # the file" and "add a key" are different repairs, so they are different states.
        plist.write_text("<plist/>")
        check("a plist that will not parse says so", inventory.periodic_trigger()[0],
              "launchd-agent-unparseable")
        # Unreadable outranks no-schedule: the file this function could not read might
        # have been the scheduled one, and `no-schedule` would be a claim about it.
        second = agents / f"io.other-{inventory.INSTALLED_BIN_NAME}.plist"
        with second.open("wb") as fh:
            plistlib.dump({"Label": "y", "RunAtLoad": True}, fh)
        check("unreadable outranks no-schedule", inventory.periodic_trigger()[0],
              "launchd-agent-unparseable")
        # ...but one genuine schedule anywhere in the directory IS an hourly fire, whatever
        # else is lying next to it.
        with second.open("wb") as fh:
            plistlib.dump({"Label": "y", "StartInterval": 3600}, fh)
        check("any scheduled plist wins", inventory.periodic_trigger()[0],
              "launchd-agent-installed")
        second.unlink()
        plist.unlink()
        # The paths are returned so a reader can re-derive the verdict rather than trust
        # it — the same reason `scope` exists at all.
        check("says where it looked", len(inventory.periodic_trigger()[2]), 3)
    finally:
        inventory.HOME = orig


def test_interpreter_finding():
    """A broken pin must become a FINDING, never an exit code and never silence."""
    orig = os.environ.pop("HESTIA_INTERPRETER_PIN_BROKEN", None)
    try:
        check("an intact pin says nothing", inventory.interpreter_finding(), None)
        os.environ["HESTIA_INTERPRETER_PIN_BROKEN"] = "/tmp/gone-venv/bin/python3"
        got = inventory.interpreter_finding()
        check("a broken pin is reported", got is not None, True)
        # Both halves must be in the sentence: what was pinned, and what actually ran.
        # "the pin broke" without the replacement leaves the reader unable to tell whether
        # the run they are holding is trustworthy.
        check("names the pin", "/tmp/gone-venv/bin/python3" in got, True)
        check("names what ran instead", sys.executable in got, True)
    finally:
        os.environ.pop("HESTIA_INTERPRETER_PIN_BROKEN", None)
        if orig is not None:
            os.environ["HESTIA_INTERPRETER_PIN_BROKEN"] = orig


def test_wrapper_heredoc_is_inert():
    """The generated wrapper's comments must not be shell input (cbp, 2026-07-28).

    `cat > "$BIN" <<WRAP` is UNQUOTED and has to be — the wrapper interpolates $PYTHON,
    $BIN and $WORKSPACE at install time. That makes every line between the delimiters
    prose to a reader and shell input to bash, and this file's house style is markdown
    prose in shell comments. An unescaped backtick pair is command substitution: bash RUNS
    it during install and the generated wrapper gets the output. It shipped once — the
    review comment quoting `-x` and `launchd-agent-installed` executed both on a clean
    install and left holes in the wrapper's own sentences. `bash -n` does not catch this;
    it is valid shell. Nothing in the plugin's output changes when it happens, which is
    why it needs a test and not a convention.

    THE HAZARD IS THE HEREDOC, NOT THE WRAPPER (McNugget, 2026-07-28, measured on
    macOS 26.5 by installing). The rule above was right and it was checked in one place.
    install.sh writes THREE unquoted heredocs — WRAP, the systemd .service unit, and the
    launchd plist — and the last two carry prose comments in the same house style. Probed:
    a markdown backtick pair in an XML comment inside the plist heredoc,
    `<!-- ProcessType Background: throttled for `id -un` -->`. It RAN at install time and
    the shipped plist carried my username; `plutil -lint` said OK, `bash -n` said clean,
    and this suite said "ok: 0 failure(s)". So the check below scans every unquoted
    heredoc, not the one where the bug was found.

    AND THE ESCAPE-EXEMPTION LET THE THING IT GUARDS THROUGH. The `$(`/`${` check skipped
    any line containing `\\$` anywhere — which is nearly every prose line in WRAP, because
    they all quote `\\$PY`. Probed: a line reading `# prose about \\$PY and the pin under
    ${HOME}/bin` passed green, and the installed wrapper had my sandbox path baked into
    the sentence. Escapes are per-token, so the line is stripped of them and what remains
    is what bash will run.

    AND THE `$` HALF WAS STILL SCOPED THE WAY THE BACKTICK HALF HAD JUST STOPPED BEING
    (cbp, 2026-07-28, measured on Linux by installing). "Scan every heredoc, not the one
    where the bug was found" got applied to backticks and `$(`; the `$` expansion check
    stayed WRAP-only AND brace-only. Bare `$NAME` was refused nowhere. The probe is the
    one directly above with two characters deleted — `# prose about \\$PY and the pin
    under $HOME/.local/bin` — and it passed green, `bash -n` clean, and shipped a wrapper
    reading "the pin under /tmp/hli7/home/.local/bin". This file's whole house style is
    prose that writes `\\$PY`, `\\$PYTHON`, `\\$HOME`, `\\$PYENV_ROOT`: every one of those
    is ONE BACKSLASH from expanding, and the unbraced form is the likelier typo because it
    is the shorter one. So `${` was the harder half to type and the only half guarded.

    The fix is a whitelist, not a wider ban. A ban cannot work here — the unit and the
    plist EXIST to interpolate — but the set that may expand is small, known, and already
    written down in prose. Naming it turns "someone added an expansion" into a failing
    test instead of a silent one, which is the same tripwire shape as the delimiter list
    below. An unknown heredoc gets the empty set: a new generated file refuses every
    expansion until someone says which ones it meant.
    """
    src = (Path(__file__).parent / "install.sh").read_text()
    heredocs = _unquoted_heredocs(src)
    # Named, so that deleting a heredoc's guard by deleting its `cat` shows up as a count.
    check("all three unquoted heredocs found",
          sorted(d for d, _ in heredocs), ["EOF", "PLIST_EOF", "WRAP"])
    check("the wrapper heredoc was found", len(dict(heredocs).get("WRAP", "")) > 200, True)
    for delim, body in heredocs:
        # Command substitution is never wanted in a generated file: whatever it names, it
        # runs on the installing machine and the output is what ships. No exceptions, so
        # this half is the same for all three.
        live = [ln for ln in body.splitlines() if "`" in _unescaped(ln)]
        check(f"no unescaped backtick in the {delim} heredoc", live, [])
        # Every surviving `$` must be one of the pins this heredoc exists to write. This
        # subsumes the old `$(`/`${` pair: `$(` has no name, so it lands in the unnamed
        # bucket and is refused everywhere, and `${HOME}` is refused in WRAP by absence.
        allowed = _MAY_EXPAND.get(delim, frozenset())
        live = [f"{ln}   [${n}]" for ln in body.splitlines()
                for n in _live_expansions(ln) if n not in allowed]
        check(f"only the named pins expand in the {delim} heredoc", live, [])


def test_plist_xml_escaping():
    """The whitelist above renames the plist's pins to XML_*; this asks whether they escape.

    A PROBE THIS GUARD WAS NOT WRITTEN AROUND, applied to the guard I just wrote (McNugget,
    2026-07-28). The whitelist change is a RENAME CHECK: it fails if a raw `$HOME` comes
    back to the plist, and it says nothing about whether `xml_escape` escapes anything. Break
    the `s/&/\\&amp;/` in that sed and every static check above stays green — which is the
    same "the check names the thing instead of running it" shape this thread has now found
    four times. So this one runs it.

    `&`, `<` and `>` are legal in a POSIX path and are metacharacters in XML. Measured on
    macOS 26.5 with HESTIA_WORKSPACE=/tmp/mcn-sb2/R&D: plutil refused the generated plist
    ("unknown ampersand-escape sequence at line 10"), the installer removed it, and the
    periodic trigger was gone while the other two triggers installed clean — the wrapper
    quotes its interpolation and the hook goes through shlex.quote, so shell syntax already
    handled what XML did not.

    The round-trip is the assertion that matters: escaping is only correct if a parser gives
    the ORIGINAL path back. Verified live too — launchd holds `/tmp/mcn-sb3/R&D`, decoded,
    and the job ran with 0 bytes on stderr.
    """
    src = (Path(__file__).parent / "install.sh").read_text()
    m = re.search(r"^xml_escape\(\)\s*\{.*\}\s*$", src, re.M)
    check("xml_escape is defined in install.sh", bool(m), True)
    if not m:
        return
    probe = "/tmp/R&D/<a>/b & c"
    r = subprocess.run(["bash", "-c", m.group(0) + '\nxml_escape "$1"', "_", probe],
                       capture_output=True, text=True)
    check("xml_escape exits 0", r.returncode, 0)
    check("xml_escape escapes & < >", r.stdout, "/tmp/R&amp;D/&lt;a&gt;/b &amp; c")
    # The whole point: a parser must give the path back unchanged. `&` first in that sed or
    # the `&amp;` it just wrote gets escaped again into `&amp;amp;`, which round-trips wrong
    # rather than failing to parse — the failure this assertion exists for.
    #
    # CAUGHT, NOT RAISED, and that is not decoration: the sabotage probe for this test
    # (delete the `&` rule from the sed) makes the value UNPARSEABLE, and an uncaught
    # ParseError ends the run on a traceback with the checks after it never reached. A guard
    # that crashes is not a guard that reports — the same distinction as a wrapper that
    # exits 127 silently, one layer up.
    try:
        back = ET.fromstring(f"<r><string>{r.stdout}</string></r>")[0].text
    except ET.ParseError as e:
        back = f"<not well-formed XML: {e}>"
    check("the escaped value parses and decodes back to the path", back, probe)


def test_wrapper_shell_quoting():
    """The same question as the plist's, asked of the file that was excused from it.

    "Three generated files, three target syntaxes" excused the two shell ones as a
    category: the hook by `shlex.quote` — which is right, that IS the mechanism — and the
    wrapper by "it interpolates inside double quotes", which is not. Double quotes are the
    WEAK shell quoting: `$`, backtick, `\\` and `"` all keep their meaning inside them, and
    all four are legal in a POSIX path on both platforms (cbp, 2026-07-28, measured on
    Linux by installing, `bash -n` clean on the generated wrapper in every case).

    Two measured shapes, and the second is why this is not a nit:

    * `.../cost$avings` shipped as `${HESTIA_WORKSPACE:-/tmp/.../cost$avings}`. `$avings`
      is unset at RUN time, so every fire walked `/tmp/.../cost` — and reported
      `workspace from env`, because the wrapper's own `env` line had set it.
    * ``.../it`id`s`` shipped with the backtick pair intact, which is COMMAND SUBSTITUTION
      in the generated file. The path came back as `/tmp/.../ituid=1000(dp`: `id` ran, on
      every fire, under the user's timer.

    That second one is the backtick finding one layer down. Escaping the heredoc's PROSE
    stopped install.sh executing backticks at INSTALL time; nothing stopped a backtick
    arriving in a VALUE and executing at RUN time. A whitelist notices a NAME that expands
    and cannot notice what the named value CONTAINS — which is the axis the plist opened,
    applied to the file the plist's own finding excused.

    Runs the function, per the rule this suite adopted one test up: the whitelist change to
    SH_* is a rename check and stays green if `sh_pin` stops quoting. So this asserts a
    ROUND-TRIP through the real construct the wrapper uses — `${HESTIA_WORKSPACE:-$WS_PIN}`
    under /bin/sh, with the variable unset — because that is the only assertion that fails
    when the quoting is right in shape and wrong in effect.
    """
    src = (Path(__file__).parent / "install.sh").read_text()
    m = re.search(r"^sh_pin\(\)\s*\{.*\}\s*$", src, re.M)
    check("sh_pin is defined in install.sh", bool(m), True)
    if not m:
        return
    # Every character double quotes fail to hold, plus the one single quotes cannot hold.
    probe = "/tmp/cost$avings/it`id`s/o'brien/a\"b/back\\slash/R&D/50%off"
    r = subprocess.run(["bash", "-c", m.group(0) + '\nsh_pin "$1"', "_", probe],
                       capture_output=True, text=True)
    check("sh_pin exits 0", r.returncode, 0)
    check("sh_pin returns a single-quoted literal",
          r.stdout.startswith("'") and r.stdout.endswith("'"), True)
    # The wrapper's own line, with HESTIA_WORKSPACE unset so the pin is what is used. If
    # `id` were still substitutable the output would carry a uid; if `$avings` were still
    # live the path would be short. Either way this is an inequality, not a traceback.
    env = {k: v for k, v in os.environ.items() if k != "HESTIA_WORKSPACE"}
    back = subprocess.run(
        ["/bin/sh", "-c", f'WS_PIN={r.stdout}\nprintf %s "${{HESTIA_WORKSPACE:-$WS_PIN}}"'],
        capture_output=True, text=True, env=env)
    check("the pinned workspace survives /bin/sh unchanged", back.stdout, probe)
    # And the env-supplied path still wins, which is the wrapper's other half.
    env["HESTIA_WORKSPACE"] = "/tmp/from-env"
    back = subprocess.run(
        ["/bin/sh", "-c", f'WS_PIN={r.stdout}\nprintf %s "${{HESTIA_WORKSPACE:-$WS_PIN}}"'],
        capture_output=True, text=True, env=env)
    check("an inherited HESTIA_WORKSPACE still overrides the pin", back.stdout,
          "/tmp/from-env")


def test_unit_specifier_escaping():
    """A systemd unit is the THIRD syntax, not a second copy of the shell one.

    `%` is legal in a POSIX path and introduces a SPECIFIER in a unit file, and this is the
    only one of the four generated files where the common failure is SILENT — because most
    letters are a valid specifier (cbp, 2026-07-28, measured on systemd 255):

        /tmp/.../50%off      -> %o is the OS ID     -> ExecStart resolves to 50ubuntuff
        /tmp/.../100%uptime  -> %u is the user name -> 100dpptime
        /tmp/.../50%zdone    -> z is not a specifier -> "fatal error, unit will not be
                                started" in ExecStart, silently DROPPED in Environment=

    In the first two the unit parses clean, the timer enables, install.sh prints
    `installed: hourly timer`, and the hourly run walks a directory nobody named while the
    other two triggers get the right path. Nothing on either side says so — which is
    strictly worse than the plist case that opened this axis, where plutil refused and
    skip_periodic() reported the gap.

    Runs the function, and asks SYSTEMD for the round-trip rather than string-comparing:
    `systemd-analyze verify` names the RESOLVED ExecStart path in its not-executable error,
    so a probe pointed at a file that does not exist reports back exactly what systemd
    made of the escaping. Skipped, and SAID to be skipped, where systemd-analyze is absent
    (Darwin, minimal installs) — an unrun guard reported as clean is this plugin's subject.
    """
    src = (Path(__file__).parent / "install.sh").read_text()
    m = re.search(r"^sd_escape\(\)\s*\{.*\}\s*$", src, re.M)
    check("sd_escape is defined in install.sh", bool(m), True)
    if not m:
        return
    probe = "/tmp/50%off/100%uptime/a%%b"
    r = subprocess.run(["bash", "-c", m.group(0) + '\nsd_escape "$1"', "_", probe],
                       capture_output=True, text=True)
    check("sd_escape exits 0", r.returncode, 0)
    check("sd_escape doubles every percent", r.stdout,
          "/tmp/50%%off/100%%uptime/a%%%%b")
    if not shutil.which("systemd-analyze"):
        print("SKIPPED: sd_escape round-trip — no systemd-analyze on this machine "
              "(the string assertion above still ran)")
        return
    with tempfile.TemporaryDirectory() as d:
        unit = Path(d) / "sd-escape-probe.service"
        unit.write_text("[Unit]\nDescription=probe\n[Service]\nType=oneshot\n"
                        f"ExecStart={r.stdout}/NOPE\n")
        v = subprocess.run(["systemd-analyze", "--user", "verify", str(unit)],
                           capture_output=True, text=True)
        # The message names the path systemd resolved. Anything other than the probe back
        # means a specifier expanded — which is the failure, whether it errored or not.
        resolved = re.search(r"Command (\S+) is not executable", v.stderr)
        check("systemd reports back a resolved path", bool(resolved), True)
        if resolved:
            check("systemd decodes the escaped value to the original path",
                  resolved.group(1), probe + "/NOPE")


def test_unit_verdict():
    """"This unit is bad" and "I could not look" are different, and one of them deletes.

    FOUND BY RUNNING THE GUARD, NOT BY READING IT (cbp, 2026-07-28). The lint-before-load
    backstop was first written as "systemd-analyze rc != 0 means unloadable, remove the
    units" — the shape the plist's plutil block has. Its first end-to-end run, on a
    sandboxed install with no XDG_RUNTIME_DIR, deleted a perfectly good timer pair because
    systemd-analyze had said `Failed to initialize manager: No such device or address`.
    The CHECKER could not start; nothing was wrong with the units. A guard that reports on
    a question it never asked, failing in the direction that destroys, is the exact defect
    this plugin exists to find — so it is worth a test rather than a rewrite in silence.

    The rule that replaced the exit code: A UNIT MAY ONLY BE CONDEMNED ON A MESSAGE THAT
    NAMES IT. systemd prefixes real complaints with the unit; a manager that would not
    start names nothing of ours. That gives three verdicts, and the third is the one the
    exit code cannot express.
    """
    src = (Path(__file__).parent / "install.sh").read_text()
    m = re.search(r"^unit_verdict\(\) \{.*?^\}$", src, re.M | re.S)
    check("unit_verdict is defined in install.sh", bool(m), True)
    if not m:
        return

    def verdict(rc, out):
        r = subprocess.run(["bash", "-c", m.group(0) + '\nunit_verdict "$1" "$2" "$3"',
                            "_", str(rc), out, "hestia-agent-inventory"],
                           capture_output=True, text=True)
        return r.stdout

    check("clean verify is ok", verdict(0, ""), "ok")
    # rc=0 with output is systemd's "... ignoring": the unit loads, a setting was dropped.
    check("a dropped setting is degraded, not fatal",
          verdict(0, "/x/hestia-agent-inventory.service:5: Failed to resolve specifiers "
                     "in WS=/tmp/50%zdone, ignoring: Invalid slot"), "degraded")
    # The real fatal, verbatim from systemd 255.
    check("a fatal error that names the unit is bad",
          verdict(1, "/x/hestia-agent-inventory.service:5: Failed to resolve unit "
                     "specifiers in /tmp/50%zdone: Invalid slot\n"
                     "hestia-agent-inventory.service: Unit configuration has fatal error, "
                     "unit will not be started."), "bad")
    # THE REGRESSION. Verbatim from the run that deleted a good timer.
    check("a checker that could not start is unverified, NOT bad",
          verdict(1, "Failed to lookup RuntimeDirectory path: No such device or address\n"
                     "Failed to initialize manager: No such device or address"),
          "unverified")
    check("systemd-analyze missing is the same fact, arriving differently",
          verdict(1, "systemd-analyze is not installed"), "unverified")


# `<<-?` then an optionally quoted word; `(?!<)` so the `<<<junk` in install.sh's own
# prose about plutil is a herestring and not a delimiter named `<junk`.
_HEREDOC_RE = re.compile(r"""<<-?(?!<)\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1""")

# What each generated file is FOR, stated as the set of install-time values it may bake in.
# Deliberately hand-written rather than derived from the file: derived, it would agree with
# whatever the file does today and could never disagree with a mistake. Adding an
# interpolation means adding it here, in the same commit, on purpose.
_MAY_EXPAND = {
    # The wrapper pins scope and nothing else. Its body is otherwise prose about `\$PY`.
    # SH_*, not the raw names, for the same reason the plist takes XML_* (cbp, 2026-07-28):
    # this heredoc generates /bin/sh, and `$`, backtick, `\\` and `"` all keep their meaning
    # inside the double quotes that were said to answer it. A raw `$WORKSPACE` back in here
    # is a value reaching a syntax that cannot hold it — measured, a workspace path with a
    # backtick in it became command substitution in the shipped wrapper, run on every fire.
    # See the sh_pin block in install.sh.
    "WRAP": frozenset({"SH_PYTHON", "SH_BIN", "SH_WORKSPACE"}),
    # The systemd --user unit: what to run and where from — and SD_*, because a unit file
    # is the third syntax, not a second copy of the shell one. `%` is legal in a path and
    # is a SPECIFIER here; measured, `50%off` reached ExecStart as `50ubuntuff` with the
    # unit parsing clean. See the sd_escape block in install.sh.
    "EOF": frozenset({"SD_SRC_DIR", "SD_BIN", "SD_WORKSPACE"}),
    # The launchd plist: same, plus the paths launchd needs spelled out absolutely — and
    # every one of them XML-ESCAPED, which is why they are the XML_* names and not the raw
    # ones (McNugget, 2026-07-28). The raw names are deliberately NOT in this set: a `$HOME`
    # put back into the plist is a value reaching a syntax that cannot hold it, and this
    # whitelist is already the thing that notices a name it was not told about. `&`, `<` and
    # `>` are legal in a POSIX path and are metacharacters in XML; measured with a workspace
    # named `R&D`, plutil refused the plist and the periodic trigger was lost. See the
    # xml_escape block in install.sh.
    "PLIST_EOF": frozenset({"XML_BIN", "XML_HOME", "XML_LABEL", "XML_PATH",
                            "XML_LOG_DIR", "XML_WORKSPACE"}),
}

# A live `$` is either `${NAME}`, `$NAME`, or something with no name at all — `$(`, `$$`,
# `$?`, `$1`. The last group is never a pin, so it is reported under the name it has none
# of and refused everywhere by not being in any whitelist.
_EXPANSION_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*)|(.|$))")


def _live_expansions(line: str) -> list[str]:
    """The names bash would expand on this line, after its escapes are stripped.

    `$(`/`$$`/`$?` come back as the literal character so they read in a failure message,
    and so that nothing unnamed can be whitelisted by accident.
    """
    return [(m.group(1) or m.group(2) or m.group(3) or "$")
            for m in _EXPANSION_RE.finditer(_unescaped(line))]


def _unescaped(line: str) -> str:
    """The line with bash's escapes removed — i.e. what is left for bash to expand.

    Per token, not per line: one escaped `\\$` on a line says nothing about the next `$(`
    on that same line, and assuming otherwise is what let `${HOME}` through.
    """
    return line.replace("\\\\", "").replace("\\`", "").replace("\\$", "")


def _unquoted_heredocs(src: str) -> list[tuple[str, str]]:
    """Every `<<DELIM` heredoc in a shell source whose delimiter is UNQUOTED, as
    (delim, body). Quoted (`<<'EOF'`) delimiters are literal to bash and are the safe
    case, so they are not returned. Lines that are shell comments are not scanned for
    openers — this file talks about heredocs as much as it writes them.
    """
    lines = src.splitlines()
    out, i = [], 0
    while i < len(lines):
        m = None if lines[i].lstrip().startswith("#") else _HEREDOC_RE.search(lines[i])
        if m:
            quote, delim = m.group(1), m.group(2)
            j = i + 1
            while j < len(lines) and lines[j].strip() != delim:
                j += 1
            if j < len(lines):          # only a closed heredoc is a heredoc
                if not quote:
                    out.append((delim, "\n".join(lines[i + 1:j])))
                i = j
        i += 1
    return out


def test_printed_advice_is_pasteable():
    """The installer's own advice is a shell syntax too — the fifth surface.

    Four GENERATED FILES were counted and fixed (wrapper, hook, plist, unit). These two
    lines were exempted by not being a file: `on demand: ... --workspace $WORKSPACE` and
    `export HESTIA_WORKSPACE=$WORKSPACE`. They are not prose. One is a command a human is
    told to run; the other is a line they are told to put in their SHELL RC. Measured on
    macOS 26.5 by pasting them (McNugget, 2026-07-28):

        .../cost$avings  -> `$avings` unset -> .../cost, SILENT where that exists
        .../it`id`s      -> command substitution runs in the operator's shell, and the
                            export half persists `uid=501(...)` into their rc
        .../a b          -> truncates at the space (the ordinary macOS path)
        .../o'brien      -> parse error (the loud one, and the only safe outcome)

    Asserts a ROUND TRIP through /bin/sh, not the presence of quotes, for the reason the
    two tests above adopted: a check that greps for `'` stays green if `sh_pin` is swapped
    for something that quotes in shape and not in effect. So this runs the REAL sh_pin,
    against the REAL echo lines lifted from install.sh, and pastes the result.
    """
    src = (Path(__file__).parent / "install.sh").read_text()
    pin = re.search(r"^sh_pin\(\)\s*\{.*\}\s*$", src, re.M)
    check("sh_pin is defined in install.sh", bool(pin), True)
    ondemand = re.search(r'^echo "on demand:.*$', src, re.M)
    exportln = re.search(r'^echo "\s*\(or export HESTIA_WORKSPACE=.*$', src, re.M)
    check("the on-demand line is in install.sh", bool(ondemand), True)
    check("the export-to-rc line is in install.sh", bool(exportln), True)
    if not (pin and ondemand and exportln):
        return

    # TWO probes, and the second is the one that matters. The first carries every
    # character double quotes fail to hold; unpinned it is a PARSE ERROR, so a broken
    # pin shows up as empty output. That is the loud half, and on its own it would let
    # this test pass for the wrong reason — "the paste crashed" is not "the paste was
    # wrong", and the defect being guarded is SILENT. So the quiet probe holds only the
    # characters that corrupt without complaining (`$`, backtick, space): unpinned it
    # pastes CLEANLY and returns a different, non-empty path. Same correction the plist
    # test needed when `&`-escaped-last stayed well-formed and decoded wrong.
    probes = [
        ("loud",  "/tmp/cost$avings/it`id`s/o'brien/a\"b/back\\slash/a b/R&D/50%off"),
        ("quiet", "/tmp/cost$avings/it`id`s/a b/R&D"),
    ]
    env = {k: v for k, v in os.environ.items() if k != "HESTIA_WORKSPACE"}
    # Run the real function and the real lines. Nothing here is a copy of install.sh.
    # BOTH names are bound, deliberately: if this bound only the pinned one, reverting
    # a line to the raw `$WORKSPACE` would fail here on an EMPTY expansion — red for the
    # absence of a variable rather than for the defect, which is a probe that passes
    # without reproducing what it claims to reproduce.
    script = (pin.group(0) + '\nWORKSPACE="$1"\nSH_WORKSPACE="$(sh_pin "$1")"\n'
              + ondemand.group(0) + "\n" + exportln.group(0) + "\n")

    for label, probe in probes:
        r = subprocess.run(["bash", "-c", script, "_", probe],
                           capture_output=True, text=True)
        check(f"the advice lines print ({label})", r.returncode, 0)
        printed = r.stdout

        # Paste half 1: everything after `--workspace ` is one shell word, or it is a bug.
        arg = printed.split("--workspace ", 1)[1].splitlines()[0]
        back = subprocess.run(["/bin/sh", "-c", f"printf %s {arg}"],
                              capture_output=True, text=True, env=env)
        check(f"the printed --workspace argument pastes back unchanged ({label})",
              back.stdout, probe)

        # Paste half 2: the line the operator is told to put in their shell rc.
        line = printed.split("(or ", 1)[1].split(" in your shell rc", 1)[0]
        back = subprocess.run(
            ["/bin/sh", "-c", f'{line}\nprintf %s "$HESTIA_WORKSPACE"'],
            capture_output=True, text=True, env=env)
        check(f"the printed export line pastes back unchanged ({label})",
              back.stdout, probe)
        check(f"the printed export line runs nothing ({label})", back.stderr, "")


if __name__ == "__main__":
    test_attribute()
    test_has_tag()
    test_fallback_enumeration()
    test_interpreter_finding()
    test_wrapper_heredoc_is_inert()
    test_plist_xml_escaping()
    test_wrapper_shell_quoting()
    test_unit_specifier_escaping()
    test_printed_advice_is_pasteable()
    test_unit_verdict()
    with tempfile.TemporaryDirectory() as d:
        test_verdict(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_periodic_trigger(Path(d))
    for f in FAILS:
        print("FAIL", f)
    print(f"{'FAILED' if FAILS else 'ok'}: {len(FAILS)} failure(s)")
    sys.exit(1 if FAILS else 0)
