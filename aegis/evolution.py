import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .audit import AuditLog
from .training.eval import LocalEvaluator
from .utils.time import now_utc

logger = logging.getLogger(__name__)


@dataclass
class EvolutionProposal:
    proposal_id: str
    created_at: datetime
    metrics: Dict[str, Any]
    approved: bool = False
    applied: bool = False
    canary_percentage: float = 0.0
    audit_signoff_required: bool = False
    audit_signoff: bool = False


class EvolutionManager:
    """Tracks proposed model updates and gating consented evolution."""

    MAX_SNAPSHOTS = 4
    MAX_PERPLEXITY_DELTA = 0.15

    def __init__(self):
        self.proposals: Dict[str, EvolutionProposal] = {}
        self.adapter_snapshots: List[Dict[str, Any]] = []
        self.interaction_buffer: List[Dict[str, Any]] = []
        self.audit = AuditLog()
        self.evaluator_factory: Callable[[str], LocalEvaluator] = LocalEvaluator

    def create_proposal(
        self,
        proposal_id: str,
        metrics: Dict[str, Any],
        canary_percentage: float = 0.0,
        audit_signoff_required: bool = False,
    ) -> EvolutionProposal:
        if proposal_id in self.proposals:
            raise ValueError(f"Proposal already exists: {proposal_id}")
        if not (0 <= canary_percentage <= 100):
            raise ValueError("canary_percentage must be between 0 and 100")

        proposal = EvolutionProposal(
            proposal_id=proposal_id,
            created_at=now_utc(),
            metrics=metrics,
            canary_percentage=canary_percentage,
            audit_signoff_required=audit_signoff_required,
        )
        self.proposals[proposal_id] = proposal
        self.audit.record("evolution", "proposal_created", {"proposal_id": proposal_id, "metrics": metrics, "canary_percentage": canary_percentage, "audit_signoff_required": audit_signoff_required})
        logger.info("Created evolution proposal %s", proposal_id)
        return proposal

    def approve_proposal(self, proposal_id: str) -> EvolutionProposal:
        proposal = self._get_proposal(proposal_id)
        proposal.approved = True
        self.audit.record("evolution", "proposal_approved", {"proposal_id": proposal_id})
        logger.info("Approved evolution proposal %s", proposal_id)
        return proposal

    def apply_proposal(self, proposal_id: str) -> EvolutionProposal:
        proposal = self._get_proposal(proposal_id)
        if proposal.applied:
            raise ValueError("Proposal has already been applied")

        if not proposal.approved:
            raise ValueError("Proposal must be approved before application")

        if proposal.audit_signoff_required and not proposal.audit_signoff:
            raise ValueError("Proposal requires audit signoff before application")

        if self._is_partial_canary(proposal.canary_percentage) and not proposal.audit_signoff:
            raise ValueError("Canary deployment requires audit signoff")

        delta = self._extract_delta_perplexity(proposal)

        if delta > self.MAX_PERPLEXITY_DELTA:
            self.audit.record("evolution", "proposal_rejected", {"proposal_id": proposal_id, "delta_perplexity": delta})
            raise ValueError(f"Perplexity delta {delta:.3f} exceeds safety threshold {self.MAX_PERPLEXITY_DELTA:.3f}")

        if self._is_partial_canary(proposal.canary_percentage):
            self.audit.record("evolution", "proposal_canary", {"proposal_id": proposal_id, "canary_percentage": proposal.canary_percentage})
            logger.info("Applying canary deployment for proposal %s with %s%%", proposal_id, proposal.canary_percentage)

        self.persist_snapshot(proposal)

        proposal.applied = True
        self.audit.record("evolution", "proposal_applied", {"proposal_id": proposal_id, "delta_perplexity": delta, "canary_percentage": proposal.canary_percentage})
        logger.info("Applied evolution proposal %s", proposal_id)

        if not self.run_smoke_tests(proposal):
            self.rollback_last_snapshot()
            proposal.applied = False
            self.audit.record("evolution", "proposal_rollback", {"proposal_id": proposal_id})
            raise RuntimeError("Smoke tests failed after adapter apply; rolled back")

        return proposal

    def persist_snapshot(self, proposal: EvolutionProposal) -> None:
        snapshot = {
            "proposal_id": proposal.proposal_id,
            "timestamp": now_utc(),
            "metrics": proposal.metrics,
        }
        self.adapter_snapshots.append(snapshot)

        if len(self.adapter_snapshots) > self.MAX_SNAPSHOTS:
            self.adapter_snapshots.pop(0)

        self.audit.record("evolution", "snapshot_saved", snapshot)

    def run_smoke_tests(self, proposal: EvolutionProposal) -> bool:
        smoke_pass = proposal.metrics.get("smoke_passed")
        if isinstance(smoke_pass, bool):
            return smoke_pass

        benchmark_path = proposal.metrics.get("benchmark_path")
        if isinstance(benchmark_path, str) and benchmark_path.strip():
            model_name = str(proposal.metrics.get("model_name", "candidate-model"))
            min_eval_score = float(proposal.metrics.get("min_eval_score", 0.8))

            try:
                evaluator = self.evaluator_factory(benchmark_path)
                eval_result = evaluator.evaluate(model_name)
                score = float(eval_result.get("score", 0.0))
                total = int(eval_result.get("total", 0))
                passed = total > 0 and score >= min_eval_score
                self.audit.record(
                    "evolution",
                    "smoke_eval",
                    {
                        "proposal_id": proposal.proposal_id,
                        "model_name": model_name,
                        "benchmark_path": benchmark_path,
                        "score": score,
                        "total": total,
                        "min_eval_score": min_eval_score,
                        "passed": passed,
                    },
                )
                return passed
            except Exception as exc:
                self.audit.record(
                    "evolution",
                    "smoke_eval_error",
                    {
                        "proposal_id": proposal.proposal_id,
                        "benchmark_path": benchmark_path,
                        "error": str(exc),
                    },
                )
                return False

        # Fallback gate when smoke flag is unavailable.
        return proposal.metrics.get("delta_perplexity", 1.0) <= self.MAX_PERPLEXITY_DELTA

    def rollback_last_snapshot(self) -> None:
        if self.adapter_snapshots:
            popped = self.adapter_snapshots.pop()
            logger.warning("Rolled back adapter snapshot %s", popped.get("proposal_id"))

    def execute_proposal(self, proposal_id: str, canary_percentage: float = 100.0, audit_signoff: bool = False) -> EvolutionProposal:
        proposal = self._get_proposal(proposal_id)

        if proposal.applied:
            raise ValueError("Proposal has already been executed")

        if not (0 <= canary_percentage <= 100):
            raise ValueError("canary_percentage must be between 0 and 100")

        proposal.canary_percentage = canary_percentage
        proposal.audit_signoff = audit_signoff

        if not proposal.approved:
            raise ValueError("Proposal must be approved before execution")

        return self.apply_proposal(proposal_id)

    @staticmethod
    def _is_partial_canary(canary_percentage: float) -> bool:
        return 0 < canary_percentage < 100

    @staticmethod
    def _extract_delta_perplexity(proposal: EvolutionProposal) -> float:
        delta = proposal.metrics.get("delta_perplexity")
        if delta is None:
            raise ValueError("Proposal missing delta_perplexity metric")
        if not isinstance(delta, (int, float)):
            raise ValueError("delta_perplexity must be numeric")
        if not math.isfinite(float(delta)):
            raise ValueError("delta_perplexity must be finite")
        return float(delta)

    def enroll_interaction(self, user_input: str, action: str, success: bool) -> None:
        self.interaction_buffer.append({
            "timestamp": now_utc(),
            "user_input": user_input,
            "action": action,
            "success": success,
        })

    def summarize_interactions(self) -> Dict[str, Any]:
        return {
            "total": len(self.interaction_buffer),
            "success_rate": sum(1 for i in self.interaction_buffer if i["success"]) / max(1, len(self.interaction_buffer)),
        }

    def list_proposals(self) -> List[EvolutionProposal]:
        return list(self.proposals.values())

    def _get_proposal(self, proposal_id: str) -> EvolutionProposal:
        if proposal_id not in self.proposals:
            raise KeyError(f"Proposal not found: {proposal_id}")
        return self.proposals[proposal_id]
