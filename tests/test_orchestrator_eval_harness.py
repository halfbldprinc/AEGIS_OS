import json

from aegis.audit import AuditEvent
from aegis.orchestrator.eval_harness import OrchestratorEvaluationHarness


def test_eval_harness_aggregates_denials_retries_and_success_rate(tmp_path):
    harness = OrchestratorEvaluationHarness()

    events = [
        AuditEvent(
            timestamp="2026-03-27T10:00:00+00:00",
            source="orchestrator",
            event_type="step_retry",
            details={"step_id": "s1", "skill": "echo", "action": "echo", "attempt": 1},
        ),
        AuditEvent(
            timestamp="2026-03-27T10:00:01+00:00",
            source="orchestrator",
            event_type="step_succeeded",
            details={"step_id": "s1", "skill": "echo", "action": "echo", "latency_ms": 42.0},
        ),
        AuditEvent(
            timestamp="2026-03-27T10:00:02+00:00",
            source="orchestrator",
            event_type="step_denied",
            details={"step_id": "s2", "skill": "shell", "action": "run", "reason": "guardian_denied"},
        ),
        AuditEvent(
            timestamp="2026-03-27T10:00:03+00:00",
            source="orchestrator",
            event_type="step_failed",
            details={"step_id": "s3", "skill": "browser", "action": "fetch_text", "error": "timeout"},
        ),
    ]

    summary = harness.evaluate_events(events).to_dict()

    assert summary["latency_ms"]["count"] == 1.0
    assert summary["denial_reason_distribution"]["guardian_denied"] == 1
    assert summary["retry_effectiveness"]["retried_step_count"] == 1.0
    assert summary["retry_effectiveness"]["retried_steps_succeeded"] == 1.0

    echo_key = "echo:echo"
    assert summary["success_rate_by_skill_action"][echo_key]["attempts"] == 1.0
    assert summary["success_rate_by_skill_action"][echo_key]["success_rate"] == 1.0


def test_eval_harness_appends_snapshot(tmp_path):
    harness = OrchestratorEvaluationHarness()
    summary = harness.evaluate_events([])

    out = tmp_path / "history.jsonl"
    harness.append_snapshot(out, summary)

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event_count"] == 0
