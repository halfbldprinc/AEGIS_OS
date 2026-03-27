#!/usr/bin/env bash
set -euo pipefail

# Debian Installer late_command helper.
# Run inside installer environment and target root mounted at /target.
# Example preseed usage:
# d-i preseed/late_command string in-target mkdir -p /opt/aegisos ; \
#   cp -a /cdrom/opt/aegisos /opt/ ; \
#   /opt/aegisos/scripts/debian_installer_late_command.sh /target

TARGET_ROOT="${1:-/target}"

if [[ ! -d "$TARGET_ROOT" ]]; then
  echo "Target root not found: $TARGET_ROOT"
  exit 1
fi

# The script is interactive and writes install selections to target rootfs.
"$(dirname "$0")/installer_select_model.sh" "$TARGET_ROOT" "$TARGET_ROOT/etc/aegis/install-selections.env"

echo "Debian installer selections completed"
