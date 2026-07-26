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
   first hand-run. Resolve to a real file on PATH; never judge by name.
2. A config directory is not an installed agent. `~/.foo` outliving an uninstall is
   residue, reported as such. Installation is evidenced by an executable.
3. A configured hook is not a working hook, and an empty result is not a clean result.
   Verify the hook TARGET EXISTS; if the registry is unreadable, say UNKNOWN rather
   than render "nothing ungoverned" out of "could not look".

Exit 0 always. This is an observation, and an observation layer that can break a session
has become a gate. Findings go to stdout as JSON and (unless --no-witness) to the chain.
"""
from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from urllib import request as urlrequest

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


def real_executable(names: list[str]) -> str | None:
    """A real executable on PATH — NOT a shell builtin (see docstring #1)."""
    for name in names:
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if not d:
                continue
            p = Path(d) / name
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    return None


def hook_paths(text: str) -> list[str]:
    """Absolute paths a config's hook commands point at, so we can test they resolve."""
    out = []
    for tok in text.replace('"', " ").replace("'", " ").replace(",", " ").split():
        if tok.startswith("/") and "/" in tok[1:]:
            out.append(tok.rstrip("};"))
    return out


def inspect(atlas_id: str) -> dict:
    exes, dirnames, plugin_dir = names_for(atlas_id)
    exe = real_executable(exes)
    homes = [HOME / d for d in dirnames if (HOME / d).is_dir()]
    plugin_available = (PLUGINS / plugin_dir).is_dir()

    rec: dict = {
        "agent": atlas_id,
        "plugin": plugin_dir if plugin_available else None,
        "plugin_available": plugin_available,
        # #2: installation is evidenced by an executable, not by a config dir.
        "installed": exe is not None,
        "executable": exe,
        "config_dirs": [str(h) for h in homes],
        "wired": False,
        "findings": [],
    }
    if exe is None and homes:
        rec["residue"] = True
        rec["findings"].append(
            "RESIDUE: config dir present with no executable on PATH — a leftover, "
            "not an installed agent")

    for home in homes:
        for fname in CONFIG_FILES:
            cfg = home / fname
            if not cfg.is_file():
                continue
            try:
                text = cfg.read_text(errors="replace")
            except OSError as e:
                rec["findings"].append(f"config unreadable ({cfg}): {e}")
                continue
            if "hestia" not in text.lower():
                continue
            rec["wired"] = True
            rec.setdefault("configs", []).append(str(cfg))
            # #3: a configured hook is not a working hook.
            for target in hook_paths(text):
                if "hestia" not in target.lower():
                    continue
                if not Path(target).exists():
                    rec["wired"] = False
                    rec["findings"].append(
                        f"MISWIRED: hook target does not exist -> {target}")
                elif target.startswith("/tmp/"):
                    rec["findings"].append(
                        f"FRAGILE: hook target under /tmp, cleared on reboot -> {target}")
                elif "/mnt/c/" in target:
                    rec["findings"].append(
                        "FRAGILE: hook target on the 9p mount — cold-load can exceed the "
                        f"hook timeout, and these hooks fail OPEN -> {target}")

    rec["governed"] = bool(rec["installed"] and plugin_available and rec["wired"])
    return rec


def classify(recs: list[dict]) -> dict:
    """The gaps, each with its own remedy. This is the actionable part."""
    gaps: dict[str, list[str]] = {
        "miswired": [], "ungoverned": [], "ungovernable": [], "dormant_plugin": []}
    for r in recs:
        if r["installed"] and any(f.startswith("MISWIRED") for f in r["findings"]):
            gaps["miswired"].append(r["agent"])
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


def main() -> int:
    argv = sys.argv[1:]

    if not ATLAS.is_dir():
        print(json.dumps({"status": "UNKNOWN", "reason":
                          f"agent-atlas registry not readable at {ATLAS} — cannot "
                          "distinguish 'nothing ungoverned' from 'could not look'"},
                         indent=1))
        return 0

    known = sorted(p.name for p in ATLAS.iterdir() if p.is_dir())
    recs = [inspect(a) for a in known]
    available = sorted(p.name for p in PLUGINS.iterdir()
                       if p.is_dir() and p.name not in NOT_A_HARNESS_PLUGIN) \
        if PLUGINS.is_dir() else []
    installed = [r for r in recs if r["installed"]]
    governed = [r for r in installed if r["governed"]]
    gaps = classify(recs)
    fragile = sorted({r["agent"] for r in installed
                      if any(f.startswith("FRAGILE") for f in r["findings"])})

    status = "OK"
    if gaps["miswired"]:
        status = "MISWIRED"
    elif gaps["ungoverned"] or gaps["ungovernable"]:
        status = "UNGOVERNED_PRESENT"

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
        "detail": [r for r in recs
                   if r["installed"] or r["plugin_available"] or r.get("residue")],
    }
    if "--no-witness" not in argv:
        report["witness"] = witness(report)

    if "--brief" in argv:  # for the SessionStart surface: one line, no wall of JSON
        line = (f"[agent-inventory] {status} on {report['machine']}: "
                f"{len(report['installed'])} installed, {len(available)} plugins, "
                f"{len(report['governed'])} governed")
        extra = [f"{k}={v}" for k, v in gaps.items() if v and k != "dormant_plugin"]
        print(line + (" | " + " ".join(extra) if extra else ""))
    else:
        print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
