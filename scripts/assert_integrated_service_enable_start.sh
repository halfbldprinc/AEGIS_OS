#!/usr/bin/env bash
set -euo pipefail

# Fails if any integrated service is enabled but not started (or vice versa)
# in critical install/package integration scripts.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

FILES=(
  "$ROOT_DIR/scripts/install_distro_rootfs.sh"
  "$ROOT_DIR/packaging/deb/build_deb.sh"
  "$ROOT_DIR/packaging/rpm/aegisos.spec"
)

SERVICES=(
  "aegis-onboarding.service"
  "aegis-api.service"
  "aegis-agent.service"
)

missing=0

for file in "${FILES[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "[ASSERT] Missing file: $file" >&2
    missing=1
    continue
  fi

  for service in "${SERVICES[@]}"; do
    has_enable=0
    has_start=0

    if grep -Eq "systemctl[[:space:]]+enable[[:space:]]+${service}" "$file"; then
      has_enable=1
    fi

    if grep -Eq "systemctl[[:space:]]+start[[:space:]]+${service}" "$file"; then
      has_start=1
    fi

    if [[ "$has_enable" -ne "$has_start" ]]; then
      echo "[ASSERT] Service lifecycle mismatch in $file for ${service}: enable=$has_enable start=$has_start" >&2
      missing=1
    fi

    if [[ "$has_enable" -eq 0 && "$has_start" -eq 0 ]]; then
      echo "[ASSERT] Missing enable/start entries in $file for ${service}" >&2
      missing=1
    fi
  done
done

if [[ "$missing" -ne 0 ]]; then
  echo "Integrated service lifecycle assertion failed." >&2
  exit 1
fi

echo "Integrated service lifecycle assertion passed."
