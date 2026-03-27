#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${VERSION:-0.1.0}"
PKG_NAME="aegisos"
BUILD_TOP="$ROOT_DIR/build/packages/rpm"

command -v rpmbuild >/dev/null 2>&1 || {
  echo "rpmbuild is required" >&2
  exit 1
}

rm -rf "$BUILD_TOP"
mkdir -p "$BUILD_TOP"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

SPEC_SRC="$ROOT_DIR/packaging/rpm/aegisos.spec"
SPEC_DST="$BUILD_TOP/SPECS/aegisos.spec"
cp "$SPEC_SRC" "$SPEC_DST"
sed -i.bak "s/^Version:.*/Version:        $VERSION/" "$SPEC_DST"
rm -f "$SPEC_DST.bak"

SRC_DIR="$BUILD_TOP/SOURCES/${PKG_NAME}-${VERSION}"
mkdir -p "$SRC_DIR"
rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "build" \
  --exclude "__pycache__" \
  --exclude "aegisos.egg-info" \
  "$ROOT_DIR/" "$SRC_DIR/"

pushd "$BUILD_TOP/SOURCES" >/dev/null
tar -czf "${PKG_NAME}-${VERSION}.tar.gz" "${PKG_NAME}-${VERSION}"
popd >/dev/null

rpmbuild \
  --define "_topdir $BUILD_TOP" \
  -bb "$SPEC_DST"

echo "Built RPM package(s):"
find "$BUILD_TOP/RPMS" -type f -name "*.rpm" -print
