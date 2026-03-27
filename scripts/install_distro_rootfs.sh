#!/usr/bin/env bash
set -euo pipefail

NO_SYSTEMCTL=0
for arg in "$@"; do
  if [[ "$arg" == "--no-systemctl" ]]; then
    NO_SYSTEMCTL=1
  fi
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo ./scripts/install_distro_rootfs.sh"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="/opt/aegisos"

has_systemd() {
  command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]
}

if [[ -d "$INSTALL_DIR" ]]; then
  bash "$ROOT_DIR/scripts/release_snapshot.sh" --reason "rootfs-install-upgrade" || true
fi

if ! id -u aegis >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/aegis --shell /usr/sbin/nologin aegis
fi

mkdir -p "$INSTALL_DIR"
rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  "$ROOT_DIR/" "$INSTALL_DIR/"

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip
"$INSTALL_DIR/.venv/bin/python" -m pip install "$INSTALL_DIR[api,llm]"

install -d -m 755 /etc/aegis
install -d -m 755 /etc/xdg/autostart
install -m 644 "$INSTALL_DIR/deploy/model_catalog.json" /etc/aegis/model_catalog.json
install -m 644 "$INSTALL_DIR/deploy/autostart/aegis-text-fallback.desktop" /etc/xdg/autostart/aegis-text-fallback.desktop
touch /etc/aegis/install-selections.env
bash "$INSTALL_DIR/scripts/runtime_policy_defaults.sh" /etc/aegis/runtime.env

install -m 644 "$INSTALL_DIR/deploy/systemd/aegis-onboarding.service" /etc/systemd/system/aegis-onboarding.service
install -m 644 "$INSTALL_DIR/deploy/systemd/aegis-api.integrated.service" /etc/systemd/system/aegis-api.service
install -m 644 "$INSTALL_DIR/deploy/systemd/aegis-agent.integrated.service" /etc/systemd/system/aegis-agent.service

mkdir -p /var/lib/aegis
chown -R aegis:aegis /var/lib/aegis
chmod 640 /etc/aegis/install-selections.env || true

if [[ "$NO_SYSTEMCTL" -eq 1 ]]; then
  echo "Skipping systemctl operations (--no-systemctl)."
elif ! has_systemd; then
  echo "systemd not active in this environment; skipping systemctl operations."
else
  systemctl daemon-reload
  systemctl enable aegis-onboarding.service
  systemctl enable aegis-api.service
  systemctl enable aegis-agent.service
  systemctl start aegis-onboarding.service || true
  systemctl start aegis-api.service || true
  systemctl start aegis-agent.service || true
fi

echo "AegisOS integrated install complete"
echo "Reboot or run: systemctl start aegis-onboarding.service && systemctl start aegis-api.service && systemctl start aegis-agent.service"
