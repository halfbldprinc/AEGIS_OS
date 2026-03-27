#!/usr/bin/env bash
set -euo pipefail

ROLLBACK_ROOT="${AEGIS_ROLLBACK_ROOT:-/var/lib/aegis/rollback}"
SNAPSHOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --snapshot)
      SNAPSHOT="${2:-}"
      shift 2
      ;;
    --latest)
      SNAPSHOT="latest"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$SNAPSHOT" ]]; then
  echo "Usage: $0 (--latest | --snapshot <timestamp>)" >&2
  exit 1
fi

if [[ "$SNAPSHOT" == "latest" ]]; then
  snapshot_dir="$(readlink "$ROLLBACK_ROOT/latest" || true)"
  if [[ -z "$snapshot_dir" ]]; then
    echo "No latest snapshot link found under $ROLLBACK_ROOT" >&2
    exit 1
  fi
else
  snapshot_dir="$ROLLBACK_ROOT/$SNAPSHOT"
fi

if [[ ! -d "$snapshot_dir" ]]; then
  echo "Snapshot not found: $snapshot_dir" >&2
  exit 1
fi

if [[ -d "$snapshot_dir/opt_aegisos" ]]; then
  mkdir -p /opt/aegisos
  rsync -a --delete "$snapshot_dir/opt_aegisos/" /opt/aegisos/
fi

if [[ -d "$snapshot_dir/etc_aegis" ]]; then
  mkdir -p /etc/aegis
  rsync -a --delete "$snapshot_dir/etc_aegis/" /etc/aegis/
fi

if [[ -f "$snapshot_dir/aegis-onboarding.service" ]]; then
  cp -f "$snapshot_dir/aegis-onboarding.service" /etc/systemd/system/aegis-onboarding.service
fi

if [[ -f "$snapshot_dir/aegis-api.service" ]]; then
  cp -f "$snapshot_dir/aegis-api.service" /etc/systemd/system/aegis-api.service
fi

if [[ -f "$snapshot_dir/aegis-agent.service" ]]; then
  cp -f "$snapshot_dir/aegis-agent.service" /etc/systemd/system/aegis-agent.service
fi

systemctl daemon-reload || true
systemctl restart aegis-onboarding.service >/dev/null 2>&1 || true
systemctl restart aegis-api.service >/dev/null 2>&1 || true
systemctl restart aegis-agent.service >/dev/null 2>&1 || true

echo "Rollback completed from snapshot: $snapshot_dir"