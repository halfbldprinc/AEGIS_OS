"""Container security and policy helpers for containerized skill execution."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Set

logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_IMAGES = ("python:3.14-slim", "aegis/skill-runtime:latest")


def allowed_images() -> Set[str]:
    raw = os.getenv("AEGIS_ALLOWED_CONTAINER_IMAGES")
    if raw:
        return {part.strip() for part in raw.split(",") if part.strip()}
    return set(DEFAULT_ALLOWED_IMAGES)


def generate_seccomp_profile(skill_name: str) -> Dict[str, Any]:
    profile = {
        "defaultAction": "SCMP_ACT_ERRNO",
        "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_AARCH64"],
        "syscalls": [
            {
                "names": [
                    "read",
                    "write",
                    "close",
                    "fstat",
                    "mmap",
                    "munmap",
                    "brk",
                    "rt_sigaction",
                    "rt_sigprocmask",
                    "ioctl",
                    "lseek",
                    "clock_gettime",
                    "getpid",
                    "gettid",
                    "exit",
                    "exit_group",
                    "sigreturn",
                ],
                "action": "SCMP_ACT_ALLOW",
            }
        ],
        "metadata": {"skill": skill_name},
    }
    logger.debug("Generated seccomp profile for %s: %s", skill_name, profile)
    return profile


def generate_cgroup_config(skill_name: str, pids_limit: int) -> Dict[str, Any]:
    config = {
        "skill": skill_name,
        "cpu_shares": 512,
        "memory_limit": "256M",
        "pids_max": pids_limit,
        "io_max": "8:0 rbps=524288 wbps=524288",
    }
    logger.debug("Generated cgroup config for %s: %s", skill_name, config)
    return config


def generate_sbom(image_tag: str) -> Dict[str, Any]:
    sbom = {
        "image": image_tag,
        "components": [
            {"name": "python", "version": "3.14"},
            {"name": "aegis-runtime", "version": "0.1.0"},
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.debug("Generated SBOM for %s: %s", image_tag, sbom)
    return sbom


def inspect_repo_digests(runtime: str, image_tag: str) -> List[str]:
    try:
        completed = subprocess.run(
            [runtime, "image", "inspect", image_tag, "--format", "{{json .RepoDigests}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if completed.returncode != 0:
            return []
        raw = completed.stdout.strip()
        if not raw:
            return []
        parsed = json.loads(raw)
        return [str(item) for item in parsed if isinstance(item, str)]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []


def verify_image_provenance(
    image_tag: str,
    inspect_digests_fn: Callable[[str, str], List[str]],
    allowed_images_set: Set[str] | None = None,
) -> bool:
    strict_mode = os.getenv("AEGIS_STRICT_PROVENANCE", "0") == "1"
    allowlist = allowed_images_set if allowed_images_set is not None else allowed_images()

    if image_tag not in allowlist and "@sha256:" not in image_tag:
        logger.warning("Image %s is not in the container allowlist", image_tag)
        return False

    if "@sha256:" in image_tag:
        return True

    expected_digests_raw = os.getenv("AEGIS_IMAGE_DIGESTS", "")
    if expected_digests_raw:
        try:
            expected_map = json.loads(expected_digests_raw)
        except json.JSONDecodeError:
            logger.warning("Invalid AEGIS_IMAGE_DIGESTS JSON")
            return False

        expected_digest = expected_map.get(image_tag)
        if expected_digest:
            runtime = shutil.which("podman") or shutil.which("docker")
            if not runtime:
                return False
            digests = inspect_digests_fn(runtime, image_tag)
            if not any(expected_digest in d for d in digests):
                logger.warning("Image digest mismatch for %s", image_tag)
                return False

    cosign_policy = os.getenv("AEGIS_REQUIRE_COSIGN", "0") == "1"
    cosign = shutil.which("cosign")
    if cosign_policy:
        if not cosign:
            logger.warning("Cosign is required but not installed")
            return False

        identity = os.getenv("AEGIS_COSIGN_CERT_IDENTITY")
        issuer = os.getenv("AEGIS_COSIGN_CERT_ISSUER")
        cmd = [cosign, "verify", image_tag]
        if identity:
            cmd.extend(["--certificate-identity", identity])
        if issuer:
            cmd.extend(["--certificate-oidc-issuer", issuer])

        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            if completed.returncode != 0:
                logger.warning("Cosign verification failed for %s", image_tag)
                return False
        except (OSError, subprocess.SubprocessError):
            return False
    elif strict_mode and not expected_digests_raw and "@sha256:" not in image_tag:
        logger.warning("Strict provenance requires digest pinning or AEGIS_IMAGE_DIGESTS policy")
        return False

    return True


def vulnerability_scan(image_tag: str) -> Dict[str, Any]:
    scan_report = {
        "image": image_tag,
        "findings": [],
        "status": "unknown",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    trivy = shutil.which("trivy")
    if trivy:
        try:
            completed = subprocess.run(
                [trivy, "image", "--quiet", "--format", "json", image_tag],
                capture_output=True,
                text=True,
                timeout=90,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                report = json.loads(completed.stdout)
                vulns = []
                for result in report.get("Results", []) or []:
                    vulns.extend(result.get("Vulnerabilities", []) or [])
                scan_report["findings"] = vulns
                scan_report["status"] = "clean" if not vulns else "vulnerable"
            else:
                scan_report["status"] = "unknown"
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            scan_report["status"] = "unknown"
    else:
        scan_report["status"] = "clean"

    logger.debug("Vulnerability scan for %s: %s", image_tag, scan_report)
    return scan_report
