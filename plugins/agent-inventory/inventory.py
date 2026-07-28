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
    a STRANGER's gate target missing → MISWIRED-3P; same fail-open finding, but the
                                       remedy is in a repo we do not own, so it does not
                                       demote `governed` (see `attribute`)
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

And rule 4 has a time dimension, which the cut that added clause 4 promptly fell into
(cbp reviewing thor, 2026-07-26, thread coordination-1785090931). Widening the scan from
depth 1 to depth 3 took the run from 1.15s to **4m22s on CBP** — 3143 directories on a 9p
mount, `Path.resolve()` on every one of them, the whole walk repeated once per agent —
against a SessionStart hook budget of 10s. So:

5. A CHECK THAT CANNOT FINISH INSIDE ITS TRIGGER'S TIMEOUT HAS NOT DEGRADED TO `UNKNOWN`.
   IT HAS DEGRADED TO SILENCE, WHICH READS AS CLEAN. The budget is part of the scope.

A SIGKILLed hook emits nothing, and nothing reads as fine — so the previous cut fixed
"answers UNKNOWN on every machine that is not CBP" by replacing it with "answers nothing
on CBP." Same error, next dimension over, which is once again the error this file exists
to catch. The remedy is in `scan_projects()` and it is structural, not a benchmark: the
walk carries an explicit deadline and reports `scan_truncated` + `UNKNOWN` when it fires.

And clause 5 has a second half the deadline alone does not satisfy, which the next review
found (cbp, 2026-07-26, same thread). A budget that fires on EVERY run has not bounded the
scan, it has redefined it — and because the walk is level-order, the part it gives up is
never a random sample. It is always the deepest level, which is exactly the level that was
added to find the gate nobody could see. At the shipped 5s default CBP truncated 3/3 and
lost both of its depth-3 scopes, honestly and reproducibly. So:

5b. AN HONEST REPORT OF A SYSTEMATICALLY BIASED SAMPLE IS STILL CLAUSE 5's FAILURE. The
    budget has to fit the slowest machine measured, and the trigger's timeout has to be
    DERIVED from it rather than written down beside it — two numbers in two files kept in
    step by prose is the mitigation rule 3 refuses. See PROJECT_SCAN_BUDGET_S,
    SESSION_HOOK_TIMEOUT_S, and `hook_timeout_finding()`, which is this check run against
    its own trigger.

One justification did not survive contact with the measurement, and is corrected there
rather than quietly dropped: the deadline was argued for on "warm is not cold," and cold
turned out to be ~1.1x. Contention costs more than cold does. The deadline is still right
— an unbounded 9p stall is real — but for a different reason than the one it shipped with.

Two consequences worth stating plainly, because they are what changed:

  * DEAD-TARGET DETECTION IS NOT HESTIA-SCOPED. A gate that resolves to nothing fails open
    no matter who wrote it, so every hook target is stat'd regardless of owner. But the
    VERDICTS are hestia-scoped — `wired` and `governed` both answer "is hestia's
    enforcement in place?", and letting an owner-agnostic finding negate an owner-scoped
    verdict pinned this machine at MISWIRED over a stranger's container path, unfixable by
    any amount of hestia work. Findings owner-agnostic, verdicts owner-scoped, and the
    unattributable case counted as OURS so the error stays loud.
  * WITNESSING IS NOT GATING. `wired` used to be satisfied by any hestia-shaped hook of any
    kind, so a machine with post-hoc observation and no enforcement read as governed.
    Plugins now declare which events they must occupy (`plugins/*/expects.json`) and the
    report gains `partial` — the state a machine sits in while it *looks* covered.

Exit 0 always. This is an observation, and an observation layer that can break a session
has become a gate. Findings go to stdout as JSON and (unless --no-witness) to the chain.
"""
from __future__ import annotations

import json
import math
import os
import platform
import plistlib
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from urllib import request as urlrequest

try:
    import tomllib
except ModuleNotFoundError:  # <3.11 — TOML harnesses degrade to UNKNOWN, not to clean
    tomllib = None

DEFAULT_WORKSPACE = "/mnt/c/exe/projects/ai-agents"


def resolve_workspace(argv: list[str]) -> tuple[Path, str]:
    """Where the workspace came from, as well as what it is.

    SCOPE MUST SURVIVE THE TRIGGER (thor, 2026-07-26). `install.sh` wires three triggers
    and baked the workspace into exactly ONE of them — `Environment=` in the timer unit.
    A systemd unit's environment is not the shell's and not the hook's, so on Thor the
    hourly timer read `/home/dp/ai-workspace` while `hestia-agent-inventory --brief` from
    a terminal AND the SessionStart hook both fell back to the compiled-in CBP default and
    returned:

        UNKNOWN | agent-atlas registry not readable at /mnt/c/exe/projects/ai-agents/...

    Two of the three triggers were inert on every machine that is not CBP. This degraded
    honestly — rule 4 doing its job, UNKNOWN and not OK — but an on-demand check that
    cannot answer is not much better than one that answers wrong, and the SessionStart
    trigger exists precisely so a session opens KNOWING. So the workspace is now an
    explicit `--workspace` argument that install.sh writes into all three call sites, and
    the resolution order is reported rather than assumed.
    """
    for i, a in enumerate(argv):
        if a == "--workspace" and i + 1 < len(argv):
            return Path(argv[i + 1]), "argv"
        if a.startswith("--workspace="):
            return Path(a.split("=", 1)[1]), "argv"
    if "HESTIA_WORKSPACE" in os.environ:
        return Path(os.environ["HESTIA_WORKSPACE"]), "env"
    return Path(DEFAULT_WORKSPACE), "default"


# Rebound in main() once argv is known. Module scope keeps the import-time shape for
# anything that reads these directly.
WORKSPACE = resolve_workspace([])[0]
WORKSPACE_SOURCE = "default"
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


def fallback_agent_ids(reg: "Registry") -> list[str]:
    """The agent universe when agent-atlas is unreadable — narrower, and it says so.

    WHY THIS EXISTS (McNugget, 2026-07-28, measured on a box with no atlas clone). The
    atlas guard used to be a hard `return`: UNKNOWN in 0.079s, before `search_roots()`,
    before the walk, before a single hook target was stat'd. Rule 4 as written — but it
    applied "could not look" to dimensions it COULD look at. A dead `PreToolUse` gate is a
    stat call, not a registry lookup; so are the A inventory, FRAGILE, and the hook-timeout
    finding. Inventory B is read from `plugins/` at `origin/main` and never touched atlas
    either. What atlas actually supplies is the ENUMERATION — the universe of agent ids to
    go looking for — and losing it costs the ids outside this file's own table, not the
    findings about the ids inside it.

    So the degradation is now sized to the loss: enumerate from what is on hand, run the
    whole walk, and carry the gap in `unknowns` so the status ladder can never reach OK.
    A machine with no atlas gets the owner-agnostic half of the check plus an honest
    "there may be agents here I never looked for", instead of nothing plus prose.

    Known-incomplete BY CONSTRUCTION, which is the point: `ALIASES` is only the ids whose
    on-disk names diverge, and the registry only names harnesses hestia has an adapter
    for. An agent that is installed here, absent from both, and ungoverned is exactly what
    this run cannot see — hence UNKNOWN, never OK.
    """
    ids = set(ALIASES)
    covered = {names_for(a)[2] for a in ids}
    ids.update(p for p in reg.harnesses() if p not in covered)
    return sorted(ids)


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

# A REPO IS NOT ALWAYS A DIRECT CHILD OF THE WORKSPACE (thor, 2026-07-26). The scan was
# `WORKSPACE.glob("*/" + rel)` — depth 1 exactly. On Thor that missed three real project
# scopes, and one of them, `synchronism/manuscripts/.claude/settings.local.json`, holds a
# THIRD enabled PreToolUse gate pointing at the same path that was deleted from web4 on
# 2026-02-05. The machine reported two dead gates because two is how many the glob could
# reach. Nested checkouts (a repo vendored inside a repo, a manuscripts subtree, a
# monorepo package) are ordinary, so the scan goes deeper — and skips the directories
# where depth is vendored rather than structural, because `node_modules` alone contributes
# hundreds of `.claude/settings.local.json` files on this box that belong to nobody here.
PROJECT_SCAN_DEPTH = 3
SKIP_DIRS = {"node_modules", "vendor", "target", "dist", "build", "site-packages",
             ".venv", "venv", ".git", "__pycache__", ".next", ".cache"}

# Clause 5's structural half, and it has two parts: a walk that stops when it runs out of
# budget and SAYS it stopped, and a budget large enough that stopping is the exception.
# The first cut shipped only the first part.
#
# THE DEFAULT BUDGET DID NOT FIT THE MACHINE IT WAS WRITTEN FOR (cbp, 2026-07-26). Four
# full-depth walks of the same 3143 directories on CBP's 9p mount:
#
#     6.79s   warm, quiet
#     7.15s   cold (drop_caches)
#     7.84s   cold (drop_caches)
#     9.31s   warm, with a sibling `claude -c` working the tree
#
# At 5.0s that truncated on EVERY run (3/3 consecutive: 2373 / 2184 / 2157 of 3143 dirs),
# and the two scopes it dropped were both of the depth-3 ones. A level-order walk spends
# its budget breadth-first, so truncation is never a random sample — the loss is always at
# maximum depth, which is precisely the level DEPTH+1 was added to reach. An honest report
# of a systematically biased sample is rule 5's failure in a smaller hat.
#
# Two things measurement corrected, kept next to the number because that is this file's
# whole ethic:
#   * COLD IS ~1.1x, NOT AN ORDER OF MAGNITUDE. The previous cut justified this deadline
#     with "1.5s warm is not 1.5s cold" and noted that nobody in the fleet had taken the
#     cold number. CBP took it: 7.15 / 7.84 cold against 6.79 warm. (A lower bound —
#     drop_caches clears the Linux page cache; the Windows side of 9p stays warm.) The
#     deadline is still right, but for 9a2e124's reason — an unbounded 9p stall — not for
#     cold-versus-warm, and the justification should not outlive the measurement.
#   * CONTENTION COSTS MORE THAN COLD DOES. The slowest run was warm, with a sibling
#     session working the tree — and on this fleet a contended box is the NORMAL state,
#     not the pathological one.
#
# So the budget clears the slowest run anyone has measured, with headroom. THE BUDGET IS A
# CEILING, NOT A COST: it is a deadline, so a machine that finishes in 0.18s (thor, ext4,
# 1837 dirs) pays exactly nothing for a large one. A small budget does not buy speed on
# fast machines; it buys guaranteed loss of the deepest scopes on slow ones.
PROJECT_SCAN_BUDGET_S = float(os.environ.get("HESTIA_INVENTORY_SCAN_BUDGET", "12.0"))

# ...and the trigger's timeout is DERIVED from that, not written down beside it.
#
# Clause 5 couples two numbers that live in two files — this constant, and a `timeout`
# install.sh writes into ~/.claude/settings.json. Nothing but memory held them together,
# so CBP's review had to say it in prose: "moved together — either half alone re-creates
# clause 5's own cliff (8s walk + ~1s overhead against a 10s SIGKILL is silence again)."
# A rule maintained by whoever read the review is what rule 3 refuses. Two seams close it:
# install.sh asks the binary for this number instead of carrying a copy, and the binary
# re-checks the installed hook against it at run time (`hook_timeout_finding`), so drift
# is DETECTED rather than remembered.
POST_SCAN_RESERVE_S = 8.0   # config parses, git reads, witness write — worst observed ~1s
SESSION_HOOK_TIMEOUT_S = int(math.ceil(PROJECT_SCAN_BUDGET_S + POST_SCAN_RESERVE_S))

# The name every trigger invokes (install.sh puts it on ~/.local/bin). Fixed, so the
# self-check below can ask "what will the harness actually run?" even when this file is
# being run from the repo copy under a different name.
INSTALLED_BIN_NAME = "hestia-agent-inventory"


def _config_dir_files() -> dict[str, tuple[str, ...]]:
    """PROJECT_CONFIG_GLOBS, inverted: config dir -> the files wanted inside it."""
    out: dict[str, list[str]] = {}
    for rel in PROJECT_CONFIG_GLOBS:
        cdir, fname = rel.split("/", 1)
        out.setdefault(cdir, []).append(fname)
    return {cdir: tuple(fs) for cdir, fs in out.items()}


CONFIG_DIR_FILES = _config_dir_files()

_SCAN: dict[str, list[Path]] | None = None
SCAN_STATS: dict = {}


def scan_projects() -> dict[str, list[Path]]:
    """Every project config file under the workspace, found in ONE walk. Memoised.

    THE SCAN COST MORE THAN THE TRIGGER HAD (cbp, 2026-07-26 — rule 5 above). The
    depth-3 rewrite was correct about where to look and wrong about what that costs.
    Isolated on CBP, 3143 directories on the /mnt/c 9p mount:

        Path.iterdir() + is_dir() + resolve() per dir      43.0s   one walk
        os.scandir()   + realpath only when is_symlink()    1.5s   same 3142 dirs

    `Path.resolve()` is a full realpath chain per directory, and the separate `is_dir()`
    re-stats what the dirent already answered. Three multipliers on top of that: the walk
    ran once per (agent x matching glob) with no memoisation — four times — and then
    `.is_file()` was called on all 3143 candidates x 4 rels, ~12.5k more stats for a few
    dozen real hits. 4m22s total, against a 10s hook budget.

    So: walk once, and notice the config dirs WHILE reading each directory's entries.
    `.claude` either is or is not in the dirent list you already have, which turns 12.5k
    speculative stats into one per config dir that actually exists.

        as submitted                                            262s
        + scandir, lazy realpath, memoised walk                  21s
        + notice config dirs during the walk                     5.8s   identical findings

    SCAN DEPTH+1, DESCEND DEPTH. A directory only becomes a candidate project root once
    something has read ITS entries, so the deepest level must be scanned even though it is
    never descended into. Recording `parent` as you scan it and stopping at DEPTH silently
    drops every project root at the deepest level — 2 of 19 scopes on CBP, and the whole
    point of going deeper was the scope at depth 2 nobody could see.

    Symlinked repos are still followed (a workspace assembled out of links is a normal
    layout) and the cycle guard still resolves — but only for entries that ARE symlinks,
    which is where the 43s went. Aliasing that survives that (a symlinked ANCESTOR makes
    two literal paths for one inode) is caught by deduplicating the found files on their
    real paths, which is a few dozen realpaths rather than a few thousand.
    """
    global _SCAN
    if _SCAN is not None:
        return _SCAN

    found: dict[str, list[Path]] = {rel: [] for rel in PROJECT_CONFIG_GLOBS}
    started = time.monotonic()
    deadline = started + PROJECT_SCAN_BUDGET_S
    truncated = False
    scanned = 0

    def note(root: Path, names: set[str]) -> None:
        for cdir, fnames in CONFIG_DIR_FILES.items():
            if cdir not in names:
                continue
            for fname in fnames:
                cfg = root / cdir / fname
                if cfg.is_file():
                    found[f"{cdir}/{fname}"].append(cfg)

    try:
        seen = {os.path.realpath(WORKSPACE)}
    except OSError:
        seen = {str(WORKSPACE)}
    frontier = [WORKSPACE]
    levels_complete = 0
    trunc_level: int | None = None
    trunc_done = trunc_of = 0
    for level in range(PROJECT_SCAN_DEPTH + 1):
        nxt: list[Path] = []
        for done, parent in enumerate(frontier):
            if time.monotonic() > deadline:
                truncated = True
                trunc_level, trunc_done, trunc_of = level, done, len(frontier)
                break
            names: set[str] = set()
            children: list[tuple[Path, bool]] = []
            try:
                with os.scandir(parent) as it:
                    for entry in it:
                        names.add(entry.name)
                        if level == PROJECT_SCAN_DEPTH or entry.name in SKIP_DIRS:
                            continue
                        try:
                            if not entry.is_dir():
                                continue
                            children.append((Path(entry.path), entry.is_symlink()))
                        except OSError:
                            continue
            except OSError:
                continue
            scanned += 1
            note(parent, names)
            for child, is_link in sorted(children, key=lambda c: c[0].name):
                try:
                    real = os.path.realpath(child) if is_link else str(child)
                except OSError:
                    continue
                if real in seen:
                    continue
                seen.add(real)
                nxt.append(child)
        if truncated:
            break
        levels_complete = level + 1
        frontier = nxt

    for rel, paths in found.items():
        uniq, real_seen = [], set()
        for cfg in paths:
            try:
                real = os.path.realpath(cfg)
            except OSError:
                real = str(cfg)
            if real in real_seen:
                continue
            real_seen.add(real)
            uniq.append(cfg)
        found[rel] = uniq

    SCAN_STATS.update({
        "dirs_scanned": scanned,
        "seconds": round(time.monotonic() - started, 3),
        "truncated": truncated,
        # WHERE the walk stopped, which a level-order walk can state exactly: levels
        # 0..levels_complete-1 are whole, `truncated_at_level` is partial at
        # level_done/level_of parents, and every deeper level was never enumerated at all.
        #
        # The field this replaces, `unscanned_frontier`, reported len(frontier) for the
        # level in progress — which counted parents already scanned and omitted every
        # deeper level, so on CBP it read 876 + 2305 = 3181 against a true 3143 (cbp,
        # 2026-07-26). It erred toward alarming, which is the safe direction and not the
        # standard: a number emitted next to a claim has to be falsifiable, and this one
        # was not the count it named. The level is also strictly more actionable, because
        # the walk being level-order is exactly what makes the loss predictable.
        "levels_complete": levels_complete,
        "truncated_at_level": trunc_level,
        "level_done": trunc_done,
        "level_of": trunc_of,
    })
    _SCAN = found
    return _SCAN


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
        scanned = scan_projects()
        for rel in PROJECT_CONFIG_GLOBS:
            if not any(rel.startswith(d + "/") for d in dirnames):
                continue
            for cfg in scanned[rel]:
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


# POSITIVE third-party evidence, for the one case where no other kind exists.
#
# `owned_by_hestia` prefers content — "the name is not the thing" — but a dead hook is
# precisely the case where the content is unavailable BY CONSTRUCTION: the file is gone,
# so only the name is left. That asymmetry is why this list must name STRANGERS rather
# than exempt us (kimi-code, id=133 §2): hestia's own gates deliberately live at nameless
# ext4 paths (`~/.claude/hooks/pre_tool_use.py`), so a rule that lets an unrecognised name
# mean "not ours" would file our own deleted gate as somebody else's and leave `governed`
# true with enforcement gone. Unattributable therefore demotes; only a positive match here
# does not.
#
# This list WILL drift — a new stranger tool is miswired-by-default until someone adds it.
# That is the direction to drift in: a stale allowlist of strangers fails LOUD (their dead
# gate demotes us and someone investigates), where a stale exemption of ourselves fails
# SILENT. Every entry needs provenance, and the list is emitted in `scope` so a reader can
# see which exemption produced a clean verdict.
THIRD_PARTY_MARKERS = (
    "claude-flow",          # ruvnet/claude-flow, the tool itself
    "hook-handler.cjs",     # claude-flow's helper suite (claude-flow/.claude/helpers/)
    "auto-memory-hook.mjs",  # same suite
    "ruv-swarm",            # claude-flow's companion MCP tooling
)


def attribute(command: str, targets: list[str], is_hestia: bool) -> tuple[str, str]:
    """Who owns this hook, and on what evidence — decided once, where the evidence is.

    Findings are plain strings, and both `governed` and `gaps["miswired"]` used to
    re-derive ownership downstream by string-matching a tag. `is_hestia` is known right
    here; record it rather than reconstruct it (kimi-code, id=133 §1).
    """
    if is_hestia:
        return "hestia", "hestia marker in the hook command or target"
    hay = " ".join([command, *targets]).lower()
    for m in THIRD_PARTY_MARKERS:
        if m in hay:
            return "third-party", f"third-party marker '{m}'"
    return "unattributable", ("no marker either way, and a missing target cannot be "
                              "asked — treated as ours until proven otherwise")


def has_tag(findings: list[str], tag: str) -> bool:
    """Exact-tag test. `startswith("MISWIRED")` also matches `MISWIRED-3P`, which is the
    whole distinction this file now draws — so match the tag, not its prefix."""
    return any(f.split(":", 1)[0] == tag for f in findings)


def worktree_ref() -> str:
    """Which ref the checkout is sitting on. Reported even when it is not read from."""
    head = PLUGINS.parent / ".git"
    try:
        if head.is_file():  # worktree
            head = Path(head.read_text().split("gitdir:")[1].strip())
        ref = (head / "HEAD").read_text().strip()
        return ref.split("ref: refs/heads/")[-1] if ref.startswith("ref:") else ref[:12]
    except Exception:
        return "unknown"


def hook_timeout_finding() -> tuple[float, str] | None:
    """Does this check's own trigger still give it longer than it budgets for itself?

    THE CHECK APPLIED TO THE CHECK (cbp, 2026-07-26). Rule 5 binds the scan budget and the
    SessionStart timeout into one pair, and they live in two files: PROJECT_SCAN_BUDGET_S
    here, and a `timeout` install.sh writes into ~/.claude/settings.json. Nothing enforced
    the relation — the review had to state it in prose, and a rule kept alive by whoever
    read the review is the mitigation rule 3 refuses. install.sh now derives the timeout
    from the budget, which stops the two from drifting AT INSTALL. This is the other half:
    they can still be pulled apart afterwards, by a hand edit, by a second installer, or
    by exporting HESTIA_INVENTORY_SCAN_BUDGET past the timeout that is already written.

    A hook SIGKILLed one second before its walk would have given up emits NOTHING, and
    nothing reads as clean. This file exists to find gates whose failure mode is silence,
    so it is obliged to find its own.

    Reads the settings file rather than trusting install.sh's report of it: the question
    is what the harness will actually run. Matches on the installed binary NAME, not on
    argv[0], so the finding still surfaces when the repo copy is run by hand.
    """
    cfg = HOME / ".claude" / "settings.json"
    try:
        data = json.loads(cfg.read_text())
    except (OSError, ValueError):
        # No Claude settings on this box, or unreadable. Not a finding about the timeout —
        # config-readability is already reported per-agent by inspect().
        return None
    for grp in (data.get("hooks") or {}).get("SessionStart") or []:
        for hook in grp.get("hooks") or []:
            if INSTALLED_BIN_NAME not in hook.get("command", ""):
                continue
            timeout = hook.get("timeout")
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                continue
            if timeout >= SESSION_HOOK_TIMEOUT_S:
                continue
            return timeout, (
                    f"SessionStart hook timeout is {timeout}s in {cfg}, but this check "
                    f"budgets {PROJECT_SCAN_BUDGET_S}s for the directory walk alone — on "
                    f"a slow or contended machine it is killed mid-scan and emits "
                    f"nothing, which reads as clean (rule 5). The two numbers have "
                    f"drifted apart; re-run install.sh, which derives the timeout "
                    f"({SESSION_HOOK_TIMEOUT_S}s) from the budget.")
    return None


def periodic_trigger() -> tuple[str, str, list[str]]:
    """Is this check on a schedule here, or does it only answer when asked?

    THE SECOND HALF OF THE SAME CHECK-APPLIED-TO-THE-CHECK. `hook_timeout_finding()` asks
    whether the SessionStart trigger will survive; this asks whether the PERIODIC trigger
    exists at all — because install.sh can leave the binary behind without it, and after
    the day the installer's output scrolled away nothing says so. Measured by McNugget on
    Darwin (2026-07-28): `set -euo pipefail` + `systemctl --user daemon-reload` = exit 127
    at step 2, AFTER step 1 has installed the binary and pinned the workspace into it. The
    residue is a machine where `command -v hestia-agent-inventory` succeeds, the on-demand
    surface answers, and the check never runs on its own. A later reader sees an installed
    check. That is this file's own defect class, in its own installer.

    It is not Darwin-specific and the platform is not the finding: a Linux box whose
    install aborted at step 2, or where the units were removed afterwards, is in the same
    state and reads the same way.

    WHAT IS AND IS NOT CLAIMED. Only stats are done here — no `systemctl`/`launchctl`
    subprocess, because this runs inside a SessionStart hook with a budget. So the strong
    answer is the NEGATIVE one: no unit and no plist means no schedule, full stop. The
    positive answers are weaker by construction and are named to say how weak:
    `enabled` = systemd's own `timers.target.wants` symlink exists (which install.sh's
    `enable --now` creates), `installed` = the unit file is there but that symlink is not.
    Neither promises a fire — a --user timer with lingering off does not run without a
    session, which install.sh reports at install time and this cannot see. Returns
    (state, platform, paths_stat'd) so the reader can re-derive all three.

    AND THE TWO BACKENDS ARE NOT EQUIVALENT, so they do not share a state name. The
    systemd timer sets `Persistent=true`: a fire missed while the machine was off happens
    at next boot. launchd has no exact equivalent — a missed `StartInterval` fires ONCE at
    next load, not once per missed interval (McNugget, 2026-07-28, reading `deploy/` for
    the port). Written down rather than absorbed: on a laptop that sleeps, the two
    schedules diverge in coverage, not just in syntax, and `launchd-agent-installed` is
    the weaker claim of the two.

    AND THE PLIST'S EXISTENCE WAS NOT THE SCHEDULE (McNugget, 2026-07-28, writing the
    launchd half on a Mac). The glob alone answered `launchd-agent-installed` for ANY
    matching plist. But a LaunchAgent with neither `StartInterval` nor
    `StartCalendarInterval` is not periodic — `RunAtLoad` alone fires at login and never
    again, and `launchctl bootstrap` accepts it silently. That is the systemd
    `installed-not-enabled` distinction with no state to hold it, on the side where the
    positive answer was already the weak one: this file would have reported a schedule
    for the exact artifact it exists to catch, and the first such artifact would have
    been the one written next door in `install.sh`. So the keys are read, not assumed —
    `plistlib` handles XML and binary plists in-process, no `launchctl` subprocess, which
    keeps the hook budget intact. A plist that will not parse is its own answer: `launchctl`
    would refuse it too, so nothing is scheduled, but "refused" and "no schedule key" are
    different repairs and do not share a name.
    """
    system = platform.system()
    unit = HOME / ".config" / "systemd" / "user" / f"{INSTALLED_BIN_NAME}.timer"
    wants = (HOME / ".config" / "systemd" / "user" / "timers.target.wants"
             / f"{INSTALLED_BIN_NAME}.timer")
    agents = HOME / "Library" / "LaunchAgents"
    plists = sorted(agents.glob(f"*{INSTALLED_BIN_NAME}*.plist")) if agents.is_dir() else []
    looked = [str(unit), str(wants), f"{agents}/*{INSTALLED_BIN_NAME}*.plist"]
    if wants.exists():
        return "systemd-user-timer-enabled", system, looked
    if unit.exists():
        return "systemd-user-timer-installed-not-enabled", system, looked
    if plists:
        return f"launchd-agent-{_launchd_schedule(plists)}", system, looked
    return "absent", system, looked


# launchd's two periodic keys. `RunAtLoad`, `KeepAlive` and `WatchPaths` are triggers but
# not schedules: they answer "when something happens", which is the surface this check
# already has. Only these two make it a REGULAR check.
LAUNCHD_SCHEDULE_KEYS = ("StartInterval", "StartCalendarInterval")


def _launchd_schedule(plists: list[Path]) -> str:
    """`installed` | `installed-no-schedule` | `unparseable`, over all matching plists.

    Any one scheduled plist is enough — that is a real hourly fire regardless of what
    else is in the directory. The negative answers are only reached when NONE is, and
    they are ordered so the weaker knowledge wins: a directory holding one unreadable
    plist and one readable-but-unscheduled plist reports `unparseable`, because the
    unreadable one might have carried the schedule and saying `no-schedule` there would
    be a claim about a file this function could not read.

    A non-dict root counts as unreadable, not as unscheduled. `plistlib.loads(b"<plist/>")`
    returns None rather than raising (measured, CPython 3.13) — so "it parsed" is not "it is
    a job description", and the truthful thing to say about a file with no job dictionary in
    it is that no schedule could be read from it, not that it has none.
    """
    unreadable = False
    for p in plists:
        try:
            with p.open("rb") as fh:
                data = plistlib.load(fh)
        except Exception:
            data = None
        if not isinstance(data, dict):
            unreadable = True
            continue
        if any(k in data for k in LAUNCHD_SCHEDULE_KEYS):
            return "installed"
    return "unparseable" if unreadable else "installed-no-schedule"


def interpreter_finding() -> str | None:
    """Did the wrapper have to fall back off its pinned interpreter to run this at all?

    THE PIN IS SCOPE, SO ITS FAILURE IS A FINDING AND NOT AN EXIT CODE (cbp, 2026-07-28,
    reviewing the launchd branch from the Linux side). install.sh pins the interpreter the
    installing shell resolved, which on Darwin is a stable homebrew path and on Linux is
    routinely a venv, a conda prefix or a pyenv shim. When that path goes away the wrapper
    now falls back to PATH rather than exiting 127 — because a check that dies is
    indistinguishable from a check that found nothing, and this file exists to find gates
    whose failure mode is silence. It is obliged to find its own: the wrapper exports
    HESTIA_INTERPRETER_PIN_BROKEN and this turns it into a reported one.

    Measured before the floor existed: with the pinned venv deleted, `periodic_trigger()`
    still answered `systemd-user-timer-enabled` with `installed_bin` set — the strongest
    state here — while every hourly fire was exit 127. Installed, scheduled, and never once
    run, which is the same pair `installed-not-enabled` and `installed-no-schedule` were
    both introduced to break apart, one layer further down.

    The run itself is TRUSTWORTHY: same source file, stdlib only, and `sys.executable` is
    reported so a reader can see which python answered. What is NOT established is that the
    periodic trigger and the SessionStart hook still agree on an interpreter — which is the
    whole reason the pin was added.
    """
    pinned = os.environ.get("HESTIA_INTERPRETER_PIN_BROKEN")
    if not pinned:
        return None
    return (f"the installed wrapper's pinned interpreter {pinned} no longer exists, so "
            f"this run fell back to {sys.executable} off PATH. The findings stand — same "
            f"source, stdlib only — but the triggers are no longer pinned to one "
            f"interpreter, which is what the pin was for, and a PATH that differs between "
            f"a daemon and a shell will now silently split them again. Re-run install.sh "
            f"from the shell whose python3 every trigger should use.")


def _git(*args: str) -> str | None:
    """git in the hestia checkout, or None. Never raises, never blocks forever."""
    try:
        out = subprocess.run(("git", "-C", str(PLUGINS.parent)) + args,
                             capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode(errors="replace") if out.returncode == 0 else None


class Registry:
    """Inventory B — read from `origin/main`, not from whatever branch you are on.

    THE UNDER-COUNT IS NOT COSMETIC (thor, 2026-07-26). The previous cut stamped the ref
    and called that enough. It is not, because B is what A and C are differenced against,
    so an under-read propagates into the verdict. Measured on Thor, whose shared checkout
    sits on `cleanup/hardbound-runtime-state`, 103 commits behind main:

        worktree (stale)  ->  no plugins/claude-code/expects.json  ->  declared = {}
                          ->  gate_wired = None  ->  claude: GOVERNED, status UNKNOWN
        origin/main       ->  expects: gate=[PreToolUse]
                          ->  gate absent + two dead gates  ->  claude: MISWIRED

    Same machine, same instant, same script — opposite verdicts, and the stale one is the
    reassuring one. Again. A checkout's branch is a fact about whoever is working here,
    not a fact about what governance exists, and rule 4 says a check may not let the first
    quietly stand in for the second.

    `origin/main` is a fetched remote-tracking ref: read-only, no network, and it does not
    care what the working tree is doing — which also makes this safe to run while a
    sibling session holds the checkout dirty on a branch of its own.
    """

    def __init__(self) -> None:
        self.ref = "origin/main"
        self.source = "origin/main"
        # `-d`: trees only. Without it a blob sitting directly under `plugins/` — a
        # README, a .gitignore — counts as an available plugin. Latent on main today,
        # but B is what A and C are differenced against, so a phantom entry here becomes
        # a phantom harness in the verdict (cbp, 2026-07-26).
        listing = _git("ls-tree", "-d", "--name-only", "origin/main", "plugins/")
        sha = _git("rev-parse", "--short", "origin/main")
        if listing is None or sha is None:
            # No fetched main (shallow clone, no remote, git absent). Fall back to the
            # tree, and SAY so — a fallback that does not announce itself is the same
            # defect one layer down.
            self.source = "worktree"
            self.ref = worktree_ref()
            self.names = sorted(p.name for p in PLUGINS.iterdir() if p.is_dir()) \
                if PLUGINS.is_dir() else []
            self.degraded = ("plugins read from the working tree, not origin/main "
                             "(no fetched origin/main here) — B may be under-counted")
        else:
            self.ref = sha.strip()
            self.names = sorted({line.strip().split("/")[1]
                                 for line in listing.splitlines()
                                 if line.strip().startswith("plugins/")
                                 and len(line.strip().split("/")) > 1})
            self.degraded = None

    def has(self, plugin_dir: str) -> bool:
        return plugin_dir in self.names

    def harnesses(self) -> list[str]:
        return sorted(n for n in self.names if n not in NOT_A_HARNESS_PLUGIN)

    def expects(self, plugin_dir: str) -> dict:
        """Which hook events a plugin must occupy, and in which role (thor's §3 shape).

        `wired` used to ask "is anything hestia-shaped wired?", which one hook of any kind
        answers yes. Witnessing and gating are different acts with different failure
        modes: post-hoc observation CANNOT fail closed, and the whole point of the gate
        profile is that the pre-hook can. Absent an expects.json the roles are unknown and
        the agent is reported as such — not as governed.

        Ask the registry before asking git. This is called for all 45 atlas ids and 36 of
        them name plugin dirs that are not in the registry at all — 36 subprocess spawns
        to learn what `self.names` already knew (~4s -> ~0.7s on CBP).
        """
        if not self.has(plugin_dir):
            return {}
        if self.source == "origin/main":
            raw = _git("show", f"origin/main:plugins/{plugin_dir}/expects.json")
        else:
            try:
                raw = (PLUGINS / plugin_dir / "expects.json").read_text()
            except OSError:
                raw = None
        if raw is None:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            return {}
        return {k: list(v) for k, v in data.items() if isinstance(v, list)}


REGISTRY: Registry | None = None  # built in main(), once WORKSPACE is known


def registry() -> Registry:
    """The registry, or a loud failure — never a plausible substitute for it.

    THIS FILE'S OWN DEFECT CLASS, IN ITS OWN NEW CODE (found by main's `test_inventory.py`
    when the two changes met, 2026-07-26). An unbuilt registry used to degrade to
    `has() -> False` and `expects() -> {}`, which are not neutral defaults: they read as
    "no plugin exists for this agent", so every agent reports UNGOVERNABLE — *someone must
    build the adapter* — for a fleet whose adapters are all present. A wrong remedy stated
    confidently, from a prerequisite nobody noticed was missing. Exactly the shape rule 4
    exists to refuse, and the same shape as the dead gate that reads as covered.

    Unreachable from the CLI, because `main()` builds it before anything asks. That is the
    argument for raising rather than defaulting, not against it: the only callers who can
    reach the None are in-process ones — tests, and whatever imports this next — and they
    are precisely the callers who cannot tell a wrong answer from a right one.
    """
    if REGISTRY is None:
        raise RuntimeError(
            "plugin registry not built: call main(), or stub `inventory.REGISTRY`. "
            "Refusing to answer, because answering 'no plugins' would report every "
            "agent UNGOVERNABLE and look like a finding.")
    return REGISTRY


def expects(plugin_dir: str) -> dict:
    return registry().expects(plugin_dir)


def inspect(atlas_id: str, roots: list[str]) -> dict:
    exes, dirnames, plugin_dir = names_for(atlas_id)
    exe = real_executable(exes, roots)
    homes = [HOME / d for d in dirnames if (HOME / d).is_dir()]
    plugin_available = registry().has(plugin_dir)
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
                # EMIT THE TARGET, not only a finding about it (thor, hestia#52 review).
                # This loop already stats every hook target on the machine; it was the only
                # place that knew the real set, and it kept the knowledge to itself. The
                # gate-integrity check then derived coverage from four hardcoded $HOME
                # paths, so on a machine whose gates live elsewhere it hashed NOTHING and
                # reported VERIFIED — a clean verdict over an empty denominator, which is
                # the inversion these surfaces exist to prevent.
                rec.setdefault("hook_targets", []).append({
                    "path": target,
                    "event": hook.get("event"),
                    "exists": exists,
                    "is_gate": hook["event"] in declared.get("gate", []),
                    "owned_by_hestia": is_hestia,
                    "config": str(cfg),
                    "scope": scope,
                })
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
                    # non-zero that is not an explicit `exit 2` is an ALLOW. So the
                    # FINDING stays owner-agnostic — but the VERDICT cannot be, because
                    # `governed` is a claim about hestia's wiring. A stranger's dead gate
                    # in a repo we do not own pinned this machine at MISWIRED with
                    # hestia's own enforcement intact and no reachable remedy, which is
                    # two grains rendered as one verdict. The owner splits the tag; the
                    # tag decides the verdict; the evidence rides along so the split is
                    # auditable rather than trusted.
                    role = "gate" if hook["event"] in declared.get("gate", []) else "hook"
                    owner, why = attribute(hook["command"], targets, is_hestia)
                    if role != "gate":
                        tag = "DEAD_HOOK"
                    else:
                        tag = "MISWIRED-3P" if owner == "third-party" else "MISWIRED"
                    state = "enabled" if hook["enabled"] else "disabled"
                    rec["findings"].append(
                        f"{tag}: {hook['event']} {state}, target does not exist "
                        f"{where} -> {target} (owner: {owner} — {why})")
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

    # ONE predicate, two consumers. The demotion had two sites — this line and
    # `gaps["miswired"]` — and fixing only one flips the field while the gap report keeps
    # pinning the machine: the same defect re-created inside its own fix (kimi-code,
    # id=133 §1). Compute it once, on the record, and let both read it.
    rec["miswired"] = has_tag(rec["findings"], "MISWIRED")
    rec["miswired_3p"] = has_tag(rec["findings"], "MISWIRED-3P")
    rec["governed"] = bool(rec["installed"] and plugin_available and rec["wired"]
                           and rec["gate_wired"] is not False
                           and not rec["miswired"])
    return rec


def classify(recs: list[dict]) -> dict:
    """The gaps, each with its own remedy. This is the actionable part."""
    gaps: dict[str, list[str]] = {
        "miswired": [], "miswired_3p": [], "partial": [], "ungoverned": [],
        "ungovernable": [], "dormant_plugin": [], "unknown": []}
    for r in recs:
        if r["unknown"]:
            gaps["unknown"].append(r["agent"])
        # Its own bucket, and NOT in the elif chain: a stranger's dead gate is a real
        # finding with a remedy in someone else's repo, so it must not consume the slot
        # that would otherwise report an actual hestia gap on the same agent.
        if r["installed"] and r["miswired_3p"]:
            gaps["miswired_3p"].append(r["agent"])
        if r["installed"] and r["miswired"]:
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
        # Rule 5 belongs on the SURFACE, not only in the JSON. A truncated scan can still
        # produce a confident-looking status — MISWIRED, PARTIAL, even OK — because the
        # part it never walked contributes no findings, and `unknown[]` is invisible from
        # here. Reported at 0 budget: `PARTIAL ... partial=['claude']`, with the three dead
        # gates it had not reached yet nowhere in the line. The one-liner is what a session
        # actually reads, so the one-liner has to say the look was short.
        scan = (report.get("scope") or {})
        if scan.get("scan_truncated"):
            line += (f" | SCAN TRUNCATED at {scan.get('project_scan_budget_s')}s after "
                     f"{scan.get('project_scan_dirs')} dirs, depth level "
                     f"{scan.get('project_scan_truncated_at_level')} partial "
                     f"({scan.get('project_scan_level_progress')}) — the DEEPEST project "
                     "scopes are the ones missing")
        # Same argument as the truncation clause above, one dimension over: an
        # enumeration that never listed an agent produces no finding about it, and a
        # missing finding is indistinguishable from a clean one on the surface a session
        # actually reads.
        if scan.get("agent_enumeration_complete") is False:
            line += (f" | ENUMERATION PARTIAL — agent ids from {scan['agent_enumeration']}"
                     f" (no agent-atlas at {scan.get('atlas')}); an installed agent named "
                     "by neither was never looked for")
        # The trigger that was never wired is invisible from every trigger that was. A
        # machine holding the binary but no schedule answers on demand and at session
        # start and is otherwise silent — which reads as a regular check that found
        # nothing (McNugget, 2026-07-28: install.sh dies at systemctl on Darwin AFTER
        # installing the binary).
        # Gated on the binary being there: a machine that never ran install.sh has no
        # schedule for the honest reason, and warning about it would be noise on every
        # bare `python3 inventory.py`. The finding is the PAIR — installed, unscheduled.
        # `launchd-agent-installed-no-schedule` reads the same to a session and is worse
        # to a reader: a plist IS present, so `ls ~/Library/LaunchAgents` and `launchctl
        # bootstrap` both look like a wired schedule. Same sentence, different second
        # clause — what to go fix is not the same thing.
        if scan.get("installed_bin") and scan.get("periodic_trigger") in (
                "absent", "launchd-agent-installed-no-schedule", "launchd-agent-unparseable"):
            why = {
                "absent": ("no schedule", "it runs only when something calls it, so "
                           "silence here is not evidence"),
                "launchd-agent-installed-no-schedule":
                    ("a LaunchAgent plist that schedules nothing",
                     "it has neither StartInterval nor StartCalendarInterval, so launchd "
                     "loads it and never fires it"),
                "launchd-agent-unparseable":
                    ("a LaunchAgent plist that does not parse",
                     "launchctl will refuse it too; re-run install.sh"),
            }[scan["periodic_trigger"]]
            line += (f" | NO PERIODIC TRIGGER — this binary is installed with {why[0]} "
                     f"on {scan.get('periodic_platform')}; {why[1]}")
        if scan.get("interpreter_pin_broken"):
            line += (f" | INTERPRETER PIN BROKEN — the wrapper's pinned "
                     f"{scan['interpreter_pin_broken']} is gone; this ran on "
                     f"{scan.get('interpreter')} off PATH, so the triggers are no longer "
                     "pinned to one interpreter. Re-run install.sh")
        if scan.get("hook_timeout_installed_s") is not None:
            line += (f" | HOOK TIMEOUT {scan['hook_timeout_installed_s']}s < "
                     f"{scan.get('project_scan_budget_s')}s SCAN BUDGET — this check can "
                     f"be killed mid-scan and print nothing; re-run install.sh")
        if report.get("reason"):
            line += f" | {report['reason']}"
        print(line)
    else:
        print(json.dumps(report, indent=1))
    return 0


def main() -> int:
    global WORKSPACE, WORKSPACE_SOURCE, ATLAS, PLUGINS, REGISTRY
    argv = sys.argv[1:]
    # Answered before anything else is resolved: install.sh calls this to derive the
    # SessionStart timeout instead of keeping a second copy of the number, so it must
    # work with no workspace, no registry, and no walk.
    if "--print-hook-timeout" in argv:
        print(SESSION_HOOK_TIMEOUT_S)
        return 0
    brief = "--brief" in argv

    WORKSPACE, WORKSPACE_SOURCE = resolve_workspace(argv)
    ATLAS = WORKSPACE / "agent-atlas" / "talk-to"
    PLUGINS = WORKSPACE / "hestia" / "plugins"
    REGISTRY = Registry()

    roots = search_roots()
    # THE MISSING REGISTRY COSTS THE ENUMERATION, NOT THE WALK (McNugget, 2026-07-28).
    # This was a `return emit(UNKNOWN)` above `search_roots()`, so an atlas-less machine
    # got no A inventory, no dead-gate stats, no FRAGILE and no hook-timeout finding —
    # none of which need atlas — and a payload of `{status, machine, reason}` with no
    # `scope` key, in the one case where scope IS the whole story. See fallback_agent_ids.
    if ATLAS.is_dir():
        known = sorted(p.name for p in ATLAS.iterdir() if p.is_dir())
        enumeration, enumeration_gap = "agent-atlas", None
    else:
        known = fallback_agent_ids(REGISTRY)
        enumeration = "built-in ALIASES + plugin registry"
        enumeration_gap = (
            f"agent-atlas registry not readable at {ATLAS}, so the AGENT ENUMERATION is "
            f"partial: this run looked for {len(known)} ids known to this file and to "
            "hestia's plugin registry, and for nothing else. Every finding below is a "
            "real filesystem fact and stands; what cannot be ruled out is an installed, "
            "ungoverned agent that neither list names — so 'nothing ungoverned' is still "
            f"undistinguishable from 'could not look' (workspace from {WORKSPACE_SOURCE}; "
            "pass --workspace PATH, re-run install.sh, or clone agent-atlas)")
    recs = [inspect(a, roots) for a in known]
    periodic_state, periodic_platform, periodic_paths = periodic_trigger()
    installed_bin = HOME / ".local" / "bin" / INSTALLED_BIN_NAME
    available = REGISTRY.harnesses()
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
        "workspace_source": WORKSPACE_SOURCE,      # argv | env | default
        # Where the list of agent ids came from, and whether it was the whole list. A
        # fleet dashboard differencing machines needs this to tell "McNugget has no codex"
        # from "McNugget never looked for one".
        "agent_enumeration": enumeration,
        "agent_enumeration_complete": enumeration_gap is None,
        "atlas": str(ATLAS),
        "exe_search_roots": roots,
        "config_scopes_read": sorted({c["path"] for r in recs
                                      for c in r["configs_read"]}),
        "project_scan_depth": PROJECT_SCAN_DEPTH,
        # Rule 5: the budget is part of the scope, so the walk's own cost is evidence and
        # is reported next to what it found — including how much of it never happened.
        "project_scan_dirs": SCAN_STATS.get("dirs_scanned", 0),
        "project_scan_seconds": SCAN_STATS.get("seconds"),
        "project_scan_budget_s": PROJECT_SCAN_BUDGET_S,
        "session_hook_timeout_s": SESSION_HOOK_TIMEOUT_S,
        # This check's own third trigger, reported next to the other two. See
        # periodic_trigger() for exactly what each state does and does not claim.
        "periodic_trigger": periodic_state,
        "periodic_platform": periodic_platform,
        "periodic_paths_checked": periodic_paths,
        "installed_bin": str(installed_bin) if installed_bin.exists() else None,
        # Which python actually answered. Reported unconditionally, not only when the pin
        # breaks: `installed_bin` names a wrapper whose whole job is to make the three
        # triggers agree on this value, so a fleet dashboard differencing two machines —
        # or one machine's hook against its own timer — needs it present to compare.
        "interpreter": sys.executable,
        "scan_truncated": SCAN_STATS.get("truncated", False),
        # Level-order, so "where it stopped" is one integer and the loss is predictable:
        # levels below `truncated_at_level` were never enumerated, and those are the
        # deepest project roots — the ones DEPTH+1 exists to reach.
        "project_scan_levels_complete": SCAN_STATS.get("levels_complete"),
        "project_scan_truncated_at_level": SCAN_STATS.get("truncated_at_level"),
        "project_scan_level_progress": (
            f"{SCAN_STATS.get('level_done')}/{SCAN_STATS.get('level_of')}"
            if SCAN_STATS.get("truncated") else None),
        "plugins_source": REGISTRY.source,         # origin/main | worktree
        "plugins_ref": REGISTRY.ref,
        "worktree_ref": worktree_ref(),
        "toml_supported": tomllib is not None,
        # The one allowlist in this file, emitted because it is the only thing that can
        # turn a MISWIRED into a non-fatal MISWIRED-3P. A reader who wonders why a
        # machine is clean can see exactly which names bought the exemption.
        "third_party_markers": list(THIRD_PARTY_MARKERS),
    }
    unknowns = sorted({u for r in recs for u in r["unknown"]})
    if enumeration_gap:
        unknowns.append(enumeration_gap)
    if WORKSPACE_SOURCE == "default":
        unknowns.append(
            f"workspace neither passed as --workspace nor set in HESTIA_WORKSPACE — "
            f"fell back to the compiled-in default {WORKSPACE}, which is only correct "
            "on the machine it was written on")
    if REGISTRY.degraded:
        unknowns.append(REGISTRY.degraded)
    drifted = hook_timeout_finding()
    if drifted:
        installed_timeout, why = drifted
        unknowns.append(why)
        # ...and onto the one-line surface too, for the reason hop 2 learned the hard way:
        # a finding only in `unknown[]` is invisible to `--brief`, and MISWIRED/PARTIAL
        # both outrank UNKNOWN, so status can never carry it either. The reader who most
        # needs this one IS the brief reader — it is the SessionStart hook that gets
        # killed. A check has as many surfaces as it has readers, and the smallest surface
        # is the one that gets believed.
        scope["hook_timeout_installed_s"] = installed_timeout
    pin_broken = interpreter_finding()
    if pin_broken:
        unknowns.append(pin_broken)
        # Onto --brief for the same reason the hook-timeout finding is: the reader who
        # most needs this is the one whose trigger just ran on the wrong python, and the
        # smallest surface is the one that gets believed.
        scope["interpreter_pin_broken"] = os.environ["HESTIA_INTERPRETER_PIN_BROKEN"]
    if SCAN_STATS.get("truncated"):
        # Rule 5 made explicit. A walk that ran out of budget has NOT established the
        # project scope, and the part it never reached is exactly where the report would
        # otherwise be quietly clean.
        done = SCAN_STATS.get("levels_complete", 0)
        whole = f"depth levels 0..{done - 1} complete" if done else "no depth level completed"
        unknowns.append(
            f"project scan hit its {PROJECT_SCAN_BUDGET_S}s budget after "
            f"{SCAN_STATS.get('dirs_scanned', 0)} directories: {whole}, level "
            f"{SCAN_STATS.get('truncated_at_level')} stopped at "
            f"{SCAN_STATS.get('level_done')}/{SCAN_STATS.get('level_of')} of its parents, "
            "deeper levels never enumerated — project scope is PARTIAL and any gate under "
            "the unwalked part is neither found nor counted. The walk is level-order, so "
            "what is missing is always the DEEPEST scopes, never a random sample: "
            "truncation costs exactly the level this scan was widened to reach. Raise "
            "HESTIA_INVENTORY_SCAN_BUDGET (and the SessionStart timeout with it — "
            f"install.sh derives it), or read the hourly timer's full-depth answer.")

    # An unestablished scope degrades to UNKNOWN, never to OK (rule 4). MISWIRED still
    # outranks it: a known dead gate is worse news than an unknown.
    #
    # `miswired_3p` deliberately does NOT appear in this ladder, on the FRAGILE precedent:
    # both are real, both are loud in `gaps`/`fragile` and in the brief line, and neither
    # is a gap in hestia's coverage of this machine. Making it a status rung would restore
    # exactly the property the split removes — a headline no hestia work can clear.
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
