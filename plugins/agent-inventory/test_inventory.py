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
import sys
import tempfile
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
        # glob alone, so it is testable on a box that has never seen launchctl.
        home2 = tmp / "home2"
        (home2 / "Library" / "LaunchAgents").mkdir(parents=True)
        (home2 / "Library" / "LaunchAgents"
         / f"net.dpcars.{inventory.INSTALLED_BIN_NAME}.plist").write_text("<plist/>")
        inventory.HOME = home2
        check("launchd plist counts", inventory.periodic_trigger()[0],
              "launchd-agent-installed")
        # The paths are returned so a reader can re-derive the verdict rather than trust
        # it — the same reason `scope` exists at all.
        check("says where it looked", len(inventory.periodic_trigger()[2]), 3)
    finally:
        inventory.HOME = orig


if __name__ == "__main__":
    test_attribute()
    test_has_tag()
    test_fallback_enumeration()
    with tempfile.TemporaryDirectory() as d:
        test_verdict(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_periodic_trigger(Path(d))
    for f in FAILS:
        print("FAIL", f)
    print(f"{'FAILED' if FAILS else 'ok'}: {len(FAILS)} failure(s)")
    sys.exit(1 if FAILS else 0)
