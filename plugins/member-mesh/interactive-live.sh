#!/usr/bin/env bash
# interactive-live.sh — is a member's INTERACTIVE session alive right now?
#
# The ping-reply routing break (dp 2026-07-30, verified and documented in
# shared-context/forum/kimi-dp-is-right-about-ping-reply-routing-verified-and-a-fix-shape-2026-07-30.md):
# an interactive session sends a notice; the reply lands in the member's single
# consume-once mailbox; the watcher drains it and fires a HEADLESS instance; the
# author session never learns the reply arrived. Two consumers, one queue, and
# the wrong one usually wins.
#
# This script is the yield signal that closes the common case. A live session
# touches a heartbeat file on every tool call (one line in its gate). If the
# heartbeat is fresh, the watcher must YIELD — peek, not drain — so the reply
# waits for the live session instead of being eaten by a headless one.
#
# Exit 0 = interactive session is live (watcher should yield).
# Exit 1 = no live session (watcher drains and fires as before).
#
# Env:
#   HEARTBEAT_FILE  default $HOME/.${WATCH_MEMBER}/hestia-instance/interactive-heartbeat
#   HOLD_SECS       freshness window in seconds (default 300). Should be a few
#                   times the member's active-call cadence; a session that stops
#                   calling tools goes stale and the watcher resumes on its own.
#
# Failure shape: a missing/unreadable heartbeat is NOT live (exit 1) — the
# default is the wake path, and a member whose gate lacks the toucher simply
# keeps today's behavior. Never an error either way: this is a yield hint for
# routing, not a gate on acts.
set -u

HB="${HEARTBEAT_FILE:-$HOME/.${WATCH_MEMBER:-kimi-code}/hestia-instance/interactive-heartbeat}"
HOLD="${HOLD_SECS:-300}"

[ -f "$HB" ] || exit 1
NOW=$(date +%s)
MTIME=$(stat -c %Y "$HB" 2>/dev/null) || exit 1
[ $((NOW - MTIME)) -lt "$HOLD" ] && exit 0
exit 1
