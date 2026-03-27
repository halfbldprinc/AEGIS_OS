from dataclasses import dataclass
from typing import Protocol, Dict, Any

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

    def evaluate(self, skill_name: str, action: str, params: Dict[str, Any], trust_ledger: TrustLedger) -> PolicyDecision:
        history_exists = skill_name in trust_ledger.records
        if history_exists and not trust_ledger.is_unlocked(skill_name):
            return PolicyDecision(False, f"skill '{skill_name}' blocked by trust ledger")

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
