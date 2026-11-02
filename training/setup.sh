#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
command -v gcc >/dev/null || { echo 'Install build-essential python3-dev python3-venv pkg-config curl first'; exit 1; }
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --index-url https://pypi.org/simple numpy==2.2.6 maturin==1.15.0
# CPU default. For GPU follow README and replace this wheel deliberately.
.venv/bin/python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.8.0
if [ ! -x "$HOME/.cargo/bin/rustup" ]; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o build-rustup-init.sh
  sh build-rustup-init.sh -y --profile minimal --default-toolchain 1.98.1 --no-modify-path
else
  "$HOME/.cargo/bin/rustup" toolchain install 1.98.1 --profile minimal
fi
.venv/bin/python bootstrap.py "$@"
