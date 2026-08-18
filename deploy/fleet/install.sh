#!/usr/bin/env bash
# Hestia fleet installer.
#
# Detects platform, downloads the prebuilt binary from GitHub Releases,
# initialises the vault, installs the systemd user unit (Linux) or
# launchd agent (macOS), and prints a smoke-test result.
#
# Idempotent: re-running upgrades the binary and reloads the service
# without touching the vault or chain.
#
# Usage:
#   bash <(curl -fsSL https://raw.githubusercontent.com/dp-web4/hestia/main/deploy/fleet/install.sh)
#
# Or, on a checked-out repo:
#   bash deploy/fleet/install.sh
#
# Environment overrides:
#   HESTIA_VERSION   pin a specific release tag (default: latest)
#   HESTIA_HOME      override install location for state (default: ~/.hestia)
#   HESTIA_BIND      bind address for the daemon (default: 127.0.0.1:7711)
#   HESTIA_SKIP_HOOK if set, do NOT wire ~/.claude/settings.json hooks
#
set -euo pipefail

REPO="dp-web4/hestia"
DEFAULT_VERSION="v0.0.3"
VERSION="${HESTIA_VERSION:-$DEFAULT_VERSION}"
HESTIA_HOME="${HESTIA_HOME:-$HOME/.hestia}"
HESTIA_BIND="${HESTIA_BIND:-127.0.0.1:7711}"
# Detect rather than assume: this fleet is WSL + Linux + macOS with three different
# layouts, and a hardcoded path is wrong on two thirds of it.
if [ -z "${HESTIA_WORKSPACE:-}" ]; then
  for _ws in /mnt/c/exe/projects/ai-agents "$HOME/ai-workspace" "$HOME/ai-agents" "$HOME/repos"; do
    [ -d "$_ws/hestia" ] && HESTIA_WORKSPACE="$_ws" && break
  done
fi
BIN_DIR="$HOME/.local/bin"
BIN_PATH="$BIN_DIR/hestia"

c_dim()  { printf '\033[2m%s\033[0m\n' "$*"; }
c_ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m%s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m%s\033[0m\n' "$*" >&2; }
c_hdr()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

detect_target() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"
  case "$os::$arch" in
    Linux::x86_64)        echo "x86_64-unknown-linux-gnu" ;;
    Linux::aarch64)       echo "aarch64-unknown-linux-gnu" ;;
    Linux::arm64)         echo "aarch64-unknown-linux-gnu" ;;
    Darwin::arm64)        echo "aarch64-apple-darwin" ;;
    Darwin::x86_64)
      c_err "intel mac not in fleet build matrix — use 'cargo install hestia' instead"
      exit 1 ;;
    *) c_err "unsupported platform: $os $arch"; exit 1 ;;
  esac
}

step_download() {
  local target="$1" tmpdir url filename checksum_url
  tmpdir="$(mktemp -d)"
  filename="hestia-${VERSION}-${target}.tar.gz"
  url="https://github.com/${REPO}/releases/download/${VERSION}/${filename}"
  checksum_url="${url}.sha256"
  c_hdr "downloading $filename"
  c_dim "$url"
  if ! curl -fsSL "$url" -o "$tmpdir/$filename"; then
    c_err "download failed; check that ${VERSION} has a release with ${filename}"
    exit 1
  fi
  # P0 (public-release): verify SHA-256 checksum. Signatures will be added in
  # the next phase (minisign/cosign) — this step at least detects corruption
  # or accidental mismatches and prepares the installer shape.
  if curl -fsSL "$checksum_url" -o "$tmpdir/$filename.sha256" 2>/dev/null; then
    (
      cd "$tmpdir"
      if ! sha256sum -c "$filename.sha256" >/dev/null 2>&1; then
        c_err "SHA-256 checksum verification failed for $filename"
        exit 1
      fi
      c_ok "SHA-256 checksum verified"
    )
  else
    c_warn "no checksum file found at $checksum_url — proceeding without verification"
  fi
  tar -xzf "$tmpdir/$filename" -C "$tmpdir"
  mkdir -p "$BIN_DIR"
  install -m 0755 "$tmpdir/hestia-${VERSION}-${target}/hestia" "$BIN_PATH"
  c_ok "installed $BIN_PATH"
  "$BIN_PATH" --version || true
  rm -rf "$tmpdir"
}

step_vault() {
  c_hdr "vault"
  mkdir -p "$HESTIA_HOME"
  chmod 700 "$HESTIA_HOME"
  local pp="$HESTIA_HOME/.passphrase"
  # Read the vault state BEFORE minting, so the mint can be honest about what it
  # is about to do. The bad case: a vault sealed out-of-band (its passphrase held
  # somewhere other than this file -- e.g. inline in a launchd plist, McNugget
  # 2026-07-25) plus a missing .passphrase. We then mint a FRESH secret, find
  # vault.enc already present, leave it alone, and hand the daemon a key that
  # does not open it. Two green lines, an unopenable vault, nothing said so.
  local vault_pre=no
  [ -f "$HESTIA_HOME/vault.enc" ] && vault_pre=yes
  if [ -f "$pp" ] && [ -s "$pp" ]; then
    c_dim "passphrase exists; leaving alone"
  elif [ "$vault_pre" = yes ]; then
    c_warn "VAULT/PASSPHRASE MISMATCH: $HESTIA_HOME/vault.enc exists but $pp does not."
    c_warn "  This vault was sealed with a secret held somewhere else. A generated one will NOT open it."
    c_warn "  Recover the real passphrase first (check launchd plists / systemd units for an inline"
    c_warn "  HESTIA_PASSPHRASE), write it to $pp mode 600, and re-run. Skipping generation."
  else
    if command -v openssl >/dev/null 2>&1; then
      openssl rand -base64 30 | tr -d '\n' > "$pp"
    else
      # Fallback: /dev/urandom + base64 from python (always present)
      head -c 24 /dev/urandom | python3 -c "import sys,base64; sys.stdout.write(base64.b64encode(sys.stdin.buffer.read()).decode())" > "$pp"
    fi
    chmod 600 "$pp"
    c_ok "generated passphrase at $pp (mode 600)"
  fi
  local vault="$HESTIA_HOME/vault.enc"
  if [ -f "$vault" ]; then
    c_dim "vault already initialised at $vault"
  else
    HESTIA_PASSPHRASE="$(cat "$pp")" \
      HESTIA_HOME="$HESTIA_HOME" \
      "$BIN_PATH" init
    c_ok "vault initialised"
  fi
}

step_service_linux() {
  c_hdr "systemd user service"
  local unit_dir="$HOME/.config/systemd/user"
  local unit="$unit_dir/hestia.service"
  mkdir -p "$unit_dir"
  cat > "$unit" <<UNIT
[Unit]
Description=Hestia local-first Web4 trust daemon
Documentation=https://github.com/dp-web4/hestia
# NOT After=default.target. This unit is WantedBy=default.target; ordering it
# *after* the target that wants it is the latent charge. It does NOT cycle on
# its own -- systemd refuses to build the two-node loop ("Don't create loops"):
# a target skips its implicit "order me after what I want" edge for any unit
# that declares a contradicting order. The cycle needs a THIRD unit to bridge:
#   default.target -> watcher (implicit) -> hestia (After=hestia.service)
#                  -> default.target (the bad line)
# systemd breaks that by DELETING a start job, and the victim is whichever unit
# closes the loop -- not necessarily this one. On CBP it silently deleted both
# member-mesh watchers at every boot: the mesh was "enabled" and never ran.
# Found 2026-07-25, the first reboot after the mesh was armed.
# Reboot-free detector: wanted-but-not-ordered == loop-avoidance already fired.
# (No backticks in this heredoc: it is unquoted, so they would be command
# substitution and silently eat the text -- which is what happened to the
# original of this comment.)

# Bound the retry loop. NOT because a start limit was missing: systemd already
# applies StartLimitIntervalSec=10s / StartLimitBurst=5 by default (measured on
# CBP's live unit, which declares neither and still reads 10s/5). The limit was
# there and structurally could not fire -- at RestartSec=5s at most 2-3 attempts
# land in any 10s window, so a burst of 5 is unreachable, the unit never enters
# failed, and nothing reports it broken (nomad: 289 consecutive restarts against
# status=226/NAMESPACE under a WSL kernel).
# The fix is a window WIDER than burst x RestartSec, not the setting's presence:
# 5 x 5s = 25s, so 120s trips. Writing StartLimitIntervalSec=10 here would
# reproduce the forever-loop exactly. Keep this in sync with RestartSec below.
# These are [Unit] keys, not [Service] -- they moved in systemd 229, and are
# silently ignored anywhere else (verify_service_linux probes 1b/1c).
# Measured, not asserted (CBP, systemd 255.4/WSL2, two units identical but for
# the window): 120 -> failed at t=30s on the 5th start ("Start request repeated
# too quickly"); 10 -> 13 restarts at t=70s and still climbing. Probe 1d now
# enforces "keep in sync" instead of leaving it to this comment.
# Boundary, also measured (four units, only the window differing): 20 and 25
# both climb past 15 restarts at t=80s without firing; 30 fails at 5. systemd
# permits burst starts per window and refuses the burst+1-th, which lands at
# burst x RestartSec -- so a window of (burst-1) x RestartSec never fires, and
# window == burst x RestartSec is decided by sub-second jitter. Hence "wider
# than", strictly.
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=simple
ExecStart=/bin/sh -c 'HESTIA_PASSPHRASE="\$(cat %h/.hestia/.passphrase)" exec %h/.local/bin/hestia serve --bind ${HESTIA_BIND}'
Environment=HESTIA_HOME=%h/.hestia
Environment=RUST_LOG=warn
# The workspace the daemon hands to agent-inventory when the dashboard asks for the
# read list. Without it the inventory falls back to a compiled-in default that is only
# correct on the machine it was written on, and — correctly — degrades its whole report
# to UNKNOWN rather than reporting OK off a guess (thor, agent-inventory review §5).
# Per-machine: WSL boxes use /mnt/c/exe/projects/ai-agents, Linux boxes ~/ai-workspace.
Environment=HESTIA_WORKSPACE=${HESTIA_WORKSPACE}
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/.hestia
PrivateTmp=true
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
UNIT
  # `cat >` inherits the caller's umask, so a permissive umask writes a
  # world-writable unit (nomad's live unit was mode 755, which systemd-analyze
  # warns on). Pin it rather than depend on the environment.
  chmod 644 "$unit"
  systemctl --user daemon-reload
  if systemctl --user is-active --quiet hestia.service; then
    systemctl --user restart hestia.service
    c_ok "restarted hestia.service"
  else
    systemctl --user enable --now hestia.service
    c_ok "enabled + started hestia.service"
  fi
  # Linger so the service survives session logout (matters for headless boxes).
  if ! loginctl show-user "$USER" 2>/dev/null | grep -q 'Linger=yes'; then
    sudo loginctl enable-linger "$USER" 2>/dev/null || \
      c_warn "could not enable-linger (sudo may have prompted); service will stop on logout until you run: sudo loginctl enable-linger $USER"
  fi

  verify_service_linux
}

# Normalise a systemd timespan to seconds: "120", "120s", "2min", "1min 30s",
# "1h", "500ms", "infinity". Prints NOTHING when it cannot parse -- callers must
# treat empty as UNKNOWN, never as a match. Needed because systemd echoes a
# written 120 back as "2min", so comparing the rendered strings would report a
# working setting as broken.
_timespan_secs() {
  awk -v s="$1" 'BEGIN{
    if (s == "") exit
    if (s == "infinity") { print "infinity"; exit }
    if (s ~ /^[0-9]+$/)  { print s + 0; exit }
    t = 0; ok = 0
    while (match(s, /[0-9]+(us|ms|min|s|m|h|d)/)) {
      tok = substr(s, RSTART, RLENGTH); s = substr(s, RSTART + RLENGTH)
      v = tok + 0; u = tok; sub(/^[0-9]+/, "", u)
      if (u == "us") v /= 1000000; else if (u == "ms") v /= 1000
      else if (u == "min" || u == "m") v *= 60
      else if (u == "h") v *= 3600; else if (u == "d") v *= 86400
      t += v; ok = 1
    }
    if (ok) print t
  }'
}

# Post-install verification. The recurring defect this guards is "install
# reported success, unit never ran, nothing said so" -- an `enabled` unit reads
# as "will come back" when it may not. Reports inspectable evidence and warns;
# it does NOT fail the install, because the caller decides what the evidence is
# worth. Two known instances: the default.target ordering cycle (2026-07-25) and
# the unbounded 226/NAMESPACE restart loop on WSL (nomad, 289 retries).
verify_service_linux() {
  c_hdr "post-install verification"

  # NOTE on style: this runs under `set -euo pipefail`, and verification must
  # never abort an otherwise-good install. So every probe is `|| true`, and no
  # probe puts a pipeline in an `if` condition -- `grep -q` exits early, which
  # SIGPIPEs the upstream systemctl, and under pipefail the pipeline would then
  # report failure on exactly the runs where the pattern DID match. Capture
  # first, test the string second.

  local unit_file="$HOME/.config/systemd/user/hestia.service"

  # 1. The unit as written must parse. Catches typo'd/misplaced keys -- e.g.
  #    StartLimit* in [Service] instead of [Unit], which systemd silently ignores.
  #    It does NOT catch the ordering cycle, and must not be cited as evidence
  #    that a unit is cycle-free. Measured on CBP (systemd 255.4): against a unit
  #    carrying both After=default.target and WantedBy=default.target, verify
  #    prints nothing and exits 0 -- equally clean before and after the repair.
  #    It never builds a job transaction, so it cannot see a transaction-time
  #    property. Probes 2a-2c are the cycle evidence; this one is "it parses".
  local vout
  vout=$(systemd-analyze --user verify "$unit_file" 2>&1 || true)
  if [ -n "$vout" ]; then
    c_warn "systemd-analyze verify reported:"; printf '%s\n' "$vout"
  else
    c_ok "unit verifies clean"
  fi

  # 1b. Toolchain-free check of StartLimit* placement. Probe 1 does catch the
  #     misplacement -- but only when systemd-analyze actually speaks. Measured:
  #     a stub that exits 0 silently makes probe 1 print "verifies clean" on a
  #     unit with StartLimit* in [Service]; the key is written, ignored by
  #     systemd, and reported green. (A genuinely absent binary is fine: the
  #     "command not found" lands in $vout and warns.) This check needs neither
  #     the toolchain nor a bus.
  local bad_section
  bad_section=$(awk '
    /^[[:space:]]*\[/            { sect = $0 }
    /^[[:space:]]*StartLimit[A-Za-z]*=/ { if (sect != "[Unit]") print "    " sect "  " $0 }
  ' "$unit_file" 2>/dev/null || true)
  if [ -n "$bad_section" ]; then
    c_warn "StartLimit* in the wrong section -- [Unit] keys since systemd 229, ignored where they are:"
    printf '%s\n' "$bad_section"
  else
    c_ok "StartLimit* placement ok (or absent)"
  fi

  # 1c. Readback: did the written StartLimitIntervalSec actually take effect?
  #     Independent of 1b -- catches "right section, still not live" (missing
  #     daemon-reload, a drop-in override). Bus-gated: with no user bus
  #     `systemctl --user show` prints nothing, and empty must read UNKNOWN,
  #     never OK. That exact false-CLEAN is what c510b1e fixed in probe 2c; do
  #     not reintroduce it here. Compare normalised seconds rather than the
  #     rendered string -- systemd echoes 120 back as "2min".
  local written effective ws es
  written=$(awk -F= '/^[[:space:]]*StartLimitIntervalSec=/ {gsub(/[[:space:]]/,"",$2); v=$2} END{print v}' \
              "$unit_file" 2>/dev/null || true)
  if [ -n "$written" ]; then
    effective=$(systemctl --user show hestia.service -p StartLimitIntervalUSec --value 2>/dev/null || true)
    ws=$(_timespan_secs "$written"); es=$(_timespan_secs "$effective")
    if [ -z "$effective" ]; then
      c_warn "StartLimit readback UNKNOWN: no reachable user bus. Probe 1b above is the witness here."
    elif [ -z "$ws" ] || [ -z "$es" ]; then
      c_warn "StartLimit readback UNKNOWN: could not parse written='$written' effective='$effective'."
    elif [ "$ws" != "$es" ]; then
      c_warn "StartLimitIntervalSec=$written written but NOT in effect (live value: $effective)."
      c_warn "  systemd did not take it. Check the section ([Unit], not [Service]) and daemon-reload."
    else
      c_ok "StartLimitIntervalSec=$written is in effect ($effective)"
    fi
  fi

  # 1d. Reachability: CAN the start limit fire at all? Present-and-in-effect is
  #     not the property that matters. systemd counts starts per window, so a
  #     window <= burst x RestartSec can never be filled and the limit is decor.
  #     This is not hypothetical -- it is the actual mechanism behind nomad's 289
  #     restarts on 226/NAMESPACE: the unit declared neither key, inherited the
  #     10s/5 default, and at RestartSec=5s only 2-3 attempts land per window.
  #     Measured on CBP (systemd 255.4, WSL2), two units identical but for the
  #     window: 120 -> failed at t=30s on the 5th start ("Start request repeated
  #     too quickly"); 10 -> 13 restarts at t=70s, still climbing.
  #     The template says "keep in sync with RestartSec"; a comment stating a
  #     rule nothing enforces is the same class of defect as the rest of this
  #     campaign. This probe enforces it.
  #     NOTE: a unit stopped by the start limit keeps Result=exit-code -- it does
  #     NOT become start-limit-hit (measured). Do not key a detector on Result;
  #     ActiveState=failed and the journal line are the witnesses.
  #     DO NOT TIGHTEN the "<=" below to "<", and do not re-derive the threshold
  #     as (burst-1) x RestartSec. That derivation assumes the burst-th start is
  #     the one refused; systemd permits burst starts per window and refuses the
  #     burst+1-th, which lands at burst x RestartSec. Measured on CBP, four
  #     units differing only in the window (burst=5, RestartSec=5s): 20 -> 15
  #     restarts at t=80s and still climbing; 25 -> same, still climbing; 30 ->
  #     failed at 5 starts. So (burst-1) x RestartSec = 20s does not fire, and
  #     at window == burst x RestartSec the refusing start landed at t~=25.0s
  #     against a 25s window -- sub-second jitter decides, and here it decided
  #     against firing. Warning on "<=" is the boundary, not slack above it.
  local restart_pol iv bu rs ivs rss need verdict
  restart_pol=$(systemctl --user show hestia.service -p Restart --value 2>/dev/null || true)
  if [ -z "$restart_pol" ]; then
    c_warn "start-limit reachability UNKNOWN: no reachable user bus."
  elif [ "$restart_pol" = no ]; then
    c_ok "start-limit reachability n/a (Restart=no)"
  else
    iv=$(systemctl --user show hestia.service -p StartLimitIntervalUSec --value 2>/dev/null || true)
    bu=$(systemctl --user show hestia.service -p StartLimitBurst --value 2>/dev/null || true)
    rs=$(systemctl --user show hestia.service -p RestartUSec --value 2>/dev/null || true)
    ivs=$(_timespan_secs "$iv"); rss=$(_timespan_secs "$rs")
    if [ "$ivs" = infinity ]; then
      c_ok "start-limit reachability ok (window is infinity)"
    elif [ -z "$ivs" ] || [ -z "$rss" ] || [ "$rss" = infinity ] || [ -z "$bu" ]; then
      c_warn "start-limit reachability UNKNOWN: window='$iv' burst='$bu' RestartSec='$rs'."
    else
      need=$(awk -v b="$bu" -v r="$rss" 'BEGIN{ printf "%g", b * r }' 2>/dev/null || true)
      verdict=$(awk -v i="$ivs" -v n="$need" 'BEGIN{ print (i <= n) ? "bad" : "ok" }' 2>/dev/null || true)
      if [ "$verdict" = bad ]; then
        c_warn "START LIMIT UNREACHABLE: window $iv <= burst($bu) x RestartSec($rs) = ${need}s."
        c_warn "  The limit is configured and can never fire; a persistent failure retries forever"
        c_warn "  and the unit never enters 'failed'. This is nomad's 289-restart loop."
        c_warn "  Fix: widen StartLimitIntervalSec past ${need}s (or lengthen RestartSec)."
      elif [ "$verdict" = ok ]; then
        c_ok "start-limit reachable (window $iv > burst($bu) x RestartSec($rs) = ${need}s)"
      else
        c_warn "start-limit reachability UNKNOWN: could not compare window='$iv' need='$need'."
      fi
    fi
  fi

  # 2a. On-disk check: the dormant charge. Works with NO user bus at all, which
  #     matters because this probe gets run from headless mesh sessions where
  #     `systemctl --user` reaches nothing. This is the only honest witness there
  #     (HUB and sprout both hit exactly that, 2026-07-24/25).
  local line_present=no
  if [ -f "$unit_file" ] && grep -qE '^[[:space:]]*After=([^#]*[[:space:]])?default\.target([[:space:]]|$)' "$unit_file"; then
    line_present=yes
    c_warn "ORDERING-CYCLE LINE PRESENT on disk: $unit_file declares After=default.target"
    c_warn "  Fix: sed -i '/^After=default\\.target\$/d' $unit_file && systemctl --user daemon-reload"
  else
    c_ok "no After=default.target on disk"
  fi

  # 2b. Is the charge ARMED? The line alone does not detonate -- it needs a third
  #     unit bridging default.target -> watcher -> hestia -> default.target. A box
  #     with the line but no bridge is dormant (sprout); a box with both is one
  #     reboot from silently losing that watcher (cbp was).
  local bridges
  bridges=$(grep -lE '^[[:space:]]*After=([^#]*[[:space:]])?hestia\.service([[:space:]]|$)' \
              "$HOME"/.config/systemd/user/*.service 2>/dev/null || true)
  if [ "$line_present" = yes ]; then
    if [ -n "$bridges" ]; then
      c_warn "  ARMED: these units bridge the loop and can have their start job deleted at next boot:"
      printf '    %s\n' $bridges
    else
      c_warn "  dormant: no unit currently declares After=hestia.service, so nothing closes the loop yet."
      c_warn "  Still fix it -- adding any such watcher later arms it silently."
    fi
  fi

  # 2c. Runtime fingerprint, via the live user manager: wanted-but-not-ordered
  #     means loop-avoidance already fired. Corroborates 2a from the manager's
  #     own graph -- but ONLY if the bus is actually reachable. With no user bus
  #     `systemctl --user show` returns empty and the naive test reads "clean" on
  #     a box that is in fact latent. Empty output is UNKNOWN, never CLEAN.
  #     Match whole space-delimited tokens: a bare `grep hestia.service` also
  #     hits a unit merely named like it (myhestia.service).
  local wants after
  wants=" $(systemctl --user show default.target -p Wants --value 2>/dev/null || true) "
  after=" $(systemctl --user show default.target -p After --value 2>/dev/null || true) "
  if [ -z "${wants// /}" ] && [ -z "${after// /}" ]; then
    c_warn "runtime fingerprint UNKNOWN: no reachable user bus (empty systemctl output)."
    c_warn "  Not a clean result -- the on-disk check above is the authoritative one here."
    c_warn "  To query the real manager: export XDG_RUNTIME_DIR=/run/user/\$(id -u) and re-run."
  elif [ "${wants#* hestia.service }" != "$wants" ] && [ "${after#* hestia.service }" = "$after" ]; then
    c_warn "LATENT ORDERING CYCLE (runtime): hestia.service is wanted by default.target but not ordered after it."
    c_warn "  systemd's loop-avoidance has already fired; a bridging unit can lose its start job at boot."
  else
    c_ok "runtime fingerprint clean (bus reachable, ordering acyclic)"
  fi

  # 3. Cycles are logged against the target and the DELETED victim, never against
  #    hestia.service -- so this must not filter by unit.
  local cyc
  cyc=$(journalctl --user -b 2>/dev/null | grep -i 'ordering cycle\|deleted to break' | tail -5 || true)
  if [ -n "$cyc" ]; then
    c_warn "this boot's journal contains ordering-cycle breakage:"
    printf '%s\n' "$cyc"
  fi

  # 4. active, not merely enabled.
  if systemctl --user is-active --quiet hestia.service; then
    c_ok "hestia.service is active"
  else
    local state
    state=$(systemctl --user is-active hestia.service 2>&1 || true)
    c_warn "hestia.service is NOT active (state: $state)"
    c_warn "  'enabled' alone does not mean it is running; see: journalctl --user -u hestia.service -b"
  fi
}

step_service_macos() {
  c_hdr "launchd user agent"
  local agent_dir="$HOME/Library/LaunchAgents"
  local plist="$agent_dir/io.hestia.tools.plist"
  mkdir -p "$agent_dir"
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>io.hestia.tools</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>HESTIA_PASSPHRASE="\$(cat \$HOME/.hestia/.passphrase)" exec \$HOME/.local/bin/hestia serve --bind ${HESTIA_BIND}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HESTIA_HOME</key><string>${HESTIA_HOME}</string>
    <key>HOME</key><string>${HOME}</string>
    <key>RUST_LOG</key><string>warn</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>${HESTIA_HOME}/hestia.log</string>
  <key>StandardErrorPath</key><string>${HESTIA_HOME}/hestia.err</string>
</dict>
</plist>
PLIST
  launchctl unload "$plist" 2>/dev/null || true
  launchctl load "$plist"
  c_ok "loaded $plist"

  verify_service_macos "$plist" "io.hestia.tools"
}

# launchd's PID for a label, or empty. `launchctl list <label>` prints a plist-ish
# dict and exits non-zero when the label is not loaded at all.
macos_agent_pid() {
  launchctl list "$1" 2>/dev/null | sed -n 's/.*"PID"[[:space:]]*=[[:space:]]*\([0-9]*\);.*/\1/p' | head -1 || true
}

# Prints the path if this plist sets KeepAlive to the literal <true/>; silent otherwise.
# The thing being asked is "what is KeepAlive's VALUE", and neither grep scope answers it:
#   line-scope  -- `<key>KeepAlive</key>[[:space:]]*<true/>` only matches when key and
#                  value share a line. That is the form the heredoc above writes; the
#                  canonical form `plutil` emits, and what a hand-written plist looks
#                  like, puts <true/> on the NEXT line. Measured (GNU grep 3.11): the
#                  two-line and `<true />` forms both read CLEAN.
#   file-scope  -- "<key>KeepAlive</key> somewhere AND <true/> somewhere", the shape
#                  probe 2 uses for `hestia`+`serve`, WARNS ON OUR OWN PLIST: RunAtLoad
#                  supplies the <true/> and KeepAlive is a dict. Measured: it flags the
#                  repo template, the plist written above, and KeepAlive{Crashed:true}.
#                  A probe that fires on its own known-good output is not the safe
#                  direction -- it teaches the operator to skip the whole section.
# So: adjacency, across lines, with comments removed first (a commented-out decoy must
# not fire; a comment BETWEEN key and value must not hide it). Comments are stripped
# with index(), not a regex, because an XML comment may legally contain ">". `[ \t]`
# rather than [[:space:]] -- newlines are already folded to spaces, and character
# classes are not safe on every awk this may meet. Verified identical on gawk 5.2.1,
# mawk and nawk (BWK awk, macOS's).
# Known limit: this reads text, not structure. `plutil -extract KeepAlive xml1 -o -`
# is the right tool and plutil is already a hard dependency (probe 1) -- but this was
# written on Linux and could not be executed against it. Shipping an unrun command is
# the defect this file is about. Left for the Mac; see the PR thread.
plist_uncond_keepalive() {
  awk -v f="$1" '
    { doc = doc $0 " " }
    END {
      while ((i = index(doc, "<!--")) > 0) {
        keep = keep substr(doc, 1, i - 1)
        rest = substr(doc, i + 4)
        j = index(rest, "-->")
        if (j == 0) { doc = ""; break }   # unterminated comment: drop the remainder
        doc = substr(rest, j + 3)
      }
      doc = keep doc
      if (doc ~ /<key>KeepAlive<\/key>[ \t]*<true[ \t]*\/>/) print f
    }
  ' "$1" 2>/dev/null || true
}

# The macOS half of verify_service_linux. Same defect class, different platform,
# and the platform is strictly worse at reporting it (mcnugget, forum 2026-07-25):
#   - `launchctl load` succeeds on a syntactically valid plist and says NOTHING
#     about whether the process runs. `c_ok "loaded"` above is not evidence.
#   - there is no `failed` state to check. KeepAlive respawns forever by design;
#     ThrottleInterval bounds the rate, not the count. So "is it enabled" is
#     unanswerable-by-construction here -- the only honest probe is LIVENESS OVER
#     TIME (same pid across two samples), which is what probe 4 does.
#   - observed instance on the one Mac in the fleet: `com.dp-web4.supervisor`,
#     loaded, no pid, LastExitStatus 78 (EX_CONFIG), silent about all of it.
# Same style discipline as the Linux side: every probe `|| true`, capture first
# and test the string second, warn but never gate.
verify_service_macos() {
  local plist="$1" label="$2"
  c_hdr "post-install verification"

  # 1. The plist as written must parse. Analogue of `systemd-analyze verify`:
  #    launchctl will refuse a malformed file, but say so unhelpfully.
  local lint
  lint=$(plutil -lint "$plist" 2>&1 || true)
  case "$lint" in
    *OK*) c_ok "plist lints clean" ;;
    *)    c_warn "plutil -lint reported:"; printf '%s\n' "$lint" ;;
  esac

  # 2. Label drift: is some OTHER agent already serving hestia under a different
  #    label? The repo template is `io.hestia.tools`; McNugget has been running
  #    `com.web4.hestia.daemon` since 2026-05-21 and ROSTER.md certifies THAT one.
  #    Installing here does not replace it -- it adds a second agent contending for
  #    the same port, and whichever loses is invisible in both.
  #    Match FILE-scope, not line-scope: `hestia serve` is one line in our template
  #    but two separate <string> elements in a hand-written plist (McNugget's is
  #    /opt/homebrew/bin/hestia + serve as distinct array entries), and a
  #    line-anchored regex reads CLEAN on precisely the drift it exists to catch.
  #    Verified: a line-scoped version of this probe missed McNugget's shape.
  local others=""
  local cand
  for cand in "$HOME"/Library/LaunchAgents/*.plist; do
    [ -f "$cand" ] || continue
    [ "$cand" = "$plist" ] && continue
    grep -q 'hestia' "$cand" 2>/dev/null || continue
    grep -q 'serve'  "$cand" 2>/dev/null || continue
    others="${others:+$others
}$cand"
  done
  if [ -n "$others" ]; then
    c_warn "LABEL DRIFT: other LaunchAgents also run 'hestia serve':"
    # read-loop, not `printf %s\\n $var`: macOS paths have spaces in them.
    printf '%s\n' "$others" | while IFS= read -r f; do c_warn "    $f"; done
    c_warn "  Two agents, one bind address. Unload the stale one before trusting this install:"
    c_warn "    launchctl unload <plist>   # then confirm only one pid answers on ${HESTIA_BIND}"
  else
    c_ok "no competing hestia agent in ~/Library/LaunchAgents"
  fi

  # 3. Loaded WITH a pid, not merely loaded. This is the exit-78 shape.
  local pid1
  pid1=$(macos_agent_pid "$label")
  if [ -z "$pid1" ]; then
    local st
    st=$(launchctl list "$label" 2>&1 | sed -n 's/.*"LastExitStatus"[[:space:]]*=[[:space:]]*\([0-9-]*\);.*/\1/p' | head -1 || true)
    c_warn "$label is NOT running (no pid). LastExitStatus: ${st:-<label not loaded>}"
    c_warn "  'loaded' alone does not mean it is running; see: tail ${HESTIA_HOME}/hestia.err"
    [ "$st" = "78" ] && c_warn "  78 = EX_CONFIG: the plist loaded but the program rejected its configuration."
    return 0
  fi
  c_ok "$label is running (pid $pid1)"

  # 4. Liveness over time. A crash loop under KeepAlive presents as a HEALTHY
  #    single sample -- there is always a pid, just never the same one. One extra
  #    sample is the whole difference between "running" and "restarting forever".
  sleep 4
  local pid2
  pid2=$(macos_agent_pid "$label")
  if [ -z "$pid2" ]; then
    c_warn "RESPAWN/EXIT: pid $pid1 is gone 4s later and nothing replaced it."
  elif [ "$pid2" != "$pid1" ]; then
    c_warn "CRASH LOOP: pid changed $pid1 -> $pid2 within 4s. launchd has no 'failed' state,"
    c_warn "  so this can respawn indefinitely while every 'is it loaded' check reads green."
    c_warn "  See: tail ${HESTIA_HOME}/hestia.err"
  else
    c_ok "stable across two samples (pid $pid1 held 4s)"
  fi

  # 5. Secret posture of the LaunchAgents dir. READ-ONLY -- reports, never edits:
  #    relocating a vault passphrase is an operator action, not an installer one.
  #    The template deliberately reads the secret from a 600 file and documents
  #    that as the consumer-tier boundary; a plist carrying the literal inverts it,
  #    because plists are world-readable by default and get copied around.
  local inline
  inline=$(grep -lE '<key>HESTIA_PASSPHRASE</key>' "$HOME"/Library/LaunchAgents/*.plist 2>/dev/null || true)
  if [ -n "$inline" ]; then
    c_warn "INLINE VAULT SECRET: these plists carry HESTIA_PASSPHRASE as a literal:"
    printf '%s\n' "$inline" | while IFS= read -r f; do
      c_warn "    $f (mode $(stat -f '%Lp' "$f" 2>/dev/null || echo '?'))"
    done
    c_warn "  The documented boundary is \$HOME/.hestia/.passphrase at mode 600. Operator call --"
    c_warn "  moving it touches the key that opens the vault; do it deliberately, not from a script."
  fi
  # Unconditional KeepAlive. Same line-scope-vs-file-scope trap probe 2 documents,
  # and BOTH scopes are wrong here -- see plist_uncond_keepalive above (HUB caught
  # the line-anchored miss reviewing eed7254; its proposed two-grep fix flags this
  # installer's own plist).
  local uncond=""
  local ka
  for ka in "$HOME"/Library/LaunchAgents/*.plist; do
    [ -f "$ka" ] || continue
    # Found while exercising this loop: a plist we cannot read used to fall through
    # to silence, i.e. "not inspected" rendered as "clean" -- the c510b1e rule, one
    # more time. UNKNOWN is not a pass.
    if [ ! -r "$ka" ]; then
      c_warn "UNREADABLE: $ka -- KeepAlive posture UNKNOWN, not clean"
      continue
    fi
    [ -n "$(plist_uncond_keepalive "$ka")" ] || continue
    uncond="${uncond:+$uncond
}$ka"
  done
  if [ -n "$uncond" ]; then
    c_warn "UNCONDITIONAL KeepAlive in:"
    printf '%s\n' "$uncond" | while IFS= read -r f; do c_warn "    $f"; done
    c_warn "  Respawns even after a clean exit, so a deliberate shutdown is indistinguishable"
    c_warn "  from a crash loop. Prefer KeepAlive{SuccessfulExit:false}, as this template does."
  fi
}

step_workspace_marker() {
  c_hdr "workspace marker"
  # WHY THIS EXISTS. The gate resolves its scope root from, in order: $HESTIA_WORKSPACE in
  # the HOOK PROCESS env, a `.hestia-workspace` marker walked up from cwd, else cwd itself.
  # As of be944a9 those are the only two non-degenerate branches — and MEASURED on
  # 2026-08-18, neither had a producer anywhere in the tree:
  #
  #   * the env branch needs the variable in the harness hook command. No installer writes
  #     that command; `step_claude_hooks` below prints instructions and returns. The hook
  #     lines on every seat are hand-wired, so there is nothing for an installer to set.
  #   * the marker branch had exactly one writer on main, and it was a test fixture
  #     (tools/public_boundary_test.py). No installed seat has ever had the file.
  #
  # So the gate fell through to cwd on every seat: a session launched inside a repo resolved
  # its workspace to that repo, and sibling-repository grants went inert. That is the
  # documented fail-narrow intent, but it was the ONLY reachable state rather than a
  # fallback. This step gives the portable branch its producer.
  #
  # The marker, not the env var, on purpose: it is per-workspace rather than per-hook, so it
  # covers every harness and every seat at once, it survives a hand-edited settings.json, and
  # it needs no gate edit. Content is documentation only — the gate tests presence.
  if [ -z "${HESTIA_WORKSPACE:-}" ]; then
    c_warn "no workspace root detected — skipping .hestia-workspace marker"
    c_warn "  the gate will resolve its scope root to each session's cwd (fail narrow)"
    c_warn "  re-run with: HESTIA_WORKSPACE=/path/to/workspace $0"
    return
  fi
  local marker="$HESTIA_WORKSPACE/.hestia-workspace"
  if [ -f "$marker" ]; then
    c_ok "marker present: $marker"
    return
  fi
  if [ ! -d "$HESTIA_WORKSPACE" ]; then
    c_warn "workspace root does not exist: $HESTIA_WORKSPACE — marker not written"
    return
  fi
  # Written, then READ BACK. `printf` exiting 0 is not evidence the bytes landed on a
  # filesystem this fleet actually runs on (WSL over NTFS has surprised this repo before).
  printf '%s\n' \
    "# hestia workspace root marker." \
    "# Read by the gate's workspace resolution: presence of this file marks the directory" \
    "# as the gate's scope root. Content is ignored." \
    "# Written by deploy/fleet/install.sh. Safe to commit, safe to delete (deleting it" \
    "# narrows scope resolution to each session's cwd, it does not widen anything)." \
    > "$marker"
  if [ -f "$marker" ]; then
    c_ok "marker written: $marker"
  else
    c_err "marker write reported success but the file is absent: $marker"
    return 1
  fi
}

step_claude_hooks() {
  if [ -n "${HESTIA_SKIP_HOOK:-}" ]; then
    c_dim "claude-code hooks skipped (HESTIA_SKIP_HOOK set)"
    return
  fi
  c_hdr "claude-code hooks"
  local settings="$HOME/.claude/settings.json"
  if [ ! -f "$settings" ]; then
    c_dim "no ~/.claude/settings.json — skipping (install on machines where you run Claude Code)"
    return
  fi
  # Detect plugin location: prefer ~/.hestia/plugins/claude-code, fall
  # back to the repo's plugins/claude-code if running from a checkout.
  local plugin_dir=""
  local repo_root
  repo_root="$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd || true)"
  if [ -d "$HOME/.hestia/plugins/claude-code/hooks" ]; then
    plugin_dir="$HOME/.hestia/plugins/claude-code"
  elif [ -n "$repo_root" ] && [ -d "$repo_root/plugins/claude-code/hooks" ]; then
    plugin_dir="$repo_root/plugins/claude-code"
  fi
  if [ -z "$plugin_dir" ]; then
    c_warn "no hestia claude-code plugin found; fetching plugin source under \$HESTIA_HOME/plugins…"
    mkdir -p "$HESTIA_HOME/plugins"
    curl -fsSL "https://github.com/${REPO}/archive/refs/tags/${VERSION}.tar.gz" \
      | tar -xz -C "$HESTIA_HOME/plugins" --strip-components=2 "hestia-${VERSION#v}/plugins/claude-code"
    plugin_dir="$HESTIA_HOME/plugins/claude-code"
  fi
  c_ok "claude-code plugin at $plugin_dir"
  c_dim "to enable, add the PreToolUse + PostToolUse hooks from $plugin_dir to ~/.claude/settings.json"
  c_dim "(future: 'hestia plugin install claude-code' will do this for you)"
}

step_smoketest() {
  c_hdr "smoke test"
  local host="${HESTIA_BIND%:*}" port="${HESTIA_BIND##*:}"
  # Give the daemon a second to come up.
  for _ in 1 2 3 4 5; do
    if curl -fsS -o /dev/null "http://${host}:${port}/api/dashboard"; then
      c_ok "dashboard reachable at http://${host}:${port}/"
      curl -fsS "http://${host}:${port}/api/dashboard" \
        | python3 -c "import json,sys; d=json.load(sys.stdin); print('  chain length:', d['society']['chain_length']); print('  vault entries:', d['society']['vault_entries']); print('  known plugins:', d['society']['known_plugins'])"
      return 0
    fi
    sleep 1
  done
  c_err "daemon did not respond at http://${host}:${port}/api/dashboard"
  exit 1
}

main() {
  local target os
  target="$(detect_target)"
  os="$(uname -s)"
  c_hdr "hestia fleet installer — ${VERSION} → ${target}"
  step_download "$target"
  step_vault
  case "$os" in
    Linux)  step_service_linux ;;
    Darwin) step_service_macos ;;
    *) c_err "unsupported OS"; exit 1 ;;
  esac
  step_workspace_marker
  step_claude_hooks
  step_smoketest
  c_hdr "done"
  c_ok "open http://${HESTIA_BIND}/ for the dashboard"
  c_dim "logs: journalctl --user -u hestia (Linux) | tail $HESTIA_HOME/hestia.log (macOS)"
}

main "$@"
