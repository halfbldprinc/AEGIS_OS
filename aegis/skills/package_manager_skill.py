import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from ..result import SkillResult
from ..skill import Skill
from .action_schema import ActionSchema, ParamSpec


class PackageManagerSkill(Skill):
    name = "package_manager"
    tier = 1
    allowed_actions = {"resolve", "search", "install", "remove", "upgrade", "list_installed"}

    _PACKAGE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9+._-]{0,63}$")
    _ALIASES = {
        "vscode": "code",
        "visual-studio-code": "code",
        "python3": "python3",
        "docker": "docker.io",
        "nodejs": "nodejs",
        "git": "git",
    }

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action == "resolve":
            return self.resolve(params.get("package", ""))
        if action == "search":
            return self.search(params.get("package", ""), int(params.get("limit", 10)))
        if action == "install":
            return self.install(params.get("package", ""), bool(params.get("confirmed", False)))
        if action == "remove":
            return self.remove(params.get("package", ""), bool(params.get("confirmed", False)))
        if action == "upgrade":
            return self.upgrade(params.get("package", ""), bool(params.get("confirmed", False)))
        if action == "list_installed":
            return self.list_installed(int(params.get("limit", 100)))
        return SkillResult.fail(f"Unsupported action: {action}", error_code="UNSUPPORTED_ACTION")

    def get_permissions(self) -> List[str]:
        return ["package_query", "package_install", "package_remove", "package_upgrade"]

    def get_risk(self, action: str) -> str:
        if action in {"install", "remove", "upgrade"}:
            return "high"
        return "medium"

    def resolve(self, package: str) -> SkillResult:
        normalized = self._normalize_package(package)
        if not normalized:
            return SkillResult.fail("'package' parameter is required", error_code="MISSING_PACKAGE")

        backend = self._detect_backend()
        if backend is None:
            return SkillResult.fail("No supported package manager found", error_code="NO_PACKAGE_MANAGER")

        return SkillResult.ok(
            {
                "requested": package,
                "resolved": self._ALIASES.get(normalized, normalized),
                "backend": backend,
            }
        )

    def search(self, package: str, limit: int = 10) -> SkillResult:
        normalized = self._normalize_package(package)
        if not normalized:
            return SkillResult.fail("'package' parameter is required", error_code="MISSING_PACKAGE")
        backend = self._detect_backend()
        if backend is None:
            return SkillResult.fail("No supported package manager found", error_code="NO_PACKAGE_MANAGER")

        resolved = self._ALIASES.get(normalized, normalized)
        if backend == "apt":
            cmd = ["apt-cache", "search", resolved]
        elif backend == "dnf":
            cmd = ["dnf", "search", resolved]
        elif backend == "pacman":
            cmd = ["pacman", "-Ss", resolved]
        else:
            cmd = ["brew", "search", resolved]

        result = self._run(cmd, timeout=20)
        if not result.success:
            return result

        lines = [line.strip() for line in (result.data.get("stdout", "") or "").splitlines() if line.strip()]
        return SkillResult.ok(
            {
                "backend": backend,
                "requested": package,
                "resolved": resolved,
                "results": lines[: max(1, min(limit, 100))],
            }
        )

    def install(self, package: str, confirmed: bool) -> SkillResult:
        if not confirmed:
            return SkillResult.fail("Package install requires explicit approval", error_code="CONFIRMATION_REQUIRED")

        backend = self._detect_backend()
        if backend is None:
            return SkillResult.fail("No supported package manager found", error_code="NO_PACKAGE_MANAGER")

        normalized = self._normalize_package(package)
        if not normalized:
            return SkillResult.fail("'package' parameter is required", error_code="MISSING_PACKAGE")
        resolved = self._ALIASES.get(normalized, normalized)

        if backend == "apt":
            cmd = ["apt-get", "install", "-y", resolved]
        elif backend == "dnf":
            cmd = ["dnf", "install", "-y", resolved]
        elif backend == "pacman":
            cmd = ["pacman", "-S", "--noconfirm", resolved]
        else:
            cmd = ["brew", "install", resolved]

        result = self._run(self._with_privilege(cmd), timeout=600)
        if not result.success:
            return result
        return SkillResult.ok({"action": "install", "backend": backend, "package": resolved})

    def remove(self, package: str, confirmed: bool) -> SkillResult:
        if not confirmed:
            return SkillResult.fail("Package removal requires explicit approval", error_code="CONFIRMATION_REQUIRED")

        backend = self._detect_backend()
        if backend is None:
            return SkillResult.fail("No supported package manager found", error_code="NO_PACKAGE_MANAGER")

        normalized = self._normalize_package(package)
        if not normalized:
            return SkillResult.fail("'package' parameter is required", error_code="MISSING_PACKAGE")
        resolved = self._ALIASES.get(normalized, normalized)

        if backend == "apt":
            cmd = ["apt-get", "remove", "-y", resolved]
        elif backend == "dnf":
            cmd = ["dnf", "remove", "-y", resolved]
        elif backend == "pacman":
            cmd = ["pacman", "-R", "--noconfirm", resolved]
        else:
            cmd = ["brew", "uninstall", resolved]

        result = self._run(self._with_privilege(cmd), timeout=600)
        if not result.success:
            return result
        return SkillResult.ok({"action": "remove", "backend": backend, "package": resolved})

    def upgrade(self, package: Optional[str], confirmed: bool) -> SkillResult:
        if not confirmed:
            return SkillResult.fail("Package upgrade requires explicit approval", error_code="CONFIRMATION_REQUIRED")

        backend = self._detect_backend()
        if backend is None:
            return SkillResult.fail("No supported package manager found", error_code="NO_PACKAGE_MANAGER")

        package = self._normalize_package(package) if package else ""
        if package:
            resolved = self._ALIASES.get(package, package)
            if backend == "apt":
                cmd = ["apt-get", "install", "--only-upgrade", "-y", resolved]
            elif backend == "dnf":
                cmd = ["dnf", "upgrade", "-y", resolved]
            elif backend == "pacman":
                cmd = ["pacman", "-S", "--noconfirm", resolved]
            else:
                cmd = ["brew", "upgrade", resolved]
        else:
            resolved = "all"
            if backend == "apt":
                cmd = ["apt-get", "update", "&&", "apt-get", "upgrade", "-y"]
                # apt requires shell for chained update+upgrade; execute in two safe steps instead.
                update = self._run(self._with_privilege(["apt-get", "update"]), timeout=300)
                if not update.success:
                    return update
                cmd = ["apt-get", "upgrade", "-y"]
            elif backend == "dnf":
                cmd = ["dnf", "upgrade", "-y"]
            elif backend == "pacman":
                cmd = ["pacman", "-Syu", "--noconfirm"]
            else:
                cmd = ["brew", "upgrade"]

        result = self._run(self._with_privilege(cmd), timeout=1200)
        if not result.success:
            return result
        return SkillResult.ok({"action": "upgrade", "backend": backend, "package": resolved})

    def list_installed(self, limit: int = 100) -> SkillResult:
        backend = self._detect_backend()
        if backend is None:
            return SkillResult.fail("No supported package manager found", error_code="NO_PACKAGE_MANAGER")

        if backend == "apt":
            cmd = ["dpkg-query", "-W", "-f=${Package}\n"]
        elif backend == "dnf":
            cmd = ["dnf", "list", "installed"]
        elif backend == "pacman":
            cmd = ["pacman", "-Q"]
        else:
            cmd = ["brew", "list"]

        result = self._run(cmd, timeout=30)
        if not result.success:
            return result

        lines = [line.strip() for line in (result.data.get("stdout", "") or "").splitlines() if line.strip()]
        return SkillResult.ok({"backend": backend, "packages": lines[: max(1, min(limit, 1000))]})

    def get_action_schemas(self) -> Dict[str, ActionSchema]:
        package_spec = ParamSpec(
            "package",
            str,
            required=False,
            min_length=1,
            max_length=64,
            pattern=r"^[a-zA-Z0-9][a-zA-Z0-9+._-]{0,63}$",
        )
        return {
            "resolve": ActionSchema(params={"package": ParamSpec("package", str, required=True, min_length=1, max_length=64)}, allow_extra=False),
            "search": ActionSchema(
                params={
                    "package": ParamSpec("package", str, required=True, min_length=1, max_length=64),
                    "limit": ParamSpec("limit", int, required=False, min_value=1, max_value=100),
                },
                allow_extra=False,
            ),
            "install": ActionSchema(
                params={
                    "package": package_spec,
                    "confirmed": ParamSpec("confirmed", bool, required=False),
                },
                allow_extra=False,
            ),
            "remove": ActionSchema(
                params={
                    "package": package_spec,
                    "confirmed": ParamSpec("confirmed", bool, required=False),
                },
                allow_extra=False,
            ),
            "upgrade": ActionSchema(
                params={
                    "package": package_spec,
                    "confirmed": ParamSpec("confirmed", bool, required=False),
                },
                allow_extra=False,
            ),
            "list_installed": ActionSchema(
                params={
                    "limit": ParamSpec("limit", int, required=False, min_value=1, max_value=1000),
                },
                allow_extra=False,
            ),
        }

    def _normalize_package(self, package: Any) -> str:
        value = (str(package or "").strip().lower())
        if not value:
            return ""
        if not self._PACKAGE_PATTERN.fullmatch(value):
            return ""
        return value

    @staticmethod
    def _detect_backend() -> Optional[str]:
        if shutil.which("apt-get") and shutil.which("dpkg-query"):
            return "apt"
        if shutil.which("dnf"):
            return "dnf"
        if shutil.which("pacman"):
            return "pacman"
        if shutil.which("brew"):
            return "brew"
        return None

    @staticmethod
    def _with_privilege(cmd: List[str]) -> List[str]:
        if os.geteuid() == 0:
            return cmd
        sudo = shutil.which("sudo")
        if not sudo:
            return cmd
        return [sudo] + cmd

    @staticmethod
    def _run(cmd: List[str], timeout: int = 60) -> SkillResult:
        try:
            completed = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return SkillResult.fail(f"Command timed out: {exc}", error_code="COMMAND_TIMEOUT")
        except Exception as exc:
            return SkillResult.fail(str(exc), error_code="COMMAND_EXECUTION_ERROR")

        payload = {
            "command": cmd,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode != 0:
            return SkillResult.fail(payload.get("stderr") or "command failed", error_code="COMMAND_NONZERO_EXIT", data=payload)

        return SkillResult.ok(payload)
