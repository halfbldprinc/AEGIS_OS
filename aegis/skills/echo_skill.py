from typing import Dict, Any

from ..skill import Skill
from ..result import SkillResult


class EchoSkill(Skill):
    name = "echo"
    tier = 1

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action != "echo":
            return SkillResult.fail(f"Unsupported action: {action}")

        message = params.get("message")
        if message is None:
            return SkillResult.fail("Missing 'message' parameter")

        return SkillResult.ok({"echo": message})

    def get_permissions(self):
        return ["none"]
