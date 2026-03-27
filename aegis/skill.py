from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from .result import SkillResult
from .skills.action_schema import ActionSchema

class Skill(ABC):
    """Base class for all skills."""

    name: str
    tier: int = 2  # 1=in-process, 2=container+network, 3=container+airgapped

    @abstractmethod
    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        """Run the skill action and return SkillResult."""

    @abstractmethod
    def get_permissions(self) -> List[str]:
        """Describe required permissions for this skill."""

    def get_timeout(self, action: str) -> int:
        """Optional override: action-specific timeout in seconds."""
        return 30

    def get_risk(self, action: str) -> str:
        """Risk level of an action for permission enforcement."""
        return "low"

    def on_plan_abort(self) -> None:
        """Optional cleanup if the plan is aborted mid-flight."""
        return

    def get_action_schemas(self) -> Dict[str, ActionSchema]:
        """Optional per-action parameter schema map."""
        return {}
