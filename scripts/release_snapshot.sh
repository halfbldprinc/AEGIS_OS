#!/usr/bin/env bash
set -euo pipefail

ROLLBACK_ROOT="${AEGIS_ROLLBACK_ROOT:-/var/lib/aegis/rollback}"
REASON="manual"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reason)
      REASON="${2:-manual}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
snapshot_dir="$ROLLBACK_ROOT/$timestamp"

mkdir -p "$snapshot_dir"

if [[ -d /opt/aegisos ]]; then
  rsync -a --delete /opt/aegisos/ "$snapshot_dir/opt_aegisos/"
fi

if [[ -d /etc/aegis ]]; then
  rsync -a --delete /etc/aegis/ "$snapshot_dir/etc_aegis/"
fi

if [[ -f /etc/systemd/system/aegis-onboarding.service ]]; then
  cp -f /etc/systemd/system/aegis-onboarding.service "$snapshot_dir/aegis-onboarding.service"
fi

if [[ -f /etc/systemd/system/aegis-api.service ]]; then
  cp -f /etc/systemd/system/aegis-api.service "$snapshot_dir/aegis-api.service"
fi

if [[ -f /etc/systemd/system/aegis-agent.service ]]; then
  cp -f /etc/systemd/system/aegis-agent.service "$snapshot_dir/aegis-agent.service"
fi

cat > "$snapshot_dir/metadata.env" <<EOF
AEGIS_SNAPSHOT_TIMESTAMP=$timestamp
AEGIS_SNAPSHOT_REASON=$REASON
EOF

chmod -R go-rwx "$snapshot_dir" || true

latest_link="$ROLLBACK_ROOT/latest"
ln -sfn "$snapshot_dir" "$latest_link"

echo "Created AegisOS release snapshot: $snapshot_dir"