#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="$ROOT_DIR/build/debian-live-aegis"
ISO_PATH=""
ARTIFACT_ROOT="$ROOT_DIR/build/evidence/iso-validation"
RUN_BUILD=0
MIN_ISO_BYTES="${MIN_ISO_BYTES:-52428800}"

usage() {
  cat <<'EOF'
Usage: ./scripts/validate_iso_evidence.sh [options]

Options:
  --build                    Run ISO build before validation.
  --workdir <path>           ISO workdir (default: build/debian-live-aegis).
  --iso <path>               Explicit ISO path to validate.
  --artifact-root <path>     Evidence output root.
  --min-size-bytes <bytes>   Minimum acceptable ISO size (default: 52428800).
  -h, --help                 Show this help.

Output:
  build/evidence/iso-validation/<timestamp>/
    - summary.md
    - summary.env
    - checks.tsv
    - environment.txt
    - build.log (if --build)
    - iso_file.txt
    - iso_listing_*.txt (when tools exist)
    - checksums.txt
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build)
      RUN_BUILD=1
      shift
      ;;
    --workdir)
      WORKDIR="${2:-}"
      shift 2
      ;;
    --iso)
      ISO_PATH="${2:-}"
      shift 2
      ;;
    --artifact-root)
      ARTIFACT_ROOT="${2:-}"
      shift 2
      ;;
    --min-size-bytes)
      MIN_ISO_BYTES="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
artifact_dir="$ARTIFACT_ROOT/$timestamp"
mkdir -p "$artifact_dir"

checks_file="$artifact_dir/checks.tsv"
summary_env="$artifact_dir/summary.env"
touch "$checks_file"

validation_failed=0

record_check() {
  local name="$1"
  local status="$2"
  local detail="$3"
  printf '%s\t%s\t%s\n' "$name" "$status" "$detail" >> "$checks_file"
  if [[ "$status" == "FAIL" ]]; then
    validation_failed=1
  fi
}

{
  echo "timestamp_utc=$timestamp"
  echo "root_dir=$ROOT_DIR"
  echo "workdir=$WORKDIR"
  echo "run_build=$RUN_BUILD"
} > "$summary_env"

{
  echo "date_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "uname=$(uname -a)"
  if command -v git >/dev/null 2>&1; then
    echo "git_commit=$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "git_status_short="
    git -C "$ROOT_DIR" status --short || true
  fi
  echo "python_version=$(python3 --version 2>/dev/null || echo unknown)"
  echo "lb_version=$(lb --version 2>/dev/null | head -n 1 || echo unavailable)"
} > "$artifact_dir/environment.txt"

record_check "env.capture" "PASS" "Wrote environment.txt"

if [[ "$RUN_BUILD" -eq 1 ]]; then
  if [[ -x "$ROOT_DIR/scripts/build_iso_debian_live.sh" ]]; then
    if DISTRO_CODENAME="${DISTRO_CODENAME:-bookworm}" ARCH="${ARCH:-amd64}" \
      "$ROOT_DIR/scripts/build_iso_debian_live.sh" "$WORKDIR" >"$artifact_dir/build.log" 2>&1; then
      record_check "iso.build" "PASS" "ISO build completed"
    else
      record_check "iso.build" "FAIL" "ISO build failed; see build.log"
    fi
  else
    record_check "iso.build" "FAIL" "scripts/build_iso_debian_live.sh not executable"
  fi
fi

if [[ -z "$ISO_PATH" ]]; then
  latest_iso="$(ls -1t "$WORKDIR"/*.iso 2>/dev/null | head -n 1 || true)"
  if [[ -n "$latest_iso" ]]; then
    ISO_PATH="$latest_iso"
  fi
fi

if [[ -z "$ISO_PATH" ]]; then
  record_check "iso.locate" "FAIL" "No ISO found. Provide --iso or run with --build"
else
  echo "iso_path=$ISO_PATH" >> "$summary_env"
  record_check "iso.locate" "PASS" "Using ISO: $ISO_PATH"
fi

iso_size_bytes=0
iso_sha256=""

if [[ -n "$ISO_PATH" ]]; then
  if [[ -f "$ISO_PATH" ]]; then
    record_check "iso.exists" "PASS" "ISO exists"
  else
    record_check "iso.exists" "FAIL" "ISO does not exist: $ISO_PATH"
  fi

  if [[ -f "$ISO_PATH" ]]; then
    iso_size_bytes="$(stat -f%z "$ISO_PATH" 2>/dev/null || echo 0)"
    echo "iso_size_bytes=$iso_size_bytes" >> "$summary_env"
    if [[ "$iso_size_bytes" -ge "$MIN_ISO_BYTES" ]]; then
      record_check "iso.size" "PASS" "Size=${iso_size_bytes} bytes"
    else
      record_check "iso.size" "FAIL" "Size=${iso_size_bytes} bytes (< ${MIN_ISO_BYTES})"
    fi

    file "$ISO_PATH" > "$artifact_dir/iso_file.txt" 2>&1 || true
    record_check "iso.file" "PASS" "Captured file(1) output"

    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum "$ISO_PATH" > "$artifact_dir/checksums.txt"
      iso_sha256="$(awk '{print $1}' "$artifact_dir/checksums.txt")"
      record_check "iso.sha256" "PASS" "Computed with sha256sum"
    elif command -v shasum >/dev/null 2>&1; then
      shasum -a 256 "$ISO_PATH" > "$artifact_dir/checksums.txt"
      iso_sha256="$(awk '{print $1}' "$artifact_dir/checksums.txt")"
      record_check "iso.sha256" "PASS" "Computed with shasum"
    else
      record_check "iso.sha256" "FAIL" "No sha256 tool available"
    fi
    echo "iso_sha256=$iso_sha256" >> "$summary_env"

    if command -v isoinfo >/dev/null 2>&1; then
      isoinfo -d -i "$ISO_PATH" > "$artifact_dir/iso_listing_isoinfo.txt" 2>&1 || true
      record_check "iso.isoinfo" "PASS" "Captured isoinfo metadata"
    else
      record_check "iso.isoinfo" "WARN" "isoinfo not installed"
    fi

    if command -v xorriso >/dev/null 2>&1; then
      xorriso -indev "$ISO_PATH" -toc > "$artifact_dir/iso_listing_xorriso_toc.txt" 2>&1 || true
      record_check "iso.xorriso" "PASS" "Captured xorriso TOC"
    else
      record_check "iso.xorriso" "WARN" "xorriso not installed"
    fi

    if command -v bsdtar >/dev/null 2>&1; then
      bsdtar -tf "$ISO_PATH" > "$artifact_dir/iso_listing_bsdtar.txt" 2>&1 || true
      if grep -q "live/filesystem.squashfs" "$artifact_dir/iso_listing_bsdtar.txt"; then
        record_check "iso.layout" "PASS" "Found live/filesystem.squashfs"
      else
        record_check "iso.layout" "WARN" "Could not confirm live/filesystem.squashfs via bsdtar"
      fi
    else
      record_check "iso.layout" "WARN" "bsdtar not installed"
    fi
  fi
fi

pass_count="$(awk -F '\t' '$2=="PASS" {c++} END {print c+0}' "$checks_file")"
warn_count="$(awk -F '\t' '$2=="WARN" {c++} END {print c+0}' "$checks_file")"
fail_count="$(awk -F '\t' '$2=="FAIL" {c++} END {print c+0}' "$checks_file")"

{
  echo "pass_count=$pass_count"
  echo "warn_count=$warn_count"
  echo "fail_count=$fail_count"
  if [[ "$validation_failed" -eq 1 ]]; then
    echo "validation_status=failed"
  else
    echo "validation_status=passed"
  fi
} >> "$summary_env"

{
  echo "# ISO Validation Evidence"
  echo
  echo "- Timestamp (UTC): $timestamp"
  echo "- Validation status: $([[ "$validation_failed" -eq 1 ]] && echo failed || echo passed)"
  echo "- Artifact directory: $artifact_dir"
  echo "- ISO path: ${ISO_PATH:-not-found}"
  echo "- ISO size bytes: $iso_size_bytes"
  echo "- ISO sha256: ${iso_sha256:-unavailable}"
  echo
  echo "## Check Results"
  echo
  awk -F '\t' 'BEGIN {print "| Check | Status | Detail |"; print "|---|---|---|"} {printf "| %s | %s | %s |\n", $1, $2, $3}' "$checks_file"
  echo
  echo "## Evidence Files"
  echo
  ls -1 "$artifact_dir" | sed 's/^/- /'
} > "$artifact_dir/summary.md"

echo "Validation artifacts exported to: $artifact_dir"
if [[ "$validation_failed" -eq 1 ]]; then
  echo "ISO validation failed. See summary: $artifact_dir/summary.md" >&2
  exit 1
fi

echo "ISO validation passed. See summary: $artifact_dir/summary.md"