#!/usr/bin/env python3
"""Agent inventory — three distinct inventories, and the gaps between them.

WHY THIS EXISTS. hestia only sees what routes through hestia, so an agent that is
installed but ungoverned is *structurally invisible to it*. On 2026-07-26 gemini-cli sat
on CBP with `hooksConfig.enabled: true` and a BeforeTool hook pointing at
`/tmp/gemini-live/hook.sh` — a leftover from live-verification that two reboots had
deleted. It read as governed, it was not, and no amount of looking at hestia could have
shown that. The absence had to be found from OUTSIDE. That is agent-atlas's read half
doing its job (dp): the registry says what *could* be here, the filesystem says what
*is*, and the delta is the ungoverned set — labelled, not excluded (web4 LCT §1.2:
inspectable evidence, never a prescribed verdict).

THREE INVENTORIES, NOT ONE (dp, 2026-07-26). The first cut of this script conflated
them and the conflation hid the actionable part:

    A. INSTALLED    — orchestrators actually present on this machine
    B. AVAILABLE    — hestia plugins that exist in the repo (built anywhere in the fleet)
    C. GOVERNED     — installed AND plugin available AND wired in AND the wiring resolves

C is not a third list so much as the intersection, and **the gaps between A, B and C are
the whole product**, because each gap has a different remedy:

    installed, no plugin exists      → UNGOVERNABLE here; someone must build the plugin
    installed, plugin exists, unwired→ UNGOVERNED; one install.sh away, cheapest fix
    wired but target missing         → MISWIRED; the worst state, because it reads as
                                       covered while failing open (the gemini case)
    plugin exists, not installed     → DORMANT; ready if that harness ever lands here.
                                       A plugin built on nomad is available to CBP the
                                       moment the CLI arrives — that is the fleet working.

THREE THINGS IT REFUSES TO GET WRONG, each a defect this fleet actually shipped:

1. `command -v <name>` is not an installed-ness test. It matches shell BUILTINS —
   `continue` is a bash keyword and it turned up as a phantom "installed agent" in the
   first hand-run. Resolve to a real file; never judge by name.
2. A config directory is not an installed agent. `~/.foo` outliving an uninstall is
   residue, reported as such. Installation is evidenced by an executable.
3. A configured hook is not a working hook, and an empty result is not a clean result.
   Verify the hook TARGET EXISTS; if the registry is unreadable, say UNKNOWN rather
   than render "nothing ungoverned" out of "could not look".

THE ONE ERROR UNDERNEATH ALL OF THEM (thor + cbp, 2026-07-26, thread coordination-1785083110).
Thor reviewed `209e154` and found it reported `OK` on a machine with two configured,
enabled, dead PreToolUse gates. Re-running that review against CBP found the same two dead
gates here, plus three more blind spots — and every one is the same mistake in a different
dimension: **the check treated "where I looked" as "where it is."**

    looked in $HOME/.claude          gates live in project scope too      (thor §2)
    looked in the working tree       plugins live on origin/main          (thor §4)
    looked at a default path         the workspace lives in $HESTIA_WORKSPACE (thor §5)
    looked for the string "hestia"   real gates never say "hestia"        (cbp §A)
    looked on $PATH                  binaries live under nvm/pyenv/...    (cbp §B)

And each one fails in the REASSURING direction: a narrower look yields a cleaner report.
Verified on CBP at 209e154 — deleting codex's real fail-closed PreToolUse gate leaves the
report at `status: OK, governed: [codex], miswired: []`, because the gate's target path
(`~/.codex/hooks/pre_tool_use.py`) does not contain the substring "hestia". That is the
founding gemini defect, reproduced by the file written to catch it.

So rule 3 gets a fourth clause, and it is the one that governs this file's design:

4. A CHECK MUST REPORT THE SCOPE IT ACHIEVED, AND ANY SCOPE IT COULD NOT ESTABLISH MUST
   DEGRADE TO `UNKNOWN`, NEVER TO `OK`. A governance check whose blind spots all read as
   clean manufactures exactly the confidence it exists to withhold. Every number here is
   emitted next to the evidence it was computed from (`scope` in the report), so a reader
   can falsify it instead of trusting it.

Two consequences worth stating plainly, because they are what changed:

  * DEAD-TARGET DETECTION IS NOT HESTIA-SCOPED. A gate that resolves to nothing fails open
    no matter who wrote it, so every hook target is stat'd regardless of owner. Only
    `wired` — "is hestia's adapter in place?" — remains a question about hestia.
  * WITNESSING IS NOT GATING. `wired` used to be satisfied by any hestia-shaped hook of any
    kind, so a machine with post-hoc observation and no enforcement read as governed.
    Plugins now declare which events they must occupy (`plugins/*/expects.json`) and the
    report gains `partial` — the state a machine sits in while it *looks* covered.

Exit 0 always. This is an observation, and an observation layer that can break a session
has become a gate. Findings go to stdout as JSON and (unless --no-witness) to the chain.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shlex
import sys
from pathlib import Path
from urllib import request as urlrequest

try:
    import tomllib
except ModuleNotFoundError:  # <3.11 — TOML harnesses degrade to UNKNOWN, not to clean
    tomllib = None

WORKSPACE = Path(os.environ.get("HESTIA_WORKSPACE", "/mnt/c/exe/projects/ai-agents"))
ATLAS = WORKSPACE / "agent-atlas" / "talk-to"
PLUGINS = WORKSPACE / "hestia" / "plugins"
HOME = Path.home()

# Plugin dirs that are shared machinery, not harness adapters.
NOT_A_HARNESS_PLUGIN = {"lib", "member-mesh", "agent-inventory"}

# Where atlas ids diverge from the names things actually have on disk. Anything not
# listed falls back to the atlas id for all three, which is right for most harnesses.
#   atlas id -> (executable names, config dirs, hestia plugin dir)
ALIASES = {
    "claude":        (["claude"],            [".claude"],              "claude-code"),
    "kimi_code_cli": (["kimi", "kimi-code"], [".kimi-code", ".kimi"],  "kimi"),
    "copilot_cli":   (["copilot"],           [".copilot"],             None),
    "qwen_code":     (["qwen"],              [".qwen"],                None),
    "roo_code":      (["roo"],               [".roo"],                 None),
    "kiro_cli":      (["kiro"],              [".kiro"],                None),
    "mistral_vibe":  (["vibe"],              [".mistral"],             None),
    "factory_ai_droid": (["droid"],          [".factory"],             None),
}
CONFIG_FILES = ("settings.json", "config.toml", "config.yaml", "config.json",
                "settings.local.json", "config.yml")


def names_for(atlas_id: str) -> tuple[list[str], list[str], str]:
    exes, dirs, plugin = ALIASES.get(atlas_id, (None, None, None))
    return (exes or [atlas_id],
            dirs or ["." + atlas_id],
            plugin or atlas_id)


# $PATH IS NOT AN INSTALLED-NESS TEST EITHER (cbp, 2026-07-26). Rule #1 rejected
# `command -v` because it matches builtins and replaced it with "a real file on PATH" —
# but PATH is process-local. nvm, pyenv, asdf and friends inject their bin dir from an
# interactive shell rc, so a systemd timer, a SessionStart hook and a login shell each
# resolve a DIFFERENT set of installed agents on the same machine at the same instant.
# Measured on CBP: `1 installed, 1 governed, OK` from the hook, `3 installed, 3 governed,
# OK` from the shell one second later, with codex and gemini labelled RESIDUE ("a
# leftover, not an installed agent") while both were live under ~/.nvm. The A inventory
# is what B and C are differenced against, so an under-read here silently cleans the
# whole report. Search the version-manager roots too, and SAY which roots were searched.
EXTRA_BIN_GLOBS = (
    ".nvm/versions/node/*/bin", ".local/bin", ".cargo/bin", ".bun/bin",
    ".npm-global/bin", ".deno/bin", ".pyenv/shims", ".asdf/shims",
    ".volta/bin", "go/bin", "bin",
    # harnesses that ship their own binary next to their config
    ".codex/bin", ".kimi-code/bin", ".kimi/bin", ".claude/bin",
)


def search_roots() -> list[str]:
    """Every directory this run will look in for an executable. Reported, not assumed."""
    roots = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    for pat in EXTRA_BIN_GLOBS:
        roots.extend(str(p) for p in sorted(HOME.glob(pat)) if p.is_dir())
    seen, out = set(), []
    for d in roots:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def real_executable(names: list[str], roots: list[str]) -> str | None:
    """A real executable in one of `roots` — NOT a shell builtin (see docstring #1)."""
    for name in names:
        for d in roots:
            p = Path(d) / name
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    return None


# ---- hook targets ----------------------------------------------------------------
# The old version scanned config TEXT for whitespace-delimited tokens starting with "/",
# then kept only those containing "hestia". Three filters, each of which alone hides a
# real dead gate:
#   * `$CLAUDE_PROJECT_DIR/../web4/.../pre_tool_use.py` does not start with "/" —
#     invisible. Both dead gates on Thor AND on CBP are written exactly this way.
#   * `~/.codex/hooks/pre_tool_use.py` is hestia's own deployed gate and the PATH
#     contains no "hestia" — invisible. Verified: deleting it still reports OK.
#   * a config that never says "hestia" was skipped whole — which is every non-hestia
#     gate on the machine, and the founding gemini config itself.
# So: parse the config structurally, expand the variables the engines expand, and stat
# every target regardless of who owns it.
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
INTERPRETERS = {"python", "python3", "node", "bash", "sh", "zsh", "ruby", "perl",
                "/bin/sh", "/bin/bash", "/usr/bin/env", "env", "uv", "deno"}
# Shell words that mean "what follows is not a hook target".
SHELL_BREAK = {"|", "||", "&&", ";", ">", ">>", "<", "&"}


def expand(tok: str, project_dir: Path | None) -> str:
    """Expand what the hook engines expand before exec'ing the command."""
    if project_dir is not None:
        for var in ("$CLAUDE_PROJECT_DIR", "${CLAUDE_PROJECT_DIR}",
                    "$CODEX_PROJECT_DIR", "${CODEX_PROJECT_DIR}"):
            tok = tok.replace(var, str(project_dir))
    tok = tok.replace("$HOME", str(HOME)).replace("${HOME}", str(HOME))
    if tok.startswith("~/"):
        tok = str(HOME) + tok[1:]
    return tok


def hook_targets(command: str, project_dir: Path | None) -> list[str]:
    """Filesystem paths a hook command will actually try to execute or import.

    Returns absolute, normalised paths. A command that resolves to no path at all
    (`npx claude-flow@alpha hooks pre-command ...`) yields nothing, which is correct —
    there is no target to stat.
    """
    try:
        toks = shlex.split(command)
    except ValueError:  # unbalanced quotes — fall back to whitespace
        toks = command.split()

    out: list[str] = []
    for tok in toks:
        if tok in SHELL_BREAK or ENV_ASSIGN.match(tok):
            continue
        if tok in INTERPRETERS or tok.startswith("-"):
            continue
        tok = expand(tok, project_dir)
        if "/" not in tok:
            continue
        # A quoted shell word is ONE shlex token, so a jq program (`.tool_input.command
        # // empty`) or an echo banner arrives here whole and contains slashes. Neither
        # is a path. Requiring no-whitespace and an explicit anchor keeps the pipeline
        # hooks in agentic-flow from being reported as a dozen dead targets — a check
        # that cries wolf gets muted, which is the same failure as reporting OK.
        if any(c.isspace() for c in tok):
            continue
        if not (tok.startswith("/") or tok.startswith("./") or tok.startswith("../")):
            continue
        p = Path(tok)
        if not p.is_absolute():
            if project_dir is None:
                continue
            p = project_dir / p
        try:
            out.append(os.path.normpath(str(p)))
        except (ValueError, OSError):
            continue
    return out


# ---- config scopes ---------------------------------------------------------------
# Claude-lineage precedence is managed -> user -> project -> local, and on both machines
# inspected so far the ENFORCEMENT half lives entirely in the last two while only
# observation lives in the first. Reading user scope alone therefore reports OK on every
# machine in this fleet that gates per-project. Project scopes are discovered under the
# workspace; the list of files actually read is reported, so "we found no gates" is
# distinguishable from "we did not look".
PROJECT_CONFIG_GLOBS = (".claude/settings.json", ".claude/settings.local.json",
                        ".codex/config.toml", ".gemini/settings.json")


def config_scopes(dirnames: list[str]) -> list[tuple[Path, Path | None, str]]:
    """(config file, project dir, scope label) for every scope this agent reads."""
    found: list[tuple[Path, Path | None, str]] = []
    for d in dirnames:
        home_dir = HOME / d
        if home_dir.is_dir():
            for fname in CONFIG_FILES:
                cfg = home_dir / fname
                if cfg.is_file():
                    found.append((cfg, None, "user"))
    if WORKSPACE.is_dir():
        for rel in PROJECT_CONFIG_GLOBS:
            if not any(rel.startswith(d + "/") for d in dirnames):
                continue
            for cfg in [WORKSPACE / rel] + sorted(WORKSPACE.glob("*/" + rel)):
                if cfg.is_file():
                    # $CLAUDE_PROJECT_DIR is the repo root, i.e. .claude's parent.
                    found.append((cfg, cfg.parent.parent, "project"))
    return found


def parse_config(cfg: Path) -> tuple[dict | None, str | None]:
    """Structured config, or (None, reason) — never a silent empty dict."""
    try:
        raw = cfg.read_bytes()
    except OSError as e:
        return None, f"unreadable: {e}"
    if cfg.suffix == ".toml":
        if tomllib is None:
            return None, "no tomllib on this interpreter (needs python >=3.11)"
        try:
            return tomllib.loads(raw.decode(errors="replace")), None
        except Exception as e:
            return None, f"unparseable TOML: {e}"
    try:
        return json.loads(raw.decode(errors="replace")), None
    except Exception as e:
        return None, f"unparseable JSON: {e}"


EVENT_NAME = re.compile(r"^(Pre|Post|Before|After|Session|User|Subagent|Stop|"
                        r"Notification|Compact|Tool)")


def walk_hooks(node, event: str | None = None, enabled: bool = True) -> list[dict]:
    """Every (event, command, enabled) triple in a config, whatever its shape.

    Three shapes are live in this fleet and all three are handled here rather than by
    three parsers: claude/gemini JSON `hooks.<Event>[].hooks[].command`, codex TOML
    `[[hooks.<Event>.hooks]]`, and kimi TOML flat `[[hooks]]` with `event = "..."`.
    """
    out: list[dict] = []
    if isinstance(node, dict):
        ev = node.get("event") if isinstance(node.get("event"), str) else event
        # #6 (thor): config-mention was treated as enablement. `"enabled": false` beside
        # a path that still resolves used to read as wired.
        en = enabled and node.get("enabled", True) is not False
        cmd = node.get("command")
        if isinstance(cmd, str) and cmd.strip():
            out.append({"event": ev, "command": cmd, "enabled": en})
        for key, val in node.items():
            if key in ("command", "event", "enabled", "type", "timeout", "matcher"):
                continue
            sub_ev = key if EVENT_NAME.match(key) else ev
            out.extend(walk_hooks(val, sub_ev, en))
    elif isinstance(node, list):
        for item in node:
            out.extend(walk_hooks(item, event, enabled))
    return out


def global_enable(cfg_data: dict) -> bool:
    """Harness-level kill switches. gemini's `hooksConfig.enabled` is the live one."""
    hc = cfg_data.get("hooksConfig")
    if isinstance(hc, dict) and hc.get("enabled") is False:
        return False
    for key in ("hooks_enabled", "hooksEnabled"):
        if cfg_data.get(key) is False:
            return False
    return True


def owned_by_hestia(command: str, targets: list[str]) -> bool:
    """Is this hook hestia's?

    NOT by path substring. hestia deploys its own gate to `~/.codex/hooks/pre_tool_use.py`
    and its witness to `~/.codex/hooks/witness.py` — ext4, off the 9p mount, and neither
    path says "hestia". Judging ownership by the path therefore reported codex's live
    witness hook as ROLE ABSENT. That is the same judge-by-name error as `command -v`
    matching builtins, one level up: the name is not the thing.

    So ask the file. These are small scripts and every hestia-deployed one identifies
    itself in its own text (observe.sh: 3 mentions, witness.py: 27, pre_tool_use.py: 36).
    """
    if "hestia" in command.lower():
        return True
    for t in targets:
        if "hestia" in t.lower():
            return True
        try:
            p = Path(t)
            if p.is_file() and p.stat().st_size <= 512_000:
                if "hestia" in p.read_text(errors="replace")[:65_536].lower():
                    return True
        except OSError:
            continue
    return False


def plugins_ref() -> str:
    """Which ref `plugins_available` was actually read from.

    B is read from the WORKING TREE, so a feature-branch or stale checkout under-counts
    it — and an under-count flips the remedy for an ungoverned agent from "run
    install.sh" to "someone must build the adapter". Thor's checkout was on
    `cleanup/hardbound-runtime-state` and reported 5 plugins where main has 8. Reading
    from `origin/main` is the fix; stamping the ref is the minimum, because it makes the
    number falsifiable by whoever reads the report.
    """
    head = PLUGINS.parent / ".git"
    try:
        if head.is_file():  # worktree
            head = Path(head.read_text().split("gitdir:")[1].strip())
        ref = (head / "HEAD").read_text().strip()
        return ref.split("ref: refs/heads/")[-1] if ref.startswith("ref:") else ref[:12]
    except Exception:
        return "unknown"


def expects(plugin_dir: str) -> dict:
    """Which hook events a plugin must occupy, and in which role (thor's §3 shape).

    `wired` used to ask "is anything hestia-shaped wired?", which one hook of any kind
    answers yes. Witnessing and gating are different acts with different failure modes:
    post-hoc observation CANNOT fail closed, and the whole point of the gate profile is
    that the pre-hook can. Absent an expects.json the roles are unknown and the agent is
    reported as such — not as governed.
    """
    path = PLUGINS / plugin_dir / "expects.json"
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    return {k: list(v) for k, v in data.items() if isinstance(v, list)}


def inspect(atlas_id: str, roots: list[str]) -> dict:
    exes, dirnames, plugin_dir = names_for(atlas_id)
    exe = real_executable(exes, roots)
    homes = [HOME / d for d in dirnames if (HOME / d).is_dir()]
    plugin_available = (PLUGINS / plugin_dir).is_dir()
    declared = expects(plugin_dir)

    rec: dict = {
        "agent": atlas_id,
        "plugin": plugin_dir if plugin_available else None,
        "plugin_available": plugin_available,
        # #2: installation is evidenced by an executable, not by a config dir.
        "installed": exe is not None,
        "executable": exe,
        "config_dirs": [str(h) for h in homes],
        "configs_read": [],
        "wired": False,
        "roles_wired": {},
        "unknown": [],
        "findings": [],
    }

    scopes = config_scopes(dirnames)
    # Accumulate across ALL scopes, then decide once. The old version assigned
    # `wired = True` unconditionally per config file, so the LAST hestia-mentioning
    # config silently repaired a demotion made by an earlier one: an agent could land in
    # `governed` and `miswired` at the same time. Harmless while only one file was read;
    # dominant the moment project scope is added, which is what this commit does.
    hestia_hooks: list[dict] = []
    for cfg, project_dir, scope in scopes:
        data, why = parse_config(cfg)
        if data is None:
            rec["unknown"].append(f"config not parsed ({cfg}): {why}")
            continue
        rec["configs_read"].append({"path": str(cfg), "scope": scope})
        cfg_enabled = global_enable(data)
        for hook in walk_hooks(data.get("hooks"), enabled=cfg_enabled):
            targets = hook_targets(hook["command"], project_dir)
            is_hestia = owned_by_hestia(hook["command"], targets)
            for target in targets:
                exists = Path(target).exists()
                # Name the exact file, not just the scope: CBP has this same dead gate in
                # two different project configs, and "[project: settings.local.json]"
                # twice reads as one duplicated finding rather than two places to fix.
                try:
                    label = str(cfg.relative_to(WORKSPACE))
                except ValueError:
                    label = str(cfg)
                where = f"[{scope}: {label}]"
                if not exists:
                    # A gate that resolves to nothing fails OPEN regardless of owner: a
                    # missing command exits 127, and by GATE_PROFILE.md §3 rule 2 any
                    # non-zero that is not an explicit `exit 2` is an ALLOW.
                    role = "gate" if hook["event"] in declared.get("gate", []) else "hook"
                    tag = "MISWIRED" if role == "gate" else "DEAD_HOOK"
                    state = "enabled" if hook["enabled"] else "disabled"
                    rec["findings"].append(
                        f"{tag}: {hook['event']} {state}, target does not exist "
                        f"{where} -> {target}")
                elif target.startswith("/tmp/"):
                    rec["findings"].append(
                        f"FRAGILE: hook target under /tmp, cleared on reboot "
                        f"{where} -> {target}")
                elif "/mnt/c/" in target:
                    # MECHANISM CORRECTED 2026-07-26 (CBP), because the previous wording made
                    # a quantitative claim and measurement refuted it. Old text: "cold-load can
                    # exceed the hook timeout". Measured on CBP with the Linux page cache
                    # dropped between runs:
                    #   hestia claude gate      9p 0.24-0.26s   ext4 0.18s   timeout 5s  (~20x)
                    #   web4-governance fallback 9p 0.68-0.74s  ext4 0.32s   budget  2s  (~3x)
                    # Nothing came near its timeout. Three fleet members migrated hooks off 9p
                    # on the strength of that sentence, and none of us had measured it — the
                    # claim was load-bearing and untested.
                    #
                    # The finding SURVIVES on a different mechanism. What bites on WSL2 is not
                    # slow steady-state cold-load, it is tail latency: the 9p mount can stall
                    # (host FS contention, Defender, a sleeping host), and a stall is UNBOUNDED,
                    # so no timeout margin protects against it. A 20x median margin says nothing
                    # about the tail, which is exactly the distinction the old wording collapsed.
                    # Second, real, cost: 0.06-0.35s per invocation is a latency tax on every
                    # tool call, independent of any timeout.
                    #
                    # Caveat on the numbers, so they are not overread the way the old claim was:
                    # drop_caches clears the LINUX page cache only. The Windows-side 9p server
                    # cache stays warm, so these are LOWER BOUNDS on true cold (post-boot) cost.
                    rec["findings"].append(
                        "FRAGILE: hook target on the 9p mount — unbounded stall risk (tail "
                        "latency, not median: measured median penalty is 0.06-0.35s against "
                        f"3-20x timeout margins), and these hooks fail OPEN {where} -> {target}")
            if is_hestia and hook["enabled"] and targets and all(
                    Path(t).exists() for t in targets):
                hestia_hooks.append({**hook, "targets": targets, "scope": scope})

    live_events = {h["event"] for h in hestia_hooks}
    rec["wired"] = bool(hestia_hooks)
    if declared:
        for role, events in declared.items():
            rec["roles_wired"][role] = sorted(e for e in events if e in live_events)
        missing = {role: [e for e in events if e not in live_events]
                   for role, events in declared.items()}
        for role, events in missing.items():
            # Only meaningful for a harness that is actually here. A dormant plugin has
            # no roles to be absent from, and saying so for every uninstalled harness
            # buries the one machine where enforcement really is missing.
            if events and exe is not None:
                rec["findings"].append(
                    f"ROLE ABSENT: no live hestia hook on {role} event(s) "
                    f"{', '.join(events)} — {'enforcement' if role == 'gate' else role} "
                    "is not present on this machine")
        rec["gate_wired"] = not missing.get("gate")
        rec["partial"] = bool(hestia_hooks) and not rec["gate_wired"]
    else:
        rec["gate_wired"] = None
        rec["partial"] = False
        # Only an ambiguity if the harness is actually here. A dormant plugin's roles
        # are moot, and reporting them as unknown would drag every machine to UNKNOWN
        # over harnesses it does not run.
        if plugin_available and exe is not None:
            rec["unknown"].append(
                f"plugin '{plugin_dir}' declares no expects.json — cannot tell "
                "observation from enforcement for this harness")

    # #2 again, but honestly: a config dir with no findable executable is residue ONLY if
    # nothing wired it. If hestia wiring is sitting in that config, then "we governed this
    # and now cannot find its binary" is an ambiguity, not a conclusion — and the old code
    # resolved it toward the clean answer. It is reported as UNKNOWN instead.
    if exe is None and homes:
        if hestia_hooks:
            rec["unknown"].append(
                f"config dir present and hestia-wired, but no executable found in any of "
                f"{len(roots)} searched roots — cannot tell 'uninstalled' from "
                "'installed outside the searched roots'")
        else:
            rec["residue"] = True
            rec["findings"].append(
                "RESIDUE: config dir present, no executable in any searched root, and "
                "nothing hestia-wired in it — a leftover, not an installed agent")

    rec["governed"] = bool(rec["installed"] and plugin_available and rec["wired"]
                           and rec["gate_wired"] is not False
                           and not any(f.startswith("MISWIRED")
                                       for f in rec["findings"]))
    return rec


def classify(recs: list[dict]) -> dict:
    """The gaps, each with its own remedy. This is the actionable part."""
    gaps: dict[str, list[str]] = {
        "miswired": [], "partial": [], "ungoverned": [], "ungovernable": [],
        "dormant_plugin": [], "unknown": []}
    for r in recs:
        if r["unknown"]:
            gaps["unknown"].append(r["agent"])
        if r["installed"] and any(f.startswith("MISWIRED") for f in r["findings"]):
            gaps["miswired"].append(r["agent"])
        elif r["installed"] and r["partial"]:
            # The state worth having: observation wired, enforcement absent. It is where
            # a machine sits while it LOOKS covered.
            gaps["partial"].append(r["agent"])
        elif r["installed"] and not r["governed"]:
            key = "ungoverned" if r["plugin_available"] else "ungovernable"
            gaps[key].append(r["agent"])
        elif r["plugin_available"] and not r["installed"]:
            gaps["dormant_plugin"].append(r["agent"])
    return gaps


def witness(report: dict) -> str:
    """Record the CLEAN result too, not only the alarm (thor, 2026-07-25): a log that
    only ever holds failures cannot distinguish 'checked, fine' from 'never checked'.

    The full MCP handshake is required, not a bare POST — initialize, initialized,
    then `hestia_connect` for an attributed session. The first cut here fired one
    unauthenticated POST, took 422 as success because nothing raised where it looked,
    and printed a clean report that recorded nothing. Attribution is not ceremony: an
    inventory of who is governed is itself an act, and an unattributed act is exactly
    the ungoverned thing this file is trying to find.
    """
    ep = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
    hdrs = {"Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"}

    def post(body: dict, extra: dict | None = None):
        req = urlrequest.Request(ep, data=json.dumps(body).encode(),
                                 headers={**hdrs, **(extra or {})})
        r = urlrequest.urlopen(req, timeout=10)
        return r.read().decode(), r.headers.get("mcp-session-id")

    def result_of(raw: str):
        for line in raw.splitlines():
            if line.startswith("data: {"):
                payload = json.loads(line[6:])
                if "result" in payload:
                    return json.loads(payload["result"]["content"][0]["text"])
        return None

    try:
        _, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "agent-inventory", "version": "1"}}})
        h = {"mcp-session-id": sid} if sid else {}
        post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)

        def call(tool, args):
            raw, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": tool, "arguments": args}}, h)
            return result_of(raw)

        conn = call("hestia_connect", {
            "plugin_id": os.environ.get("INVENTORY_PLUGIN", "agent-inventory"),
            "host_agent": "agent-inventory",
            "instance_name": f"inventory-{platform.node()}"}) or {}
        session = conn.get("sessionId") or conn.get("session_id")
        if not session:
            return f"not witnessed: connect refused ({conn})"
        res = call("hestia_request_witness", {
            "session_id": session, "event_type": "agent_inventory",
            "event_data": report}) or {}
        # Do not report success off "the call returned". Report it off the chain
        # saying so — the same distinction that makes the rest of this file worth
        # having.
        # The daemon's proof of record is the chain hash. Match on what it actually
        # returns, not on a plausible-looking field name.
        entry = res.get("witnessEntryHash") or res.get("witness_entry_hash")
        return f"witnessed {entry[:12]}" if entry else f"not witnessed: {res}"
    except Exception as e:  # observation must never break its caller
        return f"not witnessed: {type(e).__name__}: {e}"


def emit(report: dict, brief: bool) -> int:
    """One writer for both surfaces. The old code had an early return that printed
    indented JSON before the --brief branch was ever reached, so the surface built to
    emit one line dumped a blob into every session start on the UNKNOWN path (thor §5).
    Every exit now goes through here."""
    if brief:
        gaps = report.get("gaps") or {}
        line = (f"[agent-inventory] {report['status']} on {report.get('machine', '?')}")
        if "installed" in report:
            line += (f": {len(report['installed'])} installed, "
                     f"{len(report['plugins_available'])} plugins, "
                     f"{len(report['governed'])} governed")
        extra = [f"{k}={v}" for k, v in gaps.items() if v and k != "dormant_plugin"]
        if extra:
            line += " | " + " ".join(extra)
        if report.get("reason"):
            line += f" | {report['reason']}"
        print(line)
    else:
        print(json.dumps(report, indent=1))
    return 0


def main() -> int:
    argv = sys.argv[1:]
    brief = "--brief" in argv

    if not ATLAS.is_dir():
        return emit({"status": "UNKNOWN", "machine": platform.node(), "reason":
                     f"agent-atlas registry not readable at {ATLAS} — cannot "
                     "distinguish 'nothing ungoverned' from 'could not look'"}, brief)

    roots = search_roots()
    known = sorted(p.name for p in ATLAS.iterdir() if p.is_dir())
    recs = [inspect(a, roots) for a in known]
    available = sorted(p.name for p in PLUGINS.iterdir()
                       if p.is_dir() and p.name not in NOT_A_HARNESS_PLUGIN) \
        if PLUGINS.is_dir() else []
    installed = [r for r in recs if r["installed"]]
    governed = [r for r in installed if r["governed"]]
    gaps = classify(recs)
    fragile = sorted({r["agent"] for r in installed
                      if any(f.startswith("FRAGILE") for f in r["findings"])})

    # Rule 4: report the scope achieved, so every number above is falsifiable by the
    # reader instead of trusted. `plugins_available` in particular is read from the
    # WORKING TREE, so a feature-branch checkout under-counts it — and classify() sends
    # installed-and-unwired to `ungovernable` ("someone must build the adapter", the
    # expensive remedy) instead of `ungoverned` ("run install.sh") when it does. Stamping
    # the ref makes that visible rather than silently wrong.
    scope = {
        "workspace": str(WORKSPACE),
        "workspace_from_env": "HESTIA_WORKSPACE" in os.environ,
        "exe_search_roots": roots,
        "config_scopes_read": sorted({c["path"] for r in recs
                                      for c in r["configs_read"]}),
        "plugins_ref": plugins_ref(),
        "toml_supported": tomllib is not None,
    }
    unknowns = sorted({u for r in recs for u in r["unknown"]})
    if not scope["workspace_from_env"]:
        unknowns.append(
            f"HESTIA_WORKSPACE unset — fell back to the compiled-in default "
            f"{WORKSPACE}, which is only correct on the machine it was written on")

    # An unestablished scope degrades to UNKNOWN, never to OK (rule 4). MISWIRED still
    # outranks it: a known dead gate is worse news than an unknown.
    status = "OK"
    if gaps["miswired"]:
        status = "MISWIRED"
    elif gaps["partial"]:
        status = "PARTIAL"
    elif gaps["ungoverned"] or gaps["ungovernable"]:
        status = "UNGOVERNED_PRESENT"
    elif unknowns:
        status = "UNKNOWN"

    report = {
        "status": status,
        "machine": platform.node(),
        "registry_known": len(known),
        # A. installed  B. available  C. governed
        "installed": sorted(r["agent"] for r in installed),
        "plugins_available": available,
        "governed": sorted(r["agent"] for r in governed),
        "gaps": gaps,
        "fragile": fragile,
        "unknown": unknowns,
        "scope": scope,
        "detail": [r for r in recs
                   if r["installed"] or r["plugin_available"] or r.get("residue")
                   or r["unknown"]],
    }
    if "--no-witness" not in argv:
        report["witness"] = witness(report)
    return emit(report, brief)


if __name__ == "__main__":
    sys.exit(main())
