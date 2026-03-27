#!/usr/bin/env bash
set -euo pipefail

# Block placeholder-like tokens in production Python source code.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Search only in production package code under aegis/.
scan_paths=("$ROOT_DIR/aegis")

for token in "stub" "placeholder" "not implemented" "mock"; do
  echo "Checking for '$token'..."
  matches=$(grep -R --line-number -E --include='*.py' --exclude-dir='__pycache__' "(^|[^[:alnum:]_])$token([^[:alnum:]_]|$)" "${scan_paths[@]}" || true)
  if [ -n "$matches" ]; then
    echo "ERROR: Forbidden token '$token' found in non-test code:"
    echo "$matches"
    exit 1
  fi
done

echo "no_placeholder_guard: passed"
