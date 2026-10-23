#!/usr/bin/env bash
# install-watchers.sh, --check only (writes nothing, starts nothing): which members it finds on a host (#1373).
# Fixtures use non-harness file names on purpose: a file named like a real harness config is governance closure
# wherever it sits, and a test must not write closure.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/cfg"
# claude-code: JSON, pinned to its own id -> present
printf '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"HESTIA_MESH_PLUGIN=claude-code /x/session-mesh-inbox.sh"}]}]}}' > "$T/cfg/claude.json"
# kimi-code: TOML, pinned -> present
printf '[[hooks]]\nevent = "SessionStart"\ncommand = "HESTIA_MESH_PLUGIN=kimi-code /x/session-mesh-inbox.sh"\n' > "$T/cfg/kimi.toml"
# codex: only a COMMENTED line -> absent
printf '# command = "HESTIA_MESH_PLUGIN=codex /x/session-mesh-inbox.sh"\n' > "$T/cfg/codex.toml"
# gemini-ish: pinned to ANOTHER member's id -> absent (a pin must name this member)
printf 'command = "HESTIA_MESH_PLUGIN=claude-code /x/session-mesh-inbox.sh"\n' > "$T/cfg/other.toml"
# prefix trap: kimi-code-x must not count as kimi-code
printf 'command = "HESTIA_MESH_PLUGIN=kimi-code-x /x/session-mesh-inbox.sh"\n' > "$T/cfg/prefix.toml"

TABLE="claude-code|cfg/claude.json|fire-claude.sh
kimi-code|cfg/kimi.toml|fire-kimi.sh
codex|cfg/codex.toml|fire-codex.sh
other|cfg/other.toml|fire-claude.sh
kimi-code|cfg/prefix.toml|fire-kimi.sh
missing|cfg/none.toml|fire-claude.sh"
out="$(HOME="$T" HESTIA_HOME="$T/.hestia" HESTIA_MESH_STATE="$T/state" HESTIA_MESH_WATCH_TABLE="$TABLE" \
       bash "$HERE/install-watchers.sh" --check)"
echo "$out"
last="$(echo "$out" | tail -1)"
fail=0
check() { case "$last" in *"$1"*) echo "PASS $1" ;; *) echo "FAIL $1 (last line: $last)"; fail=1 ;; esac; }
# with no systemd user manager the present members read skipped(...); with one, inactive(...). Either is "found".
case "$last" in *"claude-code=absent"*) echo "FAIL claude-code pinned JSON read as absent"; fail=1 ;; *) echo "PASS claude-code found" ;; esac
case "$(echo "$out" | sed -n 2p)" in *"kimi-code: absent"*) echo "FAIL kimi-code pinned TOML read as absent"; fail=1 ;; *) echo "PASS kimi-code found" ;; esac
check "codex=absent"
check "other=absent"
case "$(echo "$out" | sed -n 5p)" in *"kimi-code: absent"*) echo "PASS prefix kimi-code-x not counted" ;; *) echo "FAIL prefix kimi-code-x counted as kimi-code"; fail=1 ;; esac
check "missing=absent"
case "$last" in mesh:*) echo "PASS summary is the last line" ;; *) echo "FAIL summary not last"; fail=1 ;; esac
[ -d "$T/.config" ] && { echo "FAIL --check wrote a unit dir"; fail=1; } || echo "PASS --check wrote nothing"
exit $fail
