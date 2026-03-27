import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psutil


@dataclass(frozen=True)
class HardwareProfile:
    cpu_cores: int
    total_ram_gb: int
    total_storage_gb: int
    has_gpu: bool
    gpu_vendor: str
    vram_gb: int


def detect_hardware_profile(root_path: str = "/") -> HardwareProfile:
    cpu_cores = int(psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True) or os.cpu_count() or 1)
    total_ram_gb = max(1, int(psutil.virtual_memory().total / (1024**3)))
    disk = shutil.disk_usage(root_path)
    total_storage_gb = max(1, int(disk.total / (1024**3)))

    gpu_vendor, vram_gb = _detect_gpu()
    has_gpu = gpu_vendor != "none"

    return HardwareProfile(
        cpu_cores=cpu_cores,
        total_ram_gb=total_ram_gb,
        total_storage_gb=total_storage_gb,
        has_gpu=has_gpu,
        gpu_vendor=gpu_vendor,
        vram_gb=vram_gb,
    )


def _detect_gpu() -> tuple[str, int]:
    nvidia_vram = _detect_nvidia_vram_gb()
    if nvidia_vram is not None:
        return "nvidia", nvidia_vram

    rocm_vram = _detect_rocm_vram_gb()
    if rocm_vram is not None:
        return "amd", rocm_vram

    if platform.system().lower() == "darwin":
        apple_vram = _detect_apple_gpu_vram_gb()
        if apple_vram is not None:
            return "apple", apple_vram

    return "none", 0


def _detect_nvidia_vram_gb() -> Optional[int]:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if completed.returncode != 0:
        return None

    values = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            values.append(int(float(line)))
        except ValueError:
            continue

    if not values:
        return None

    return max(1, int(max(values) / 1024))


def _detect_rocm_vram_gb() -> Optional[int]:
    if not shutil.which("rocm-smi"):
        return None
    try:
        completed = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if completed.returncode != 0:
        return None

    # Expected text includes MB values like: "VRAM Total Memory (B): 8589934592"
    bytes_values = []
    for token in completed.stdout.replace(",", " ").split():
        if not token.isdigit():
            continue
        maybe_bytes = int(token)
        if maybe_bytes > 1024**3:
            bytes_values.append(maybe_bytes)

    if not bytes_values:
        return None

    return max(1, int(max(bytes_values) / (1024**3)))


def _detect_apple_gpu_vram_gb() -> Optional[int]:
    if not shutil.which("system_profiler"):
        return None
    try:
        completed = subprocess.run(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if completed.returncode != 0:
        return None

    text = completed.stdout.lower()
    # Keep this tolerant: on Apple Silicon unified memory may not expose dedicated VRAM.
    # A conservative value is sufficient for profile gating.
    if "spdisplays" in text:
        return 4
    return None
