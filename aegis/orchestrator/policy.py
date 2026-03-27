import json
import os
from dataclasses import dataclass
from typing import Protocol, Dict, Any, Mapping, Iterable

from ..trust_ledger import TrustLedger

@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""


class ExecutionPolicy(Protocol):
    def evaluate(self, skill_name: str, action: str, params: Dict[str, Any], trust_ledger: TrustLedger) -> PolicyDecision:
        ...


class DefaultExecutionPolicy:
    """Default policy for skill execution.

    Implements a conservative posture:
      - If the skill has a lock in the trust ledger and is currently locked, deny execution
      - Otherwise allow
    """

    def __init__(
        self,
        enforce_action_allowlist: bool | None = None,
        allowlist: Mapping[str, Iterable[str]] | None = None,
        profile: str | None = None,
    ):
        if enforce_action_allowlist is None:
            enforce_action_allowlist = os.getenv("AEGIS_ENFORCE_ACTION_ALLOWLIST", "0").lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        self.enforce_action_allowlist = enforce_action_allowlist
        self.allowlist = self._load_allowlist(allowlist)
        self.profile = self._normalize_profile(profile or os.getenv("AEGIS_POLICY_PROFILE", "balanced"))

    PROFILE_DENY_RULES: Dict[str, Dict[str, set[str]]] = {
        "open": {},
        "balanced": {
            "shell": {"run"},
            "package_manager": {"remove", "upgrade"},
        },
        "strict": {
            "shell": {"run"},
            "os_control": {"launch", "close", "focus", "clipboard_set"},
            "settings": {"volume", "brightness", "dnd", "network"},
            "package_manager": {"install", "remove", "upgrade"},
        },
    }

    @classmethod
    def _normalize_profile(cls, profile: str) -> str:
        value = (profile or "balanced").strip().lower()
        if value not in cls.PROFILE_DENY_RULES:
            return "balanced"
        return value

    def set_profile(self, profile: str) -> str:
        self.profile = self._normalize_profile(profile)
        return self.profile

    def get_profile(self) -> Dict[str, Any]:
        rules = self.PROFILE_DENY_RULES.get(self.profile, {})
        serialized_rules = {skill: sorted(actions) for skill, actions in rules.items()}
        return {
            "profile": self.profile,
            "deny_rules": serialized_rules,
            "allowlist_enforced": self.enforce_action_allowlist,
        }

    def _is_denied_by_profile(self, skill_name: str, action: str) -> bool:
        rules = self.PROFILE_DENY_RULES.get(self.profile, {})
        denied_actions = rules.get(skill_name, set())
        return action in denied_actions or "all" in denied_actions

    @staticmethod
    def _load_allowlist(allowlist: Mapping[str, Iterable[str]] | None) -> Dict[str, set[str]]:
        if allowlist is None:
            raw = os.getenv("AEGIS_ACTION_ALLOWLIST", "").strip()
            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            if not isinstance(parsed, dict):
                return {}
            allowlist = parsed

        out: Dict[str, set[str]] = {}
        for skill, actions in allowlist.items():
            if isinstance(actions, str):
                out[str(skill)] = {actions}
                continue
            out[str(skill)] = {str(action) for action in actions}
        return out

    def _is_allowed_by_allowlist(self, skill_name: str, action: str) -> bool:
        allowed_actions = self.allowlist.get(skill_name)
        if not allowed_actions:
            return False
        return action in allowed_actions or "all" in allowed_actions

    def evaluate(self, skill_name: str, action: str, params: Dict[str, Any], trust_ledger: TrustLedger) -> PolicyDecision:
        history_exists = skill_name in trust_ledger.records
        if history_exists and not trust_ledger.is_unlocked(skill_name):
            return PolicyDecision(False, f"skill '{skill_name}' blocked by trust ledger")

        if self._is_denied_by_profile(skill_name, action) and not params.get("confirmed", False):
            return PolicyDecision(
                False,
                f"skill '{skill_name}' action '{action}' blocked by policy profile '{self.profile}'",
            )

        if self.enforce_action_allowlist:
            if params.get("confirmed", False):
                return PolicyDecision(True, "allowed_by_confirmation")
            if not self._is_allowed_by_allowlist(skill_name, action):
                return PolicyDecision(False, f"skill '{skill_name}' action '{action}' blocked by allowlist")

        return PolicyDecision(True, "allowed")


class CostBudgetPolicy:
    """Enforces per-plan and per-step cost limits."""

    def __init__(self, max_step_cost: float = 10.0, max_plan_cost: float = 100.0):
        self.max_step_cost = max_step_cost
        self.max_plan_cost = max_plan_cost

    def evaluate(self, skill_name: str, action: str, params: Dict[str, Any], trust_ledger: TrustLedger) -> PolicyDecision:
        estimated_cost = float(params.get("estimated_cost", 0.0))
        if estimated_cost > self.max_step_cost:
            return PolicyDecision(False, f"estimated step cost {estimated_cost} exceeds max {self.max_step_cost}")

        plan_cost = float(params.get("plan_cost", 0.0))
        if plan_cost > self.max_plan_cost:
            return PolicyDecision(False, f"plan cost {plan_cost} exceeds max {self.max_plan_cost}")

        return PolicyDecision(True, "allowed")
