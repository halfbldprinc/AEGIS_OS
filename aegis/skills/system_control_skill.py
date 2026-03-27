import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from ..result import SkillResult
from ..skill import Skill
from .action_schema import ActionSchema, ParamSpec


class SystemControlSkill(Skill):
    """Safe wrappers around system services and host connectivity toggles."""

    name = "system_control"
    tier = 1
    allowed_actions = {
        "service_status",
        "service_start",
        "service_stop",
        "service_restart",
        "wifi_status",
        "wifi_toggle",
        "bluetooth_status",
        "bluetooth_toggle",
    }

    _SERVICE_PATTERN = re.compile(r"^[a-zA-Z0-9_.@-]{1,128}$")

    def __init__(self):
        raw_allowlist = os.getenv(
            "AEGIS_SERVICE_ALLOWLIST",
            "aegis-api.service,aegis-agent.service,aegis-onboarding.service",
        )
        self._service_allowlist = {
            item.strip() for item in raw_allowlist.split(",") if item.strip()
        }

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action == "service_status":
            return self.service_status(params.get("service", ""))
        if action == "service_start":
            return self.service_start(params.get("service", ""), bool(params.get("confirmed", False)))
        if action == "service_stop":
            return self.service_stop(params.get("service", ""), bool(params.get("confirmed", False)))
        if action == "service_restart":
            return self.service_restart(params.get("service", ""), bool(params.get("confirmed", False)))
        if action == "wifi_status":
            return self.wifi_status()
        if action == "wifi_toggle":
            return self.wifi_toggle(bool(params.get("enabled", False)), bool(params.get("confirmed", False)))
        if action == "bluetooth_status":
            return self.bluetooth_status()
        if action == "bluetooth_toggle":
            return self.bluetooth_toggle(bool(params.get("enabled", False)), bool(params.get("confirmed", False)))
        return SkillResult.fail(f"Unsupported action: {action}", error_code="UNSUPPORTED_ACTION")

    def get_permissions(self) -> List[str]:
        return ["service_manage", "network_manage"]

    def get_risk(self, action: str) -> str:
        if action in {"service_start", "service_stop", "service_restart", "wifi_toggle", "bluetooth_toggle"}:
            return "high"
        return "medium"

    def _normalize_service(self, service: str) -> Optional[str]:
        value = (service or "").strip()
        if not value or not self._SERVICE_PATTERN.match(value):
            return None
        return value

    def _check_service_allowed(self, service: str) -> Optional[SkillResult]:
        if service not in self._service_allowlist:
            return SkillResult.fail(
                f"Service '{service}' not in allowlist",
                error_code="SERVICE_NOT_ALLOWED",
            )
        return None

    @staticmethod
    def _run(cmd: List[str], timeout: int = 20) -> SkillResult:
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return SkillResult.fail(f"Command timed out: {exc}", error_code="COMMAND_TIMEOUT")
        except FileNotFoundError:
            return SkillResult.fail(f"Command not found: {cmd[0]}", error_code="COMMAND_NOT_FOUND")
        except Exception as exc:
            return SkillResult.fail(str(exc), error_code="COMMAND_EXECUTION_ERROR")

        payload = {
            "command": cmd,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode != 0:
            return SkillResult.fail(str(payload), error_code="COMMAND_NONZERO_EXIT")
        return SkillResult.ok(payload)

    def service_status(self, service: str) -> SkillResult:
        normalized = self._normalize_service(service)
        if not normalized:
            return SkillResult.fail("'service' parameter is invalid", error_code="INVALID_SERVICE")

        policy_error = self._check_service_allowed(normalized)
        if policy_error is not None:
            return policy_error

        if shutil.which("systemctl") is None:
            return SkillResult.fail("systemctl is not available", error_code="SYSTEMCTL_UNAVAILABLE")

        return self._run(["systemctl", "status", normalized, "--no-pager"], timeout=20)

    def _service_mutation(self, operation: str, service: str, confirmed: bool) -> SkillResult:
        if not confirmed:
            return SkillResult.fail(
                f"Service {operation} requires explicit approval",
                error_code="CONFIRMATION_REQUIRED",
            )

        normalized = self._normalize_service(service)
        if not normalized:
            return SkillResult.fail("'service' parameter is invalid", error_code="INVALID_SERVICE")

        policy_error = self._check_service_allowed(normalized)
        if policy_error is not None:
            return policy_error

        if shutil.which("systemctl") is None:
            return SkillResult.fail("systemctl is not available", error_code="SYSTEMCTL_UNAVAILABLE")

        return self._run(["systemctl", operation, normalized], timeout=30)

    def service_start(self, service: str, confirmed: bool) -> SkillResult:
        return self._service_mutation("start", service, confirmed)

    def service_stop(self, service: str, confirmed: bool) -> SkillResult:
        return self._service_mutation("stop", service, confirmed)

    def service_restart(self, service: str, confirmed: bool) -> SkillResult:
        return self._service_mutation("restart", service, confirmed)

    def wifi_status(self) -> SkillResult:
        if shutil.which("nmcli") is None:
            return SkillResult.fail("nmcli is not available", error_code="NMCLI_UNAVAILABLE")

        result = self._run(["nmcli", "radio", "wifi"], timeout=10)
        if not result.success:
            return result
        state = (result.data.get("stdout", "") or "").strip().lower()
        return SkillResult.ok({"wifi_enabled": state == "enabled", "raw": state})

    def wifi_toggle(self, enabled: bool, confirmed: bool) -> SkillResult:
        if not confirmed:
            return SkillResult.fail("WiFi toggle requires explicit approval", error_code="CONFIRMATION_REQUIRED")
        if shutil.which("nmcli") is None:
            return SkillResult.fail("nmcli is not available", error_code="NMCLI_UNAVAILABLE")
        desired = "on" if enabled else "off"
        return self._run(["nmcli", "radio", "wifi", desired], timeout=15)

    def bluetooth_status(self) -> SkillResult:
        if shutil.which("nmcli") is not None:
            result = self._run(["nmcli", "radio", "bluetooth"], timeout=10)
            if result.success:
                state = (result.data.get("stdout", "") or "").strip().lower()
                return SkillResult.ok({"bluetooth_enabled": state == "enabled", "raw": state})

        if shutil.which("bluetoothctl") is None:
            return SkillResult.fail("No bluetooth backend available", error_code="BLUETOOTH_UNAVAILABLE")

        result = self._run(["bluetoothctl", "show"], timeout=10)
        if not result.success:
            return result
        text = (result.data.get("stdout", "") or "").lower()
        return SkillResult.ok({"bluetooth_enabled": "powered: yes" in text, "raw": text})

    def bluetooth_toggle(self, enabled: bool, confirmed: bool) -> SkillResult:
        if not confirmed:
            return SkillResult.fail("Bluetooth toggle requires explicit approval", error_code="CONFIRMATION_REQUIRED")

        if shutil.which("nmcli") is not None:
            desired = "on" if enabled else "off"
            return self._run(["nmcli", "radio", "bluetooth", desired], timeout=15)

        if shutil.which("bluetoothctl") is None:
            return SkillResult.fail("No bluetooth backend available", error_code="BLUETOOTH_UNAVAILABLE")

        desired = "on" if enabled else "off"
        return self._run(["bluetoothctl", "power", desired], timeout=15)

    def get_action_schemas(self) -> Dict[str, ActionSchema]:
        return {
            "service_status": ActionSchema(
                params={
                    "service": ParamSpec("service", str, required=True, min_length=1, max_length=128),
                },
                allow_extra=False,
            ),
            "service_start": ActionSchema(
                params={
                    "service": ParamSpec("service", str, required=True, min_length=1, max_length=128),
                    "confirmed": ParamSpec("confirmed", bool, required=False),
                },
                allow_extra=False,
            ),
            "service_stop": ActionSchema(
                params={
                    "service": ParamSpec("service", str, required=True, min_length=1, max_length=128),
                    "confirmed": ParamSpec("confirmed", bool, required=False),
                },
                allow_extra=False,
            ),
            "service_restart": ActionSchema(
                params={
                    "service": ParamSpec("service", str, required=True, min_length=1, max_length=128),
                    "confirmed": ParamSpec("confirmed", bool, required=False),
                },
                allow_extra=False,
            ),
            "wifi_status": ActionSchema(params={}, allow_extra=False),
            "wifi_toggle": ActionSchema(
                params={
                    "enabled": ParamSpec("enabled", bool, required=True),
                    "confirmed": ParamSpec("confirmed", bool, required=False),
                },
                allow_extra=False,
            ),
            "bluetooth_status": ActionSchema(params={}, allow_extra=False),
            "bluetooth_toggle": ActionSchema(
                params={
                    "enabled": ParamSpec("enabled", bool, required=True),
                    "confirmed": ParamSpec("confirmed", bool, required=False),
                },
                allow_extra=False,
            ),
        }
