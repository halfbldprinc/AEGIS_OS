#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
	echo "Missing virtual environment at $ROOT_DIR/.venv. Use integrated install: sudo ./scripts/install_distro_rootfs.sh"
	exit 1
fi

source .venv/bin/activate
python -m pytest -q tests/test_reliability.py
