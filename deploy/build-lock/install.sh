#!/usr/bin/env bash
# Install the cargo build-lock shim (issue #358). Places the shim at ~/.local/bin/cargo, which
# must PRECEDE the real cargo (~/.cargo/bin) in PATH for the interception to take effect.
#
# Usage:  ./install.sh            # installs to ~/.local/bin/cargo
#         ./install.sh <dest>     # installs to a custom path
#
# Idempotent. Verifies PATH ordering and warns (does not fail) if the shim is shadowed.
set -eu

DEST="${1:-$HOME/.local/bin/cargo}"
SRC="$(cd "$(dirname "$0")" && pwd)/cargo"

[ -f "$SRC" ] || { echo "install.sh: shim not found next to installer ($SRC)" >&2; exit 1; }

mkdir -p "$(dirname "$DEST")"
install -m 0755 "$SRC" "$DEST"
echo "installed cargo build-lock shim -> $DEST"

hash -r 2>/dev/null || true
resolved="$(command -v cargo || true)"
if [ "$resolved" = "$DEST" ]; then
  echo "OK: 'cargo' now resolves to the shim"
  echo "verify: cargo --version   # should print the real cargo version (pass-through)"
else
  echo "WARNING: 'cargo' resolves to '$resolved', not the shim." >&2
  echo "         Ensure '$(dirname "$DEST")' precedes the real cargo directory in PATH." >&2
fi
