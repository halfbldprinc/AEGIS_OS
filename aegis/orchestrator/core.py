from __future__ import annotations

import json
import importlib
import inspect
import logging
import os
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..utils.time import now_utc

from ..result import SkillResult
from ..skill import Skill
from ..trust_ledger import TrustLedger
from ..guardian import Guardian
from .policy import DefaultExecutionPolicy, ExecutionPolicy
from .container_runner import ContainerRunner, ContainerizedRunner, InProcessRunner, PodmanContainerRunner
from ..audit import AuditLog
from ..skills.registry import SkillRegistry
from ..skills.action_schema import SkillActionSchemaValidator


class UnsupportedHandleStrategy(ValueError):
    pass

logger = logging.getLogger(__name__)

@dataclass
class PlanStep:
    id: str
    skill_name: str
    action: str
    params: Dict[str, Any]
    status: str = "PENDING"
    result: Optional[SkillResult] = None
    timeout_seconds: int = 30
    max_retries: int = 0
    on_failure: str = "abort"  # abort | skip | fallback
    reversible: bool = False
    requires_confirmation: bool = False
    attempts: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    latency_ms: float = 0.0
    last_error: Optional[str] = None
    error_type: Optional[str] = None

    def update_result(self, result: SkillResult) -> None:
        self.result = result
        self.status = "SUCCEEDED" if result.success else "FAILED"


@dataclass
class Plan:
    id: str = field(default_factory=lambda: str(uuid4()))
    steps: List[PlanStep] = field(default_factory=list)
    status: str = "PENDING"
    created_at: datetime = field(default_factory=now_utc)
    completed_at: Optional[datetime] = None

    def register_rollback(self, step: PlanStep) -> None:
        # In a full implementation, we'd track reversible resources and roll them back.
        pass

    def rollback(self) -> None:
        for step in self.steps:
            if step.status == "SUCCEEDED" and step.reversible:
                # Rollback hook for completed reversible actions.
                AuditLog().record("orchestrator", "step_rollback", {"plan_id": self.id, "step_id": step.id})

    def add_step(self, skill_name: str, action: str, params: Dict[str, Any]) -> PlanStep:
        step = PlanStep(id=str(uuid4()), skill_name=skill_name, action=action, params=params)
        self.steps.append(step)
        return step

    def mark_running(self) -> None:
        self.status = "RUNNING"

    def mark_succeeded(self) -> None:
        self.status = "SUCCEEDED"
        self.completed_at = now_utc()

    def mark_failed(self) -> None:
        self.status = "FAILED"
        self.completed_at = now_utc()


class Orchestrator:
    """Central coordinator of plan execution and skill interactions."""

    SKILL_METADATA_PATH = os.getenv("AEGIS_SKILL_METADATA", "/etc/aegis/skills.json")
    AUTO_GRANT_SKILL_PERMISSIONS = os.getenv("AEGIS_AUTO_GRANT_SKILL_PERMISSIONS", "1").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    def __init__(
        self,
        trust_ledger: Optional[TrustLedger] = None,
        policy: Optional[ExecutionPolicy] = None,
        runner: Optional[ContainerRunner] = None,
        guardian: Optional[Guardian] = None,
        skill_metadata_path: Optional[str] = None,
    ):
        self.skills: Dict[str, Skill] = {}
        self.trust_ledger = trust_ledger or TrustLedger()
        self.policy: ExecutionPolicy = policy or DefaultExecutionPolicy()
        self.runner: ContainerRunner = runner or ContainerizedRunner()
        self.guardian = guardian or Guardian()
        self.registry = SkillRegistry(skill_metadata_path or self.SKILL_METADATA_PATH)
        self.audit_log = AuditLog()
        self.skill_metadata_path = skill_metadata_path or self.SKILL_METADATA_PATH
        self._inprocess_runner = InProcessRunner()
        self._container_runner = self.runner if isinstance(self.runner, ContainerizedRunner) else ContainerizedRunner()
        self._podman_runner = self.runner if isinstance(self.runner, PodmanContainerRunner) else PodmanContainerRunner(allow_network=False)
        self._schema_validator = SkillActionSchemaValidator()
        self._skill_action_telemetry = defaultdict(
            lambda: {
                "requests": 0,
                "successes": 0,
                "failures": 0,
                "denials": 0,
                "retries": 0,
                "total_latency_ms": 0.0,
                "latency_samples": 0,
                "error_codes": defaultdict(int),
            }
        )

    def _record_skill_action_telemetry(
        self,
        skill_name: str,
        action: str,
        status: str,
        latency_ms: Optional[float] = None,
        error_code: Optional[str] = None,
    ) -> None:
        key = f"{skill_name}:{action}"
        row = self._skill_action_telemetry[key]
        if status != "retry":
            row["requests"] += 1

        if status == "success":
            row["successes"] += 1
        elif status == "denied":
            row["denials"] += 1
        elif status == "retry":
            row["retries"] += 1
        else:
            row["failures"] += 1

        if latency_ms is not None:
            row["total_latency_ms"] += float(latency_ms)
            row["latency_samples"] += 1

        if error_code:
            row["error_codes"][error_code] += 1

    def get_skill_action_telemetry(self) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {}
        for key, row in self._skill_action_telemetry.items():
            samples = int(row["latency_samples"])
            snapshot[key] = {
                "requests": int(row["requests"]),
                "successes": int(row["successes"]),
                "failures": int(row["failures"]),
                "denials": int(row["denials"]),
                "retries": int(row["retries"]),
                "avg_latency_ms": float(row["total_latency_ms"] / samples) if samples else 0.0,
                "error_codes": dict(row["error_codes"]),
            }
        return snapshot

    def _deny_step(
        self,
        plan: Plan,
        step: PlanStep,
        reason: str,
        allow_failure: bool,
        plan_reason: str,
        error_code: str,
    ) -> Optional[Plan]:
        logger.warning("Step %s denied: %s", step.id, reason)
        step.status = "DENIED"
        step.result = SkillResult.fail(reason, error_code=error_code)
        step.last_error = reason
        step.error_type = "denied"
        self._record_skill_action_telemetry(step.skill_name, step.action, "denied", error_code=error_code)
        self.audit_log.record(
            "orchestrator",
            "step_denied",
            {
                "plan_id": plan.id,
                "step_id": step.id,
                "skill": step.skill_name,
                "action": step.action,
                "reason": reason,
                "error_code": error_code,
            },
        )
        if not allow_failure:
            plan.mark_failed()
            self.audit_log.record("orchestrator", "plan_failed", {"plan_id": plan.id, "reason": plan_reason})
            return plan
        return None

    def _is_transient_error(self, error: str) -> bool:
        normalized = (error or "").lower()
        transient_markers = (
            "timeout",
            "timed out",
            "temporarily",
            "unavailable",
            "rate limit",
            "connection reset",
            "connection refused",
            "service unavailable",
        )
        return any(marker in normalized for marker in transient_markers)

    def _retry_delay_seconds(self, attempt: int, base: float) -> float:
        jitter = random.uniform(0.0, 0.1)
        return max(0.0, base * (2 ** max(0, attempt - 1)) + jitter)

    def _validate_plan_before_execution(self, plan: Plan) -> Optional[str]:
        if not plan.steps:
            return "plan has no steps"

        for step in plan.steps:
            if not step.skill_name or not step.action:
                return f"invalid step payload for step '{step.id}'"
            if not isinstance(step.params, dict):
                return f"step '{step.id}' params must be an object"
            if step.skill_name not in self.skills:
                return f"skill '{step.skill_name}' not registered"

            skill = self.skills[step.skill_name]
            allowed_actions = getattr(skill, "allowed_actions", None)
            if allowed_actions and step.action not in allowed_actions:
                return f"action '{step.action}' not allowed for skill '{step.skill_name}'"

            if step.timeout_seconds <= 0:
                return f"step '{step.id}' has invalid timeout_seconds"
            if step.max_retries < 0:
                return f"step '{step.id}' has invalid max_retries"
            if step.on_failure not in {"abort", "skip", "fallback"}:
                return f"step '{step.id}' has invalid on_failure strategy '{step.on_failure}'"

        return None

    def _dispatch_step(self, step: PlanStep, skill: Skill) -> SkillResult:
        if not self.registry.verify_signature(skill.name, getattr(skill, "signature", None)):
            raise PermissionError("Skill signature verification failed")

        if skill.tier == 1:
            return self._run_runner_with_optional_timeout(
                self._inprocess_runner,
                skill,
                step.action,
                step.params,
                step.timeout_seconds,
            )

        if skill.tier == 2:
            logger.info("Dispatching %s to container runner (tier=%s)", step.skill_name, skill.tier)
            if hasattr(self._container_runner, "allow_network"):
                try:
                    self._container_runner.allow_network = "network" in (skill.get_permissions() or []) and self.guardian.check(skill.name, "network")
                except Exception:
                    pass
            return self._run_runner_with_optional_timeout(
                self._container_runner,
                step.skill_name,
                step.action,
                step.params,
                step.timeout_seconds,
            )

        if skill.tier == 3:
            logger.info("Dispatching %s to podman runner (tier=3)", step.skill_name)
            self._podman_runner.allow_network = False
            return self._run_runner_with_optional_timeout(
                self._podman_runner,
                step.skill_name,
                step.action,
                step.params,
                step.timeout_seconds,
            )

        return SkillResult.fail(f"Unknown skill tier {skill.tier}")

    @staticmethod
    def _run_runner_with_optional_timeout(
        runner: Any,
        skill_or_name: Any,
        action: str,
        params: Dict[str, Any],
        timeout_seconds: int,
    ) -> SkillResult:
        run_method = getattr(runner, "run")
        try:
            signature = inspect.signature(run_method)
            supports_timeout = "timeout_seconds" in signature.parameters
            supports_kwargs = any(
                p.kind is inspect.Parameter.VAR_KEYWORD
                for p in signature.parameters.values()
            )
        except (TypeError, ValueError):
            supports_timeout = True
            supports_kwargs = False

        if supports_timeout or supports_kwargs:
            try:
                return run_method(skill_or_name, action, params, timeout_seconds=timeout_seconds)
            except TypeError as exc:
                # Backward compatibility for older/custom runners that don't support timeout_seconds.
                logger.debug("Runner timeout fallback activated for %s: %s", runner.__class__.__name__, exc)
                return run_method(skill_or_name, action, params)

        return run_method(skill_or_name, action, params)

    def load_skill_plugins(self, plugin_manifest_path: str | None = None) -> None:
        path = plugin_manifest_path or os.getenv("AEGIS_PLUGIN_MANIFEST", "/etc/aegis/skill_plugins.json")
        if not path or not os.path.isfile(path):
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                plugins = json.load(f)
        except Exception:
            logger.warning("Failed to load skill plugin manifest from %s", path)
            return

        for plugin in plugins:
            module_name = plugin.get("module")
            class_name = plugin.get("class")
            skill_name = plugin.get("name")
            if not module_name or not class_name or not skill_name:
                continue
            if skill_name in self.skills:
                continue
            try:
                module = importlib.import_module(module_name)
                cls = getattr(module, class_name)
                skill = cls()
                self.register_skill(skill)
                logger.info("Loaded plugin skill %s from %s", skill_name, module_name)
            except Exception as exc:
                logger.warning("Failed to load skill plugin %s: %s", skill_name, exc)

    def register_skill(self, skill: Skill) -> None:
        if skill.name in self.skills:
            raise ValueError(f"Skill with name {skill.name} already registered")

        self.skills[skill.name] = skill
        logger.debug("Registered skill: %s", skill.name)

        self.registry.register(skill.name, getattr(skill, "tier", 2), skill.get_permissions())
        self._write_skill_metadata(skill)

        # Tier-specific execution capabilities are required by orchestrator policy.
        if getattr(skill, "tier", 2) == 2:
            self.guardian.grant(skill.name, "container")
        elif getattr(skill, "tier", 2) == 3:
            self.guardian.grant(skill.name, "airgapped")

        if not self.AUTO_GRANT_SKILL_PERMISSIONS:
            return

        # Backward-compatible dev mode: auto grant declared permissions.
        skill_permissions = skill.get_permissions() or []
        if not skill_permissions:
            self.guardian.grant(skill.name, "all")
            return

        for permission in skill_permissions:
            if permission in ("all", "none"):
                self.guardian.grant(skill.name, "all")
            else:
                self.guardian.grant(skill.name, permission)

    def get_skill(self, name: str) -> Skill:
        if name not in self.skills:
            raise KeyError(f"Skill not found: {name}")
        return self.skills[name]

    def list_skills(self) -> List[Dict[str, Any]]:
        return [{
            "name": s.name,
            "tier": getattr(s, "tier", 2),
            "permissions": s.get_permissions(),
        } for s in self.skills.values()]

    def _write_skill_metadata(self, skill: Skill) -> None:
        record = {
            "name": skill.name,
            "tier": getattr(skill, "tier", 2),
            "permissions": skill.get_permissions(),
            "registered_at": now_utc().isoformat(),
        }

        existing = {}
        if os.path.exists(self.skill_metadata_path):
            try:
                with open(self.skill_metadata_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}

        existing[skill.name] = record

        path_dir = os.path.dirname(self.skill_metadata_path)
        if path_dir:
            try:
                os.makedirs(path_dir, exist_ok=True)
            except PermissionError:
                fallback = os.path.join("/tmp", "aegis_skills")
                os.makedirs(fallback, exist_ok=True)
                self.skill_metadata_path = os.path.join(fallback, "skills.json")

        temp_path = f"{self.skill_metadata_path}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
            os.replace(temp_path, self.skill_metadata_path)
        except PermissionError:
            logger.warning("Cannot write skill metadata to %s, skipping", self.skill_metadata_path)
        except Exception as exc:
            logger.warning("Failed writing skill metadata to %s: %s", self.skill_metadata_path, exc)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass

    def execute_plan(self, plan: Plan, allow_failure: bool = False) -> Plan:
        validation_error = self._validate_plan_before_execution(plan)
        if validation_error:
            plan.mark_failed()
            self.audit_log.record("orchestrator", "plan_failed", {"plan_id": plan.id, "reason": validation_error})
            if plan.steps:
                plan.steps[0].status = "DENIED"
                plan.steps[0].result = SkillResult.fail(validation_error)
                plan.steps[0].last_error = validation_error
                plan.steps[0].error_type = "validation"
            return plan

        plan.mark_running()
        self.audit_log.record("orchestrator", "plan_started", {"plan_id": plan.id, "steps": len(plan.steps)})

        for step in plan.steps:
            skill = self.get_skill(step.skill_name)

            if step.requires_confirmation and not step.params.get("confirmed", False):
                reason = f"step '{step.skill_name}.{step.action}' requires confirmation"
                denied_plan = self._deny_step(
                    plan,
                    step,
                    reason,
                    allow_failure,
                    "requires_confirmation",
                    "REQUIRES_CONFIRMATION",
                )
                if denied_plan is not None:
                    return denied_plan
                continue

            schemas = skill.get_action_schemas()
            schema_error = self._schema_validator.validate(step.action, step.params, schemas.get(step.action))
            if schema_error:
                denied_plan = self._deny_step(
                    plan,
                    step,
                    schema_error.message,
                    allow_failure,
                    "invalid_params",
                    schema_error.error_code,
                )
                if denied_plan is not None:
                    return denied_plan
                continue

            step.started_at = now_utc()
            step_start_perf = time.perf_counter()
            allowed_actions = getattr(skill, "allowed_actions", None)
            if allowed_actions and step.action not in allowed_actions:
                reason = f"action '{step.action}' not allowed for skill '{step.skill_name}'"
                denied_plan = self._deny_step(plan, step, reason, allow_failure, "invalid_action", "INVALID_ACTION")
                if denied_plan is not None:
                    return denied_plan
                continue

            if self.trust_ledger:
                # Only enforce lock once we have an established category history.
                # This allows initial safe onboarding of first actions.
                has_history = step.skill_name in self.trust_ledger.records
                _ = has_history and not self.trust_ledger.is_unlocked(step.skill_name)

            # Guardian-capability check first: skill/action must be explicitly permitted.
            if not self.guardian.check(step.skill_name, step.action):
                reason = f"skill '{step.skill_name}' action '{step.action}' denied by guardian"
                denied_plan = self._deny_step(plan, step, reason, allow_failure, "guardian_denied", "GUARDIAN_DENIED")
                if denied_plan is not None:
                    return denied_plan
                continue

            decision = self.policy.evaluate(step.skill_name, step.action, step.params, self.trust_ledger)
            if not decision.allowed:
                denied_plan = self._deny_step(plan, step, decision.reason, allow_failure, "policy_denied", "POLICY_DENIED")
                if denied_plan is not None:
                    return denied_plan
                continue

            # Enforce configured sandboxing policy by tier.
            if skill.tier == 2:
                if not self.guardian.check(skill.name, "container"):
                    reason = f"skill '{skill.name}' container execution denied by guardian"
                    denied_plan = self._deny_step(plan, step, reason, allow_failure, "container_policy_denied", "CONTAINER_POLICY_DENIED")
                    if denied_plan is not None:
                        return denied_plan
                    continue

                requires_network = "network" in (skill.get_permissions() or [])
                if requires_network and not self.guardian.check(skill.name, "network"):
                    reason = f"skill '{skill.name}' network access denied for tier 2"
                    denied_plan = self._deny_step(plan, step, reason, allow_failure, "network_policy_denied", "NETWORK_POLICY_DENIED")
                    if denied_plan is not None:
                        return denied_plan
                    continue

            if skill.tier == 3:
                if not self.guardian.check(skill.name, "airgapped"):
                    reason = f"skill '{skill.name}' airgapped execution denied by guardian"
                    denied_plan = self._deny_step(plan, step, reason, allow_failure, "airgapped_policy_denied", "AIRGAPPED_POLICY_DENIED")
                    if denied_plan is not None:
                        return denied_plan
                    continue

                # Tier 3 skills are strictly airgapped; network is disabled at runner level.
                if self.guardian.check(skill.name, "network"):
                    logger.warning("Skill %s requested network permission but operates in airgapped mode", skill.name)


            logger.info("Executing step %s (skill=%s action=%s)", step.id, step.skill_name, step.action)

            retry_on_any_error = bool(step.params.get("retry_on_any_error", False))
            retry_backoff_base = float(step.params.get("retry_backoff_seconds", 0.2))

            while True:
                try:
                    result = self._dispatch_step(step, skill)
                except Exception as exc:
                    result = SkillResult.fail(str(exc))

                step.attempts += 1
                step.update_result(result)

                if result.success:
                    step.completed_at = now_utc()
                    step.latency_ms = (time.perf_counter() - step_start_perf) * 1000
                    step.last_error = None
                    step.error_type = None
                    self.trust_ledger.record_outcome(step.skill_name, confirmed=True, error=False)
                    self._record_skill_action_telemetry(
                        step.skill_name,
                        step.action,
                        "success",
                        latency_ms=step.latency_ms,
                    )
                    self.audit_log.record(
                        "orchestrator",
                        "step_succeeded",
                        {
                            "plan_id": plan.id,
                            "step_id": step.id,
                            "skill": step.skill_name,
                            "action": step.action,
                            "attempts": step.attempts,
                            "latency_ms": round(step.latency_ms, 2),
                        },
                    )
                    break

                step.last_error = result.error
                step.error_type = "transient" if self._is_transient_error(result.error or "") else "non_transient"
                self.trust_ledger.record_outcome(step.skill_name, confirmed=False, error=True)
                self._record_skill_action_telemetry(
                    step.skill_name,
                    step.action,
                    "failure",
                    error_code=result.error_code or "STEP_EXECUTION_FAILED",
                )
                self.audit_log.record(
                    "orchestrator",
                    "step_failed",
                    {
                        "plan_id": plan.id,
                        "step_id": step.id,
                        "skill": step.skill_name,
                        "action": step.action,
                        "error": result.error,
                        "error_code": result.error_code,
                        "attempt": step.attempts,
                        "error_type": step.error_type,
                    },
                )
                logger.warning("Step %s failed (attempt %d): %s", step.id, step.attempts, result.error)

                if step.attempts <= step.max_retries and (retry_on_any_error or step.error_type == "transient"):
                    delay = self._retry_delay_seconds(step.attempts, retry_backoff_base)
                    self._record_skill_action_telemetry(
                        step.skill_name,
                        step.action,
                        "retry",
                        error_code="STEP_RETRY",
                    )
                    self.audit_log.record("orchestrator", "step_retry", {"plan_id": plan.id, "step_id": step.id, "attempt": step.attempts, "delay_seconds": delay})
                    if delay > 0:
                        time.sleep(delay)
                    continue

                if step.on_failure == "skip" or allow_failure:
                    self.audit_log.record("orchestrator", "step_skipped", {"plan_id": plan.id, "step_id": step.id, "on_failure": step.on_failure})
                    break

                if step.on_failure == "fallback":
                    self.audit_log.record("orchestrator", "step_fallback", {"plan_id": plan.id, "step_id": step.id})
                    break

                # abort semantics
                step.completed_at = now_utc()
                step.latency_ms = (time.perf_counter() - step_start_perf) * 1000
                plan.rollback()
                plan.mark_failed()
                self.audit_log.record("orchestrator", "plan_failed", {"plan_id": plan.id, "reason": "step_failed", "step_id": step.id})
                return plan

            if step.completed_at is None:
                step.completed_at = now_utc()
                step.latency_ms = (time.perf_counter() - step_start_perf) * 1000

        plan.mark_succeeded()
        self.audit_log.record("orchestrator", "plan_succeeded", {"plan_id": plan.id})
        return plan

    def simulate_plan(self, plan: Plan) -> Dict[str, Any]:
        """Simulate plan execution decisions without side effects."""
        summary = {
            "plan_id": plan.id,
            "status": "PENDING",
            "steps": [],
        }

        for step in plan.steps:
            step_state = {
                "step_id": step.id,
                "skill_name": step.skill_name,
                "action": step.action,
                "status": "PENDING",
                "reason": None,
            }

            if step.requires_confirmation and not step.params.get("confirmed", False):
                step_state["status"] = "DENIED"
                step_state["reason"] = "requires_confirmation"
                summary["steps"].append(step_state)
                continue

            if not self.guardian.check(step.skill_name, step.action):
                step_state["status"] = "DENIED"
                step_state["reason"] = "guardian_denied"
                summary["steps"].append(step_state)
                continue

            policy_decision = self.policy.evaluate(step.skill_name, step.action, step.params, self.trust_ledger)
            if not policy_decision.allowed:
                step_state["status"] = "DENIED"
                step_state["reason"] = f"policy_denied: {policy_decision.reason}"
                summary["steps"].append(step_state)
                continue

            skill = self.skills.get(step.skill_name)
            if not skill:
                step_state["status"] = "ERROR"
                step_state["reason"] = "skill_not_registered"
                summary["steps"].append(step_state)
                continue

            allowed_actions = getattr(skill, "allowed_actions", None)
            if allowed_actions and step.action not in allowed_actions:
                step_state["status"] = "DENIED"
                step_state["reason"] = "invalid_action"
                summary["steps"].append(step_state)
                continue

            schemas = skill.get_action_schemas()
            schema_error = self._schema_validator.validate(step.action, step.params, schemas.get(step.action))
            if schema_error:
                step_state["status"] = "DENIED"
                step_state["reason"] = f"invalid_params: {schema_error.error_code}"
                summary["steps"].append(step_state)
                continue

            if skill.tier == 2 and not self.guardian.check(skill.name, "container"):
                step_state["status"] = "DENIED"
                step_state["reason"] = "container_permission_required"
                summary["steps"].append(step_state)
                continue

            if skill.tier == 2 and "network" in (skill.get_permissions() or []) and not self.guardian.check(skill.name, "network"):
                step_state["status"] = "DENIED"
                step_state["reason"] = "network_permission_required"
                summary["steps"].append(step_state)
                continue

            if skill.tier == 3 and not self.guardian.check(skill.name, "airgapped"):
                step_state["status"] = "DENIED"
                step_state["reason"] = "airgapped_permission_required"
                summary["steps"].append(step_state)
                continue

            step_state["status"] = "ALLOWED"
            summary["steps"].append(step_state)

        summary["status"] = "SIMULATED"
        return summary

    def create_plan_from_instruction(self, instruction: str):
        """Construct a default plan from free-form instruction."""
        plan = Plan()
        plan.add_step(skill_name="echo", action="echo", params={"message": instruction})
        return plan

