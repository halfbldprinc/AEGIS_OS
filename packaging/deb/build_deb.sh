#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${VERSION:-0.1.0}"
ARCH="${ARCH:-amd64}"
PKG_NAME="aegisos"
BUILD_DIR="$ROOT_DIR/build/packages/deb"
PKG_ROOT="$BUILD_DIR/${PKG_NAME}_${VERSION}_${ARCH}"
DEBIAN_DIR="$PKG_ROOT/DEBIAN"

command -v dpkg-deb >/dev/null 2>&1 || {
  echo "dpkg-deb is required" >&2
  exit 1
}

rm -rf "$BUILD_DIR"
mkdir -p "$DEBIAN_DIR" "$PKG_ROOT/opt" "$PKG_ROOT/etc/systemd/system" "$PKG_ROOT/etc/xdg/autostart"

rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "build" \
  --exclude "__pycache__" \
  --exclude "aegisos.egg-info" \
  "$ROOT_DIR/" "$PKG_ROOT/opt/aegisos/"

cp "$ROOT_DIR/deploy/systemd/aegis-onboarding.service" "$PKG_ROOT/etc/systemd/system/aegis-onboarding.service"
cp "$ROOT_DIR/deploy/systemd/aegis-api.integrated.service" "$PKG_ROOT/etc/systemd/system/aegis-api.service"
cp "$ROOT_DIR/deploy/systemd/aegis-agent.integrated.service" "$PKG_ROOT/etc/systemd/system/aegis-agent.service"
cp "$ROOT_DIR/deploy/autostart/aegis-text-fallback.desktop" "$PKG_ROOT/etc/xdg/autostart/aegis-text-fallback.desktop"

cat > "$DEBIAN_DIR/control" <<EOF
Package: $PKG_NAME
Version: $VERSION
Section: admin
Priority: optional
Architecture: $ARCH
Maintainer: AegisOS Team <maintainers@aegisos.local>
Depends: python3, python3-venv, python3-pip, systemd, ffmpeg, zenity
Description: Linux distro integrated local AI assistant runtime
 AegisOS provides a local-first assistant runtime with installer-stage model
 selection, policy-gated execution, and systemd-managed services.
EOF

cat > "$DEBIAN_DIR/postinst" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

trap 'echo "AegisOS postinst failed. Restore with: /opt/aegisos/scripts/release_rollback.sh --latest" >&2' ERR

has_systemd() {
  command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]
}

if ! id -u aegis >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/aegis --shell /usr/sbin/nologin aegis || true
fi

mkdir -p /etc/aegis /var/lib/aegis
cp -f /opt/aegisos/deploy/model_catalog.json /etc/aegis/model_catalog.json
touch /etc/aegis/install-selections.env
chmod 640 /etc/aegis/install-selections.env || true
bash /opt/aegisos/scripts/runtime_policy_defaults.sh /etc/aegis/runtime.env || true

python3 -m venv /opt/aegisos/.venv
/opt/aegisos/.venv/bin/python -m pip install --upgrade pip
/opt/aegisos/.venv/bin/python -m pip install "/opt/aegisos[api,llm]"

chown -R aegis:aegis /var/lib/aegis

if has_systemd; then
  systemctl daemon-reload || true
  systemctl enable aegis-onboarding.service || true
  systemctl enable aegis-api.service || true
  systemctl enable aegis-agent.service || true
  systemctl start aegis-onboarding.service || true
  systemctl start aegis-api.service || true
  systemctl start aegis-agent.service || true
fi
EOF
chmod 755 "$DEBIAN_DIR/postinst"

cat > "$DEBIAN_DIR/preinst" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ -d /opt/aegisos ]]; then
  bash /opt/aegisos/scripts/release_snapshot.sh --reason "deb-preinst" || true
fi
EOF
chmod 755 "$DEBIAN_DIR/preinst"

cat > "$DEBIAN_DIR/prerm" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now aegis-agent.service >/dev/null 2>&1 || true
  systemctl disable --now aegis-api.service >/dev/null 2>&1 || true
  systemctl disable --now aegis-onboarding.service >/dev/null 2>&1 || true
  systemctl daemon-reload || true
fi
EOF
chmod 755 "$DEBIAN_DIR/prerm"

OUTPUT_DEB="$BUILD_DIR/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --build "$PKG_ROOT" "$OUTPUT_DEB"

echo "Built Debian package: $OUTPUT_DEB"
