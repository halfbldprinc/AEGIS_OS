from aegis.audit import AuditLog
from aegis.daemon import AegisDaemon
from aegis.api import app, update_manager
from fastapi.testclient import TestClient


client = TestClient(app)


def _fresh_daemon(tmp_path):
    return AegisDaemon(audit_log=AuditLog(path=tmp_path / "audit.log"))


def test_control_panel_api_flow_smoke(tmp_path):
    app.state.daemon = _fresh_daemon(tmp_path)

    update_manager.state_path = tmp_path / "update_state.json"
    update_manager._state = {
        "current": {"os": "0.1.0", "agent": "0.1.0", "model": "unknown"},
        "available": {},
        "history": [],
    }

    # 1) Overview should include control panel aggregates
    overview = client.get("/v1/control-center/overview")
    assert overview.status_code == 200
    overview_payload = overview.json()
    assert "mode" in overview_payload
    assert "pending_approvals" in overview_payload
    assert "updates" in overview_payload

    # 2) Create a pending approval then decide once
    client.post('/v1/guardian/revoke', json={'skill_name': 'echo', 'action': 'echo'})
    client.post('/v1/guardian/revoke', json={'skill_name': 'echo', 'action': 'all'})

    needs_approval = client.post('/v1/process-and-execute', json={'text': 'echo control panel smoke'})
    assert needs_approval.status_code == 200
    approval = needs_approval.json().get('approval', {})
    assert approval.get('plan_id')
    assert approval.get('step_id')

    pending = client.get("/v1/permissions/pending")
    assert pending.status_code == 200
    assert any(row.get("plan_id") == approval["plan_id"] for row in pending.json().get("pending", []))

    decision = client.post(
        "/v1/permissions/decide",
        json={"plan_id": approval["plan_id"], "step_id": approval["step_id"], "decision": "once"},
    )
    assert decision.status_code == 200
    assert decision.json().get("status") in {"SUCCEEDED", "FAILED"}

    # 3) Update apply and rollback flow
    register_update = client.post(
        "/v1/update/available",
        json={"component": "agent", "version": "0.2.0", "channel": "stable", "notes": "smoke"},
    )
    assert register_update.status_code == 200

    apply_update = client.post(
        "/v1/update/apply",
        json={"component": "agent", "version": "0.2.0", "source": "control-panel-smoke"},
    )
    assert apply_update.status_code == 200
    assert apply_update.json().get("status") == "applied"

    second_apply = client.post(
        "/v1/update/apply",
        json={"component": "agent", "version": "0.3.0", "source": "control-panel-smoke"},
    )
    assert second_apply.status_code == 200
    assert second_apply.json().get("status") == "applied"

    rollback_update = client.post("/v1/update/rollback", json={"component": "agent"})
    assert rollback_update.status_code == 200
    assert rollback_update.json().get("status") == "rolled_back"

    # 4) Activity feed should return events from this daemon's audit log.
    app.state.daemon.audit_log.record("test", "control_panel_smoke", {"ok": True})
    activity = client.get("/v1/activity/feed", params={"offset": 0, "limit": 200})
    assert activity.status_code == 200
    activity_payload = activity.json()
    assert "events" in activity_payload
    assert any(event.get("event_type") == "control_panel_smoke" for event in activity_payload["events"])
