from datetime import datetime
import logging
import os
import psutil
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ResourcePolicy:
    cpu_threshold: float = 0.85
    memory_threshold: float = 0.85
    wasmem_threshold: float = 0.9


@dataclass
class ResourceState:
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    swap_percent: float = 0.0


class ResourceScheduler:
    """Governs resource allocation and triggers mitigation strategies."""

    CGROUP_CPU_MAX = "/sys/fs/cgroup/cpu.max"
    CGROUP_MEMORY_MAX = "/sys/fs/cgroup/memory.max"
    CGROUP_IO_MAX = "/sys/fs/cgroup/io.max"
    THROTTLE_REACTION_MS = 500
    IDLE_TIMEOUT_S = 90
    RAM_PRESSURE_THRESHOLD = 0.85

    def __init__(self, policy: Optional[ResourcePolicy] = None, cgroup_base_path: Optional[str] = None):
        self.policy = policy or ResourcePolicy()
        self.state = ResourceState()
        self.last_throttle_time = None
        self.cgroup_base_path = cgroup_base_path or "/sys/fs/cgroup"
        self.decision_history: List[Dict[str, Any]] = []
        self.latency_history: List[float] = []
        self.cgroup_enabled = os.path.exists(self.cgroup_base_path)

    def collect(self) -> ResourceState:
        self.state.cpu_percent = psutil.cpu_percent(interval=0.1) / 100.0
        self.state.memory_percent = psutil.virtual_memory().percent / 100.0
        self.state.swap_percent = psutil.swap_memory().percent / 100.0
        logger.debug("Resource state: %s", self.state)
        return self.state

    def should_throttle(self) -> bool:
        self.collect()
        result = (
            self.state.cpu_percent >= self.policy.cpu_threshold
            or self.state.memory_percent >= self.policy.memory_threshold
            or self.state.swap_percent >= self.policy.wasmem_threshold
        )
        logger.info("Throttle decision: %s", result)
        return result

    def monitor(self) -> Dict[str, Any]:
        state = self.collect()
        throttle = self.should_throttle()
        if self.state.memory_percent >= self.RAM_PRESSURE_THRESHOLD:
            self.handle_memory_pressure()

        return {
            "cpu_percent": state.cpu_percent,
            "memory_percent": state.memory_percent,
            "swap_percent": state.swap_percent,
            "throttle": throttle,
        }

    def yield_llm_resources(self) -> Dict[str, Any]:
        # callback for LLM process to yield resources quickly under pressure
        decision = self.schedule_yield()
        return decision

    def restore_llm_resources(self) -> Dict[str, Any]:
        if not self.should_throttle():
            self.release_cgroup_throttle()
        return self.get_metrics()

    def handle_memory_pressure(self) -> None:
        logger.warning("Memory pressure detected: %s", self.state.memory_percent)
        self.enforce_cgroup_throttle()

    def _write_cgroup_file(self, filename: str, value: str) -> None:
        path = os.path.join(self.cgroup_base_path, filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(value)
            logger.info("Wrote %s=%s", path, value)
        except (PermissionError, FileNotFoundError, OSError) as exc:
            logger.warning("Unable to write cgroup file %s: %s", path, exc)

    def _has_cgroup_file(self, filename: str) -> bool:
        return os.path.exists(os.path.join(self.cgroup_base_path, filename))

    def enforce_cgroup_throttle(self) -> None:
        # Use explicit cgroup v2 configuration where available.
        if not self.cgroup_enabled:
            logger.warning("Cgroup path unavailable, skipping enforcement")
            return

        if self._has_cgroup_file("cpu.max"):
            self._write_cgroup_file("cpu.max", "10000 100000")  # 10% limit
        else:
            logger.warning("cpu.max not found under %s", self.cgroup_base_path)

        if self._has_cgroup_file("memory.max"):
            self._write_cgroup_file("memory.max", "512M")
        else:
            logger.warning("memory.max not found under %s", self.cgroup_base_path)

        if self._has_cgroup_file("io.max"):
            self._write_cgroup_file("io.max", "8:0 rbps=1048576 wbps=1048576")
        else:
            logger.warning("io.max not found under %s", self.cgroup_base_path)

    def release_cgroup_throttle(self) -> None:
        self._write_cgroup_file("cpu.max", "max")
        self._write_cgroup_file("memory.max", "max")

    def schedule_yield(self) -> Dict[str, bool]:
        start_ts = datetime.now().timestamp()
        throttle = self.should_throttle()

        now = datetime.now().timestamp() * 1000
        if throttle and (self.last_throttle_time is None or now - self.last_throttle_time >= self.THROTTLE_REACTION_MS):
            logger.warning("Applying throttle mitigation (reaction window satisfied)")
            self.enforce_cgroup_throttle()
            self.last_throttle_time = now

        if not throttle and self.last_throttle_time is not None:
            self.release_cgroup_throttle()
            self.last_throttle_time = None

        decision = {
            "throttle": throttle,
            "reduce_provision": throttle and self.state.memory_percent > self.policy.memory_threshold,
            "pause_non_critical": throttle,
            "cgroup_path": self.cgroup_base_path,
            "cpu_percent": self.state.cpu_percent,
            "memory_percent": self.state.memory_percent,
            "swap_percent": self.state.swap_percent,
            "throttle_time_ms": self.last_throttle_time,
        }

        duration_ms = (datetime.now().timestamp() - start_ts) * 1000
        self.latency_history.append(duration_ms)
        self.decision_history.append({"timestamp": now, **decision, "latency_ms": duration_ms})

        logger.debug("Scheduler decision: %s", decision)
        return decision

    def get_metrics(self) -> Dict[str, Any]:
        latency = sorted(self.latency_history)
        p95 = latency[int(len(latency) * 0.95) - 1] if latency else 0
        return {
            "last_decision": self.decision_history[-1] if self.decision_history else {},
            "decision_count": len(self.decision_history),
            "latency_ms_p95": p95,
            "cpu_threshold": self.policy.cpu_threshold,
            "memory_threshold": self.policy.memory_threshold,
            "wasmem_threshold": self.policy.wasmem_threshold,
            "cgroup_enabled": self.cgroup_enabled,
        }

    def get_prometheus_metrics(self) -> str:
        metrics = self.get_metrics()
        labels = f'cgroup_enabled="{metrics["cgroup_enabled"]}"'
        return "\n".join(
            [
                f"aegis_resource_decision_count{{{labels}}} {metrics['decision_count']}",
                f"aegis_resource_latency_p95_ms{{{labels}}} {metrics['latency_ms_p95']}",
                f"aegis_resource_cpu_threshold{{{labels}}} {metrics['cpu_threshold']}",
                f"aegis_resource_memory_threshold{{{labels}}} {metrics['memory_threshold']}",
                f"aegis_resource_swap_threshold{{{labels}}} {metrics['wasmem_threshold']}",
            ]
        )

