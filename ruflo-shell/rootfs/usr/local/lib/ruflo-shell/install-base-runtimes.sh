#!/usr/bin/env bash
# install-base-runtimes.sh — Image-time install of the Layer-1 runtime managers.
# These are slow-changing, baked into the image. Per-user state lives on the PVC.
set -euo pipefail

# Build dependencies the managers themselves need at install time.
apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates curl build-essential pkg-config libssl-dev \
    python3 python3-pip python3-yaml pipx jq
rm -rf /var/lib/apt/lists/*

# mise — asdf-style multi-runtime version manager. System-wide binary;
# per-user toolchains and shims under $HOME/.local/share/mise on the PV.
curl -fsSL https://mise.run | MISE_INSTALL_PATH=/usr/local/bin/mise sh
chmod +x /usr/local/bin/mise

# rustup — system-wide binary; toolchains live under $HOME/.rustup on the PV.
# --default-toolchain none keeps the image slim; the inventory installer pulls
# toolchains via mise (rust@stable) or `rustup toolchain install` on demand.
export RUSTUP_HOME=/usr/local/lib/rustup CARGO_HOME=/tmp/cargo-bootstrap
mkdir -p "$RUSTUP_HOME" "$CARGO_HOME"
curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs \
  | sh -s -- -y --default-toolchain none --no-modify-path
mv "$CARGO_HOME"/bin/rustup /usr/local/bin/rustup
chmod +x /usr/local/bin/rustup
rm -rf "$CARGO_HOME"

# pipx came from apt above. Confirm.
command -v pipx >/dev/null
command -v mise >/dev/null
command -v rustup >/dev/null
command -v python3 >/dev/null
