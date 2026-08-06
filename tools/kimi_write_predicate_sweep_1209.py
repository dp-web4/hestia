#!/usr/bin/env python3
"""Second-seat sweep of the gate-self predicate, Write vs Bash (notice 1209, ask #2).

claude-code (cbp-re-1207 §5) measured ON ITS SEAT:
  - Bash, redirect probe, absolute installed hook path in content  -> REFUSED
  - Bash, bare filename / repo-relative path in content            -> ALLOWED
  - Write, repo-relative path in content (cleared by the Bash row) -> REFUSED
and concluded "the two tools do not share a predicate".

This tool re-runs the sweep OFFLINE against the hook's own functions
(_touches_self / _touches_registration / _is_read_only), imported from the repo
copy of the hook — no daemon, no chain writes, no escalations minted, on any
seat. It extends the matrix to Write x {read-shaped Bash} x {redirect Bash} so
the divergence claude hit is localised to a specific layer: the MARKER matcher
(shared) or the INTENT classifier above it (per-tool).

Hypothesis under test: the marker matcher is shared; Write is in _WRITE_TOOLS so
_is_read_only() is False unconditionally, while read-shaped Bash is classified
read-only and a marker match there is allowed (witnessed as a gate-self READ).
If the matrix shows that, "Bash != Write predicate" is really "one predicate
under two intent classifiers, and Write has no read shape".

Reads only. Mints nothing. Network: none (module-level import only; main() is
never called, so no code path here talks to the daemon).
"""
from __future__ import annotations

import hashlib
import importlib.util

HOOK = "/mnt/c/exe/projects/ai-agents/hestia/plugins/claude-code/hooks/pre_tool_use.py"
# CAVEAT: _SELF/_SELF_DIR are os.path.realpath(__file__) of the LOADED copy. Loading the
# repo copy makes those two markers repo-shaped, so rows keyed on the *installed* dir
# (e.g. "/home/dp/.claude/hooks/hestia" with no filename) read "no marker" here but WOULD
# match on the installed hook. All filename-keyed rows are location-independent. A run
# against the installed file (same sha256 this wake) flips exactly the installed-dir row.

spec = importlib.util.spec_from_file_location("gate_hook", HOOK)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

blob = open(HOOK, "rb").read()
print(f"predicate source: {HOOK}")
print(f"  sha256 {hashlib.sha256(blob).hexdigest()[:16]}…  ({len(blob)} bytes)")
print(f"  _WRITE_TOOLS     = {sorted(m._WRITE_TOOLS)}")
print(f"  _READ_ONLY_TOOLS = {sorted(m._READ_ONLY_TOOLS)}")
print()

SPELLINGS = {
    "absolute installed path": "/home/dp/.claude/hooks/hestia/pre_tool_use.py",
    "installed hooks dir     ": "/home/dp/.claude/hooks/hestia",
    "repo-relative file      ": "plugins/claude-code/hooks/pre_tool_use.py",
    "repo-relative dir       ": "plugins/claude-code/hooks",
    "bare filename           ": "pre_tool_use.py",
    "control (no marker)     ": "an ordinary string with no gate path in it",
}


def verdict(tool: str, ti: dict) -> str:
    marker = m._touches_self(tool, ti) or m._touches_registration(tool, ti)
    if not marker:
        return "ALLOW  (no marker)"
    if m._is_read_only(tool, ti):
        return f"ALLOW  (marker matched, classified READ -> witnessed self-read)  [{marker}]"
    return f"REFUSE (+ auto-open on a live seat)                              [{marker}]"


print(f"{'spelling':27s}  {'Write (content)':52s}  "
      f"{'Bash echo-shape':52s}  Bash redirect-shape")
for name, s in SPELLINGS.items():
    w = verdict("Write", {"file_path": "/tmp/kimi_probe_target.txt",
                          "content": f"a sentence mentioning {s} inside it"})
    b_read = verdict("Bash", {"command": f"echo '{s}'"})
    b_redir = verdict("Bash", {"command": f"printf '%s' '{s}' > /tmp/kimi_probe_target.txt"})
    print(f"{name}  {w:52s}  {b_read:52s}  {b_redir}")

print()
print("Also: Write whose TARGET is the gate file (content clean):")
print("  " + verdict("Write", {"file_path": SPELLINGS['absolute installed path'],
                               "content": "clean content, no markers"}))
print("And Bash sed-read of the installed hook (claude's daea09fc2106dd7b act):")
print("  " + verdict("Bash", {"command":
      "sed -n '905,945p' /home/dp/.claude/hooks/hestia/pre_tool_use.py"}))
