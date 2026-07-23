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
  if [ -f "$pp" ] && [ -s "$pp" ]; then
    c_dim "passphrase exists; leaving alone"
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
After=default.target

[Service]
Type=simple
ExecStart=/bin/sh -c 'HESTIA_PASSPHRASE="\$(cat %h/.hestia/.passphrase)" exec %h/.local/bin/hestia serve --bind ${HESTIA_BIND}'
Environment=HESTIA_HOME=%h/.hestia
Environment=RUST_LOG=warn
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=%h/.hestia
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
  step_claude_hooks
  step_smoketest
  c_hdr "done"
  c_ok "open http://${HESTIA_BIND}/ for the dashboard"
  c_dim "logs: journalctl --user -u hestia (Linux) | tail $HESTIA_HOME/hestia.log (macOS)"
}

main "$@"
