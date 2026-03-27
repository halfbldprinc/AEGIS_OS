import json
import logging
import os
import secrets
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Dict, Any, List

from ..result import SkillResult
from .container_security import (
    DEFAULT_ALLOWED_IMAGES,
    generate_cgroup_config,
    generate_sbom,
    generate_seccomp_profile,
    inspect_repo_digests,
    verify_image_provenance,
    vulnerability_scan,
    allowed_images,
)

logger = logging.getLogger(__name__)


class ContainerRunner(Protocol):
    def run(
        self,
        skill_name: str,
        action: str,
        params: Dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> SkillResult:
        ...


@dataclass
class InProcessRunner:
    """Runner for in-process skills (tier 1)."""

    def run(
        self,
        skill: Any,
        action: str,
        params: Dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> SkillResult:
        logger.debug("InProcessRunner invoked for %s action %s", getattr(skill, 'name', 'unknown'), action)

        if not hasattr(skill, 'execute'):
            return SkillResult.fail("InProcessRunner: skill is not executable")

        if hasattr(skill, 'allowed_actions') and action not in getattr(skill, 'allowed_actions'):
            return SkillResult.fail(f"InProcessRunner: action '{action}' is not permitted")

        skill_timeout = None
        try:
            if hasattr(skill, "get_timeout"):
                skill_timeout = int(skill.get_timeout(action))
        except Exception:
            skill_timeout = None

        effective_timeout = skill_timeout if timeout_seconds is None else timeout_seconds
        if skill_timeout is not None and timeout_seconds is not None:
            effective_timeout = min(skill_timeout, timeout_seconds)

        if effective_timeout is None or effective_timeout <= 0:
            try:
                return skill.execute(action, params)
            except Exception as exc:
                return SkillResult.fail(str(exc))

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(skill.execute, action, params)
                return future.result(timeout=effective_timeout)
        except FuturesTimeoutError:
            return SkillResult.fail(f"Skill execution timed out after {effective_timeout}s")
        except Exception as exc:
            return SkillResult.fail(str(exc))


@dataclass
class ContainerizedRunner:
    """Concrete container runtime executor for tier 2 skills."""

    image_tag: str = "python:3.14-slim"
    memory_limit: str = "256m"
    cpu_quota: float = 0.5
    workdir: str = "/workspace"
    pids_limit: int = 128
    sandbox_root: str = "/tmp/aegis/sandbox"

    DEFAULT_ALLOWED_IMAGES = DEFAULT_ALLOWED_IMAGES

    def _allowed_images(self) -> set[str]:
        return allowed_images()

    def _prepare_sandbox_artifacts(self, skill_name: str) -> Dict[str, str]:
        sandbox_dir = Path(self.sandbox_root) / f"{skill_name}-{int(datetime.now(timezone.utc).timestamp())}-{secrets.token_hex(4)}"
        sandbox_dir.mkdir(parents=True, exist_ok=True)

        seccomp_profile = self.generate_seccomp_profile(skill_name)
        cgroup_config = self.generate_cgroup_config(skill_name)

        seccomp_path = sandbox_dir / "seccomp.json"
        cgroup_path = sandbox_dir / "cgroup.json"

        seccomp_path.write_text(json.dumps(seccomp_profile, indent=2), encoding="utf-8")
        cgroup_path.write_text(json.dumps(cgroup_config, indent=2), encoding="utf-8")

        return {
            "sandbox_dir": str(sandbox_dir),
            "seccomp_path": str(seccomp_path),
            "cgroup_path": str(cgroup_path),
        }

    def _cleanup_sandbox_artifacts(self, artifacts: Dict[str, str]) -> None:
        sandbox_dir = artifacts.get("sandbox_dir")
        if not sandbox_dir:
            return
        try:
            shutil.rmtree(sandbox_dir, ignore_errors=True)
        except Exception:
            logger.exception("Failed to clean sandbox artifacts at %s", sandbox_dir)

    def _detect_runtime(self) -> str:
        runtime = shutil.which("podman") or shutil.which("docker")
        if not runtime:
            raise RuntimeError("No supported container runtime (podman/docker) is available")
        return runtime

    def _build_command(self, runtime: str, skill_name: str, action: str, params: Dict[str, Any], seccomp_path: str) -> List[str]:
        params_json = json.dumps(params, ensure_ascii=False)

        mount_path = f"{os.getcwd()}:{self.workdir}:Z" if os.path.basename(runtime) == "podman" else f"{os.getcwd()}:{self.workdir}"

        return [
            runtime,
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            f"--pids-limit={self.pids_limit}",
            f"--memory={self.memory_limit}",
            f"--cpus={self.cpu_quota}",
            "--security-opt",
            "label=disable",
            "--security-opt",
            f"seccomp={seccomp_path}",
            "-v",
            mount_path,
            "-w",
            self.workdir,
            self.image_tag,
            "python",
            "-u",
            "-m",
            "aegis.orchestrator.container_skill_worker",
            "--skill",
            skill_name,
            "--action",
            action,
            "--params",
            params_json,
        ]

    def _inspect_repo_digests(self, runtime: str, image_tag: str) -> List[str]:
        return inspect_repo_digests(runtime, image_tag)

    def run(
        self,
        skill_name: str,
        action: str,
        params: Dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> SkillResult:
        runtime = self._detect_runtime()
        if not self.verify_image_provenance(self.image_tag):
            return SkillResult.fail(f"Container image provenance check failed for '{self.image_tag}'")

        scan = self.vulnerability_scan(self.image_tag)
        if scan.get("status") not in {"clean", "unknown"}:
            return SkillResult.fail(f"Container vulnerability scan failed for '{self.image_tag}'")

        artifacts = self._prepare_sandbox_artifacts(skill_name)
        cmd = self._build_command(runtime, skill_name, action, params, artifacts["seccomp_path"])

        logger.info("[ContainerRunner] Executing container command for %s: %s", skill_name, cmd)

        execution_timeout = 120
        if timeout_seconds is not None:
            execution_timeout = max(1, min(int(timeout_seconds), 600))

        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=execution_timeout)
        except subprocess.TimeoutExpired as exc:
            self._cleanup_sandbox_artifacts(artifacts)
            return SkillResult.fail(f"Container execution timed out: {exc}")
        finally:
            self._cleanup_sandbox_artifacts(artifacts)

        if completed.returncode != 0:
            logger.error("Container execution failed: stdout=%s stderr=%s", completed.stdout, completed.stderr)
            return SkillResult.fail(f"Container execution failed: {completed.stderr.strip()}")

        try:
            output = json.loads(completed.stdout.strip())
            if not isinstance(output, dict):
                raise ValueError("Unexpected worker output")
            if output.get("success"):
                return SkillResult.ok({"container": True, "skill": skill_name, "action": action, "result": output.get("data")})
            return SkillResult.fail(output.get("error", "Unknown error"))
        except json.JSONDecodeError:
            logger.error("Invalid JSON from container worker: %s", completed.stdout)
            return SkillResult.fail("Invalid JSON from container worker")

    def generate_seccomp_profile(self, skill_name: str) -> Dict[str, Any]:
        return generate_seccomp_profile(skill_name)

    def generate_cgroup_config(self, skill_name: str) -> Dict[str, Any]:
        return generate_cgroup_config(skill_name, self.pids_limit)

    def generate_sbom(self, image_tag: str) -> Dict[str, Any]:
        return generate_sbom(image_tag)

    def verify_image_provenance(self, image_tag: str) -> bool:
        return verify_image_provenance(
            image_tag=image_tag,
            inspect_digests_fn=self._inspect_repo_digests,
            allowed_images_set=self._allowed_images(),
        )

    def vulnerability_scan(self, image_tag: str) -> Dict[str, Any]:
        return vulnerability_scan(image_tag)


@dataclass
class PodmanContainerRunner(ContainerizedRunner):
    """Specific runner implementation that emulates Podman sandboxing policies."""

    allow_network: bool = False
    network_whitelist: List[str] = None
    data_volume: str = "/var/lib/aegis/skills/data"

    def __post_init__(self):
        if self.network_whitelist is None:
            self.network_whitelist = []

    def run(
        self,
        skill_name: str,
        action: str,
        params: Dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> SkillResult:
        logger.info("[PodmanContainerRunner] Running %s with network=%s", skill_name, self.allow_network)

        if not self.allow_network and self.network_whitelist:
            logger.debug("Network whitelist in effect: %s", self.network_whitelist)

        return super().run(skill_name, action, params, timeout_seconds=timeout_seconds)

