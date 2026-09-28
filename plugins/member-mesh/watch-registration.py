#!/usr/bin/env python3
"""How a harness config registers prompt-disposition-watch.sh: prints wired | MISWIRED | UNWIRED.

Used by install.sh (run from the repo, never installed). A filename in the config is not a
registration (GPT, #1148): the command must sit under UserPromptSubmit and pin THIS member
with HESTIA_MESH_PLUGIN=<member>, or the hook either never fires or speaks as nobody.

Parsed per format, not grepped:
  JSON (claude-code settings.json): hooks.UserPromptSubmit[].hooks[].command
  TOML, as a line scan (tomllib is 3.11+ and this must run on any python3):
    codex  -- the event is the nearest `[[hooks.<Event>]]` header;
    kimi   -- a flat `[[hooks]]` table carrying `event = "<Event>"`.
Whole-line comments are dropped. Any error prints UNWIRED: this is a report, never a gate.

Usage: watch-registration.py <config path> <member>
"""
import json
import re
import sys

NAME = "prompt-disposition-watch.sh"


def pairs_json(text):
    try:
        hooks = json.loads(text).get("hooks") or {}
    except (ValueError, AttributeError):
        return []
    out = []
    for event, groups in hooks.items() if isinstance(hooks, dict) else []:
        for g in groups if isinstance(groups, list) else []:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                c = h.get("command") if isinstance(h, dict) else None
                if isinstance(c, str) and NAME in c:
                    out.append((event, c))
    return out


def pairs_toml(text):
    out, event, cmd = [], None, None

    def flush():
        if cmd and NAME in cmd:
            out.append((event, cmd))

    for line in text.splitlines():
        st = line.strip()
        if not st or st.startswith("#"):
            continue
        if st.startswith("["):
            m = re.match(r"\[\[hooks(?:\.([A-Za-z]+))?(\.hooks)?\]\]", st)
            flush()
            cmd = None
            if m and m.group(2):          # [[hooks.<Event>.hooks]]: same event, new command
                continue
            event = m.group(1) if m else None
            continue
        m = re.match(r"""event\s*=\s*(['"])(.*)\1""", st)
        if m:
            event = m.group(2)
            continue
        m = re.match(r"""command\s*=\s*(['"])(.*)\1""", st)
        if m:
            flush()
            cmd = m.group(2)
    flush()
    return out


def state(path, member):
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return "UNWIRED"
    pairs = pairs_json(text) if path.endswith(".json") else pairs_toml(text)
    if not pairs:
        return "UNWIRED"
    pin = re.compile(r"(^|\s)HESTIA_MESH_PLUGIN=" + re.escape(member) + r"(\s|$)")
    if any(e == "UserPromptSubmit" and pin.search(c) for e, c in pairs):
        return "wired"
    return "MISWIRED"


if __name__ == "__main__":
    try:
        print(state(sys.argv[1], sys.argv[2]))
    except Exception:
        print("UNWIRED")
