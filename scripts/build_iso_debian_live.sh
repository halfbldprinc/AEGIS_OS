#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ISO_WORKDIR="${1:-$ROOT_DIR/build/debian-live-aegis}"
DISTRO_CODENAME="${DISTRO_CODENAME:-bookworm}"
ARCH="${ARCH:-amd64}"
IMAGE_NAME="${IMAGE_NAME:-aegisos-${DISTRO_CODENAME}-${ARCH}}"

mkdir -p "$ISO_WORKDIR"
cd "$ISO_WORKDIR"

if ! command -v lb >/dev/null 2>&1; then
  echo "live-build (lb) is required. Install it first: sudo apt-get install -y live-build"
  exit 1
fi

rm -rf config auto local
mkdir -p config/package-lists config/hooks/live config/includes.chroot/opt

lb config \
  --distribution "$DISTRO_CODENAME" \
  --architectures "$ARCH" \
  --binary-images iso-hybrid \
  --archive-areas "main contrib non-free non-free-firmware" \
  --debian-installer live \
  --iso-volume "$IMAGE_NAME"

cat > config/package-lists/aegisos.list.chroot <<'EOF'
python3
python3-venv
python3-pip
rsync
curl
ca-certificates
ffmpeg
podman
git
whiptail
zenity
EOF

# Copy AegisOS source tree into image build chroot context.
rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "build" \
  --exclude "__pycache__" \
  "$ROOT_DIR/" "config/includes.chroot/opt/aegisos/"

cat > config/hooks/live/090-install-aegisos.chroot <<'EOF'
#!/bin/bash
set -euo pipefail
cd /opt/aegisos
chmod +x scripts/install_distro_rootfs.sh
chmod +x scripts/installer_select_model.sh
chmod +x scripts/debian_installer_late_command.sh
./scripts/install_distro_rootfs.sh --no-systemctl

mkdir -p /etc/systemd/system/multi-user.target.wants
ln -sf /etc/systemd/system/aegis-onboarding.service /etc/systemd/system/multi-user.target.wants/aegis-onboarding.service
ln -sf /etc/systemd/system/aegis-api.service /etc/systemd/system/multi-user.target.wants/aegis-api.service
ln -sf /etc/systemd/system/aegis-agent.service /etc/systemd/system/multi-user.target.wants/aegis-agent.service
EOF
chmod +x config/hooks/live/090-install-aegisos.chroot

lb clean --purge || true
lb build

echo "ISO build complete. Check: $ISO_WORKDIR"
ls -1 *.iso 2>/dev/null || true
