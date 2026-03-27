#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-$PWD/build/distro-base}"
DISTRO="${2:-debian-live}"

mkdir -p "$TARGET_DIR"

case "$DISTRO" in
  debian-live)
    REPO_URL="https://salsa.debian.org/live-team/live-images.git"
    ;;
  ubuntu-cdimage)
    REPO_URL="https://git.launchpad.net/livecd-rootfs"
    ;;
  *)
    echo "Unsupported distro base '$DISTRO'. Supported: debian-live, ubuntu-cdimage"
    exit 1
    ;;
esac

if [[ -d "$TARGET_DIR/.git" ]]; then
  echo "Repository already exists at $TARGET_DIR"
  exit 0
fi

git clone "$REPO_URL" "$TARGET_DIR"
echo "Cloned $DISTRO base to $TARGET_DIR"
