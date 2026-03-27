#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-/etc/aegis/runtime.env}"
TARGET_DIR="$(dirname "$TARGET")"

mkdir -p "$TARGET_DIR"
touch "$TARGET"

append_if_missing() {
  local key="$1"
  local value="$2"
  if ! grep -Eq "^${key}=" "$TARGET"; then
    printf '%s=%s\n' "$key" "$value" >> "$TARGET"
  fi
}

if ! grep -q "AegisOS runtime policy defaults" "$TARGET"; then
  {
    echo "# AegisOS runtime policy defaults"
    echo "# Existing values are preserved; only missing keys are appended."
  } >> "$TARGET"
fi

append_if_missing "AEGIS_ALLOW_UNSIGNED_BUILTINS" "0"
append_if_missing "AEGIS_AUTO_GRANT_SKILL_PERMISSIONS" "0"
append_if_missing "AEGIS_STRICT_PROVENANCE" "1"
append_if_missing "AEGIS_REQUIRE_COSIGN" "1"
append_if_missing "AEGIS_IMAGE_DIGESTS" "{}"

chmod 640 "$TARGET" || true

echo "Runtime policy defaults ensured at $TARGET"