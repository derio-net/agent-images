#!/usr/bin/env bash
# install-base-runtimes.sh — Image-time install of the Layer-1 runtime managers.
# These are slow-changing, baked into the image. Per-user state lives on the PVC.
set -euo pipefail

# Build dependencies the managers themselves need at install time, plus
# python3-yaml for install-inventory.sh's YAML parsing. The inventory script
# deliberately uses the system python (/usr/bin/python3 + apt-installed
# PyYAML) for parsing rather than a mise-managed runtime — at cont-init.d
# boot time mise shims are not yet on PATH for the script's own environment,
# and we want YAML parsing to keep working even before any mise tools land
# on the PV.
apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates curl build-essential pkg-config libssl-dev \
    python3 python3-pip python3-yaml pipx jq
rm -rf /var/lib/apt/lists/*

# mise — asdf-style multi-runtime version manager. System-wide binary;
# per-user toolchains and shims under $HOME/.local/share/mise on the PV.
curl -fsSL https://mise.run | MISE_INSTALL_PATH=/usr/local/bin/mise sh
chmod +x /usr/local/bin/mise

# rustup — system-wide binary only; toolchains live under $HOME/.rustup on
# the PV (each operator gets a fresh rustup root on first run). Steering the
# bootstrap RUSTUP_HOME/CARGO_HOME under /tmp keeps the image slim and avoids
# leaving orphaned root-owned state under /root or /usr/local that the
# runtime user could not read or extend anyway. --default-toolchain none
# keeps the image slim; the operator pulls toolchains via mise
# (rust@stable) or `rustup toolchain install` on demand.
export RUSTUP_HOME=/tmp/rustup-bootstrap CARGO_HOME=/tmp/cargo-bootstrap
mkdir -p "$RUSTUP_HOME" "$CARGO_HOME"
curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs \
  | sh -s -- -y --default-toolchain none --no-modify-path
mv "$CARGO_HOME"/bin/rustup /usr/local/bin/rustup
chmod +x /usr/local/bin/rustup
rm -rf "$RUSTUP_HOME" "$CARGO_HOME" /root/.cargo /root/.rustup

# pipx came from apt above. Confirm.
command -v pipx >/dev/null
command -v mise >/dev/null
command -v rustup >/dev/null
command -v python3 >/dev/null
