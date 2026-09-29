#!/usr/bin/env bash
# Bring a LEGACY macOS hestia seat to the canonical service shape, in place, without
# downloading anything. The operator's act: it moves the vault passphrase and rewrites the
# daemon's own launchd agent, which a governed session must not do (hestia #1152).
#
#   usage:  bash deploy/fleet/canonicalize-macos-seat.sh            # dry run: what would change
#           bash deploy/fleet/canonicalize-macos-seat.sh --apply    # do it, restart, verify, or roll back
#
# WHY NOT JUST RE-RUN install.sh. The installer downloads the latest GitHub RELEASE and would
# replace the from-main build hestia-deploy keeps current; it writes a fresh plist under its own
# template (dropping anything the seat added); and by default it rewires ~/.claude/settings.json.
# A seat that predates the installer (McNugget: hand-installed 2026-05, vault sealed out of band,
# passphrase inline in the plist since 2026-07-25 -- install.sh names it) needs the SHAPE, not a
# reinstall. This edits the existing agent with plutil, so every key it does not name survives.
#
# WHAT IT CHANGES, each only if needed, each printed first:
#   1. $HESTIA_HOME            -> mode 700                     (install.sh:113)
#   2. the vault passphrase    -> $HESTIA_HOME/.passphrase, 600, moved from the plist's
#                                 EnvironmentVariables.HESTIA_PASSPHRASE file-to-file; NEVER printed
#   3. ProgramArguments        -> /bin/sh -c 'HESTIA_PASSPHRASE="$(cat …/.passphrase)" exec <the SAME argv>'
#                                 -- the installer's form around the agent's own argv, every word quoted;
#                                 the binary stays where it is (hestia-deploy's HESTIA_BIN points there)
#   4. EnvironmentVariables    -> HESTIA_PASSPHRASE removed; everything else kept
#   5. KeepAlive               -> {SuccessfulExit: false}: restart on a crash, not after a clean exit
#   6. restart, wait for the daemon to answer, and ROLL BACK to the saved agent if it does not
#
# The saved agent (it still holds the passphrase) is left at $HESTIA_HOME/launchd-before-canonical-*.plist,
# mode 600 inside a 700 directory, for rollback. Delete it once you are satisfied.
#
# Test hooks (not for operators): CANON_AGENT_DIR, CANON_NO_RESTART=1, CANON_LAUNCHCTL, CANON_HEALTH_TRIES.
set -euo pipefail

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1
HESTIA_HOME="${HESTIA_HOME:-$HOME/.hestia}"
LABEL="${HESTIA_LAUNCHD_LABEL:-com.web4.hestia.daemon}"
AGENT_DIR="${CANON_AGENT_DIR:-$HOME/Library/LaunchAgents}"
PLIST="$AGENT_DIR/$LABEL.plist"
PP="$HESTIA_HOME/.passphrase"

say()  { printf '%s\n' "$*"; }
plan() { if [ $APPLY = 1 ]; then printf '  DO    %s\n' "$*"; else printf '  PLAN  %s\n' "$*"; fi; }
ok()   { printf '  ok    %s\n' "$*"; }
die()  { printf 'REFUSED: %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Darwin ] || die "macOS only (this seat is $(uname -s))"
command -v plutil >/dev/null || die "plutil not found"
[ -f "$PLIST" ] || die "no agent at $PLIST (set HESTIA_LAUNCHD_LABEL if this seat uses another label)"
plutil -lint "$PLIST" >/dev/null || die "$PLIST does not lint; fix it by hand first"
[ -d "$HESTIA_HOME" ] || die "no $HESTIA_HOME"

has_key() { plutil -type "$1" "$PLIST" >/dev/null 2>&1; }   # -type: presence without reading the value
say "== canonicalize $LABEL ($([ $APPLY = 1 ] && echo APPLY || echo 'dry run'))"

# ---- 1. HESTIA_HOME mode ------------------------------------------------------------------
mode=$(stat -f %Lp "$HESTIA_HOME")
if [ "$mode" != 700 ]; then plan "chmod 700 $HESTIA_HOME   (is $mode)"; [ $APPLY = 1 ] && chmod 700 "$HESTIA_HOME"
else ok "$HESTIA_HOME is 700"; fi

# ---- 2. the passphrase --------------------------------------------------------------------
inline=0; has_key EnvironmentVariables.HESTIA_PASSPHRASE && inline=1
if [ -s "$PP" ]; then
  if [ $inline = 1 ]; then
    # Both exist. They must agree, or one of them does not open this vault -- refuse rather
    # than guess which. Compared without either value reaching stdout.
    cmp -s "$PP" <(plutil -extract EnvironmentVariables.HESTIA_PASSPHRASE raw "$PLIST" | tr -d '\n') \
      || die "$PP and the plist's inline passphrase DIFFER. One of them does not open the vault; resolve by hand."
    ok "$PP exists and matches the inline value"
  else
    ok "$PP exists, nothing inline"
  fi
elif [ $inline = 1 ]; then
  plan "move the inline passphrase to $PP (mode 600, never printed)"
  if [ $APPLY = 1 ]; then
    ( umask 077; plutil -extract EnvironmentVariables.HESTIA_PASSPHRASE raw "$PLIST" | tr -d '\n' > "$PP" )
    [ -s "$PP" ] || die "wrote an empty $PP; nothing else changed"
    chmod 600 "$PP"
  fi
else
  die "no passphrase source: no $PP and none inline in $PLIST. The running daemon got it from somewhere else; find that before migrating."
fi
if [ -f "$PP" ] && [ "$(stat -f %Lp "$PP")" != 600 ]; then plan "chmod 600 $PP"; [ $APPLY = 1 ] && chmod 600 "$PP"; fi

# ---- 3-5. the agent -----------------------------------------------------------------------
# The daemon's ARGV IS PRESERVED EXACTLY and every word is shell-quoted (GPT, review of #1154: the
# first cut rebuilt it as `serve --bind <default>` -- dropping a seat's own bind or options -- and
# interpolated paths unquoted into shell source, so a space broke it). Two shapes are understood:
#   [<bin>, serve, <opts…>]                                   a direct exec (McNugget's)
#   [/bin/sh, -c, 'HESTIA_PASSPHRASE="$(cat …)" exec <bin> <opts…>']   the installer's form
# Anything else is REFUSED rather than guessed at.
argv_json=$(plutil -extract ProgramArguments json -o - "$PLIST" 2>/dev/null) || die "no ProgramArguments in $PLIST"
parsed=$(python3 - "$argv_json" "$PP" <<'PY'
import json, shlex, sys
argv, pp = json.loads(sys.argv[1]), sys.argv[2]
if argv[:2] == ["/bin/sh", "-c"] and len(argv) == 3:
    toks = shlex.split(argv[2])
    if len(toks) < 3 or not toks[0].startswith("HESTIA_PASSPHRASE=$(cat ") or toks[1] != "exec":
        sys.exit("unsupported /bin/sh -c form: not the installer's `HESTIA_PASSPHRASE=\"$(cat …)\" exec <bin> …`")
    words = toks[2:]
elif argv and argv[0] != "/bin/sh":
    words = argv
else:
    sys.exit(f"unsupported ProgramArguments shape ({len(argv)} elements)")
if len(words) < 2 or words[1] != "serve":
    sys.exit(f"the agent does not run `<hestia> serve …` (got {words[:2]})")
bind = "127.0.0.1:7711"   # `hestia serve`'s own default
for i, w in enumerate(words):
    if w == "--bind" and i + 1 < len(words):
        bind = words[i + 1]
    elif w.startswith("--bind="):
        bind = w.split("=", 1)[1]
line = f'HESTIA_PASSPHRASE="$(cat {shlex.quote(pp)})" exec ' + " ".join(shlex.quote(w) for w in words)
print(words[0]); print(bind); print(line)
PY
) || die "cannot represent this agent's command line exactly; migrate it by hand"
bin=$(printf '%s\n' "$parsed" | sed -n 1p)
BIND=$(printf '%s\n' "$parsed" | sed -n 2p)
want_args=$(printf '%s\n' "$parsed" | sed -n 3p)
[ -x "$bin" ] || die "the agent's binary '$bin' is not executable"
cur_args=$(plutil -extract ProgramArguments.2 raw "$PLIST" 2>/dev/null || true)
ka_type=$(plutil -type KeepAlive "$PLIST" 2>/dev/null || echo absent)
ka_ok=0; [ "$ka_type" = dictionary ] && [ "$(plutil -extract KeepAlive.SuccessfulExit raw "$PLIST" 2>/dev/null)" = false ] && ka_ok=1

changes=0
[ "$cur_args" = "$want_args" ] || { plan "ProgramArguments -> /bin/sh -c '$want_args'"; changes=1; }
[ $inline = 1 ] && { plan "remove EnvironmentVariables.HESTIA_PASSPHRASE"; changes=1; }
[ $ka_ok = 1 ] || { plan "KeepAlive ($ka_type) -> {SuccessfulExit: false}"; changes=1; }
[ "$bin" = "$HOME/.local/bin/hestia" ] || say "  note  binary stays at $bin (canonical is ~/.local/bin/hestia; hestia-deploy's HESTIA_BIN governs where it installs)"

if [ $changes = 0 ]; then say "== already canonical"; exit 0; fi
[ $APPLY = 1 ] || { say "== dry run: nothing changed. Re-run with --apply."; exit 0; }

# The saved agent still holds the passphrase: 600, inside the 700 home.
backup="$HESTIA_HOME/launchd-before-canonical-$(date +%Y%m%d-%H%M%S).plist"
( umask 077; cp "$PLIST" "$backup" )
new="$HESTIA_HOME/.canonical-$$.plist"
( umask 077; cp "$PLIST" "$new" )
plutil -replace ProgramArguments -json "$(python3 -c 'import json,sys;print(json.dumps(["/bin/sh","-c",sys.argv[1]]))' "$want_args")" "$new"
plutil -remove EnvironmentVariables.HESTIA_PASSPHRASE "$new" 2>/dev/null || true
plutil -replace KeepAlive -json '{"SuccessfulExit":false}' "$new"
plutil -lint "$new" >/dev/null || { rm -f "$new"; die "the rewritten agent does not lint; nothing installed"; }
has_key_new() { plutil -type "$1" "$new" >/dev/null 2>&1; }
has_key_new EnvironmentVariables.HESTIA_PASSPHRASE && { rm -f "$new"; die "the passphrase is still in the rewritten agent; nothing installed"; }
mv "$new" "$PLIST"; chmod 644 "$PLIST"
ok "agent rewritten (backup: $backup)"

if [ "${CANON_NO_RESTART:-0}" = 1 ]; then say "== done (restart skipped)"; exit 0; fi

uid=$(id -u)
LAUNCHCTL="${CANON_LAUNCHCTL:-launchctl}"      # test hook: a mock that records and can fail
TRIES="${CANON_HEALTH_TRIES:-30}"
# ONE rollback for every way the restart can fail (GPT, review of #1154: the first cut ran the
# new bootstrap unguarded under `set -e`, so a launchd refusal exited AFTER the old agent was
# stopped and BEFORE the rollback -- the daemon down, the new plist in place). The saved agent is
# restored and restarted; if launchd refuses that too, the operator is told the exact command.
rollback() {
  say "$1 -- ROLLING BACK to the saved agent" >&2
  "$LAUNCHCTL" bootout "gui/$uid/$LABEL" 2>/dev/null || true
  cp "$backup" "$PLIST"; chmod 600 "$PLIST"
  if "$LAUNCHCTL" bootstrap "gui/$uid" "$PLIST"; then
    die "restored and restarted the saved agent ($PLIST, mode 600 because it holds the passphrase). $PP is kept; nothing else changed."
  fi
  die "restored the saved agent, but launchd would not start it either. Run by hand: launchctl bootstrap gui/$uid $PLIST"
}
"$LAUNCHCTL" bootout "gui/$uid/$LABEL" 2>/dev/null || true
sleep 1
"$LAUNCHCTL" bootstrap "gui/$uid" "$PLIST" || rollback "launchctl bootstrap refused the rewritten agent"
for _ in $(seq 1 "$TRIES"); do
  code=$(curl -s -m 2 -o /dev/null -w '%{http_code}' "http://$BIND/" || true)
  [ "$code" = 200 ] && { ok "daemon answers on $BIND"; say "== canonical. Delete $backup once satisfied."; exit 0; }
  sleep 1
done
rollback "the daemon did not answer on $BIND within ${TRIES}s"
