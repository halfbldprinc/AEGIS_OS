import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional

from ..audit import AuditEvent, AuditLog


@dataclass
class HarnessSummary:
    generated_at: str
    event_count: int
    latency_ms: Dict[str, float]
    denial_reason_distribution: Dict[str, int]
    retry_effectiveness: Dict[str, float]
    success_rate_by_skill_action: Dict[str, Dict[str, float]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "event_count": self.event_count,
            "latency_ms": self.latency_ms,
            "denial_reason_distribution": self.denial_reason_distribution,
            "retry_effectiveness": self.retry_effectiveness,
            "success_rate_by_skill_action": self.success_rate_by_skill_action,
        }


class OrchestratorEvaluationHarness:
    """Aggregates orchestrator audit events into measurable reliability and performance KPIs."""

    def evaluate_from_audit_log(self, audit_log: AuditLog, since_hours: Optional[float] = None) -> HarnessSummary:
        events = audit_log.read_all()
        if since_hours is not None and since_hours > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
            events = [event for event in events if _parse_time(event.timestamp) >= cutoff]
        return self.evaluate_events(events)

    def evaluate_events(self, events: Iterable[AuditEvent]) -> HarnessSummary:
        events = list(events)
        latencies: List[float] = []
        denials: Counter[str] = Counter()

        retries_by_step: Counter[str] = Counter()
        terminal_by_step: Dict[str, str] = {}

        by_skill_action = defaultdict(lambda: {"attempts": 0, "successes": 0, "failures": 0, "denials": 0})

        for event in events:
            if event.source != "orchestrator":
                continue

            details = event.details or {}
            skill = str(details.get("skill") or "unknown")
            action = str(details.get("action") or details.get("step_action") or "unknown")
            step_id = str(details.get("step_id") or "")
            key = f"{skill}:{action}"

            if event.event_type == "step_succeeded":
                by_skill_action[key]["attempts"] += 1
                by_skill_action[key]["successes"] += 1
                latency = details.get("latency_ms")
                if isinstance(latency, (int, float)):
                    latencies.append(float(latency))
                if step_id:
                    terminal_by_step[step_id] = "success"

            elif event.event_type == "step_failed":
                by_skill_action[key]["attempts"] += 1
                by_skill_action[key]["failures"] += 1
                if step_id:
                    terminal_by_step[step_id] = "failed"

            elif event.event_type == "step_denied":
                by_skill_action[key]["attempts"] += 1
                by_skill_action[key]["denials"] += 1
                reason = str(details.get("reason") or "unknown")
                denials[reason] += 1
                if step_id:
                    terminal_by_step[step_id] = "denied"

            elif event.event_type == "step_retry":
                if step_id:
                    retries_by_step[step_id] += 1

        retry_steps = set(retries_by_step.keys())
        retried_and_succeeded = 0
        retried_and_failed = 0
        retried_no_terminal = 0

        for step_id in retry_steps:
            state = terminal_by_step.get(step_id)
            if state == "success":
                retried_and_succeeded += 1
            elif state in {"failed", "denied"}:
                retried_and_failed += 1
            else:
                retried_no_terminal += 1

        success_rate_by_skill_action: Dict[str, Dict[str, float]] = {}
        for key, counters in by_skill_action.items():
            attempts = counters["attempts"]
            success_rate = float(counters["successes"] / attempts) if attempts else 0.0
            success_rate_by_skill_action[key] = {
                "attempts": float(attempts),
                "successes": float(counters["successes"]),
                "failures": float(counters["failures"]),
                "denials": float(counters["denials"]),
                "success_rate": success_rate,
            }

        latency_summary = _latency_summary(latencies)
        retry_effectiveness = {
            "retry_event_count": float(sum(retries_by_step.values())),
            "retried_step_count": float(len(retry_steps)),
            "retried_steps_succeeded": float(retried_and_succeeded),
            "retried_steps_failed": float(retried_and_failed),
            "retried_steps_without_terminal_state": float(retried_no_terminal),
            "effectiveness_rate": float(retried_and_succeeded / (retried_and_succeeded + retried_and_failed))
            if (retried_and_succeeded + retried_and_failed)
            else 0.0,
        }

        return HarnessSummary(
            generated_at=datetime.now(timezone.utc).isoformat(),
            event_count=len(events),
            latency_ms=latency_summary,
            denial_reason_distribution=dict(denials),
            retry_effectiveness=retry_effectiveness,
            success_rate_by_skill_action=success_rate_by_skill_action,
        )

    def append_snapshot(self, output_path: str | Path, summary: HarnessSummary) -> None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary.to_dict(), ensure_ascii=False) + "\n")


def _latency_summary(latencies: List[float]) -> Dict[str, float]:
    if not latencies:
        return {"count": 0.0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}

    ordered = sorted(latencies)
    p50 = ordered[int((len(ordered) - 1) * 0.50)]
    p95 = ordered[int((len(ordered) - 1) * 0.95)]
    return {
        "count": float(len(ordered)),
        "mean": float(mean(ordered)),
        "p50": float(p50),
        "p95": float(p95),
        "max": float(max(ordered)),
    }


def _parse_time(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
