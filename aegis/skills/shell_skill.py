import json
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from ..result import SkillResult
from ..skill import Skill
from .action_schema import ActionSchema, ParamSpec


class ShellSkill(Skill):
    name = "shell"
    tier = 2
    allowed_actions = {"run"}

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action != "run":
            return SkillResult.fail(f"Unsupported action: {action}", error_code="UNSUPPORTED_ACTION")

        command = params.get("command")
        if not command:
            return SkillResult.fail("'command' parameter is required", error_code="MISSING_COMMAND")

        cwd = params.get("cwd", ".")
        timeout = min(max(int(params.get("timeout", 30)), 1), 300)

        if not self._is_safe_cwd(cwd):
            return SkillResult.fail("Working directory is outside allowed boundaries", error_code="UNSAFE_CWD")

        if not self._is_command_allowed(command):
            return SkillResult.fail("Command blocked by whitelist policy", error_code="COMMAND_BLOCKED")

        try:
            completed = subprocess.run(
                shlex.split(command),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return SkillResult.fail(f"Command timed out: {exc}", error_code="COMMAND_TIMEOUT")
        except Exception as exc:
            return SkillResult.fail(str(exc), error_code="COMMAND_EXECUTION_ERROR")

        output = {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "command": command,
            "cwd": cwd,
        }

        if completed.returncode != 0:
            return SkillResult.fail(json.dumps(output, ensure_ascii=False), error_code="COMMAND_NONZERO_EXIT")

        return SkillResult.ok(output)

    def get_permissions(self) -> List[str]:
        return ["run"]

    def _is_command_allowed(self, command: str) -> bool:
        # Allowlist base command names for safety; can be updated for project needs.
        allowlist = {"ls", "cat", "echo", "pwd", "touch", "mkdir", "cp", "mv", "grep", "sed", "awk", "find"}
        parts = shlex.split(command) if command else []
        if not parts:
            return False
        cmd = parts[0]

        return cmd in allowlist

    def _is_safe_cwd(self, cwd: str) -> bool:
        try:
            target = Path(cwd).expanduser().resolve()
            base = Path.cwd().resolve()
            tmp = Path(tempfile.gettempdir()).resolve()
            return target == base or base in target.parents or target == tmp or tmp in target.parents
        except Exception:
            return False

    def get_action_schemas(self) -> Dict[str, ActionSchema]:
        return {
            "run": ActionSchema(
                params={
                    "command": ParamSpec("command", str, required=True, min_length=1, max_length=2000),
                    "cwd": ParamSpec("cwd", str, required=False, min_length=1, max_length=2048),
                    "timeout": ParamSpec("timeout", int, required=False, min_value=1, max_value=300),
                },
                allow_extra=True,
            )
        }
