from typing import Dict, Any, List

from ..skill import Skill
from ..result import SkillResult
from ..llm.runtime import LLMRuntime, LLMUnavailableError


class LLMSkill(Skill):
    name = "llm"
    tier = 1

    def __init__(self, llm_runtime: LLMRuntime | None = None):
        self.llm_runtime = llm_runtime or LLMRuntime()

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action != "reason":
            return SkillResult.fail(f"Unsupported action: {action}")

        messages = params.get("messages")
        if messages is None:
            return SkillResult.fail("Missing 'messages' parameter")

        try:
            output = self.llm_runtime.generate(messages, temperature=0.7, max_tokens=512)
            return SkillResult.ok({"response": output})
        except LLMUnavailableError as exc:
            return SkillResult.fail(f"LLM unavailable: {exc}")
        except Exception as exc:
            return SkillResult.fail(str(exc))

    def get_permissions(self) -> List[str]:
        return ["none"]
