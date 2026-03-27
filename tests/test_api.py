from fastapi.testclient import TestClient

from aegis.api import app
from aegis.daemon import AegisDaemon

client = TestClient(app)


def test_status_endpoint():
    response = client.get("/status")
    assert response.status_code == 200
    assert "mode" in response.json()


def test_run_cycle_endpoint():
    response = client.post("/run-cycle")
    assert response.status_code == 200
    assert response.json()["status"] == "executed"


def test_onboarding_flow():
    response = client.post("/onboarding", json={"approved": True})
    assert response.status_code == 200
    assert response.json()["mode"] in ["ACTIVE_SHADOW_MODE", "ACTIVE_MODE"]


def test_enable_autonomy():
    response = client.post("/autonomy")
    assert response.status_code == 200
    assert response.json()["mode"] == "ACTIVE_MODE"


def test_trust_endpoint():
    response = client.get('/v1/trust')
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_memory_search_endpoint():
    # Ensure the memory store is functional via API.
    response = client.post('/v1/memory/upsert', json={'text': 'This is a unit test memory item', 'metadata': {'topic': 'tests'}})
    assert response.status_code == 200
    entry_id = response.json()['id']

    response = client.get('/v1/memory/search', params={'q': 'unit test'})
    assert response.status_code == 200
    data = response.json()
    assert data['query'] == 'unit test'
    assert isinstance(data['results'], list)
    assert any(item['id'] == entry_id for item in data['results'])

    response = client.delete(f'/v1/memory/{entry_id}')
    assert response.status_code == 200


def test_memory_scope_api_roundtrip():
    response = client.post(
        '/v1/memory/upsert',
        json={
            'text': 'Temporary contextual note for this session',
            'metadata': {'topic': 'session'},
            'scope': 'short_term',
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload['scope'] == 'short_term'
    entry_id = payload['id']

    response = client.get('/v1/memory/search', params={'q': 'contextual note', 'scope': 'short_term'})
    assert response.status_code == 200
    data = response.json()
    assert data['scope'] == 'short_term'
    assert any(item['id'] == entry_id for item in data['results'])
    assert all(item['scope'] == 'short_term' for item in data['results'])


def test_memory_scope_api_rejects_invalid_scope():
    response = client.post(
        '/v1/memory/upsert',
        json={
            'text': 'invalid scope probe',
            'scope': 'ephemeral',
        },
    )
    assert response.status_code == 422

    response = client.get('/v1/memory/search', params={'q': 'probe', 'scope': 'ephemeral'})
    assert response.status_code == 422


def test_guardian_endpoints():
    response = client.post('/v1/guardian/grant', json={'skill_name': 'echo', 'action': 'echo', 'duration_hours': 1})
    assert response.status_code == 200

    response = client.get('/v1/guardian')
    assert response.status_code == 200
    perms = response.json().get('permissions', [])
    assert any(p['skill_name'] == 'echo' and p['action'] == 'echo' for p in perms)

    response = client.post('/v1/guardian/revoke', json={'skill_name': 'echo', 'action': 'echo'})
    assert response.status_code == 200

    response = client.get('/v1/guardian')
    assert response.status_code == 200
    perms = response.json().get('permissions', [])
    assert not any(p['skill_name'] == 'echo' and p['action'] == 'echo' for p in perms)

def test_resource_status_endpoint():
    response = client.get("/v1/resource/status")
    assert response.status_code == 200
    assert "resource_decision" in response.json()
    assert isinstance(response.json()["resource_decision"], dict)


def test_guardian_check_endpoint():
    app.state.daemon = AegisDaemon()
    client.post('/v1/guardian/grant', json={'skill_name': 'echo', 'action': 'echo', 'duration_hours': 1})

    response = client.get('/v1/guardian/check', params={'skill_name': 'echo', 'action': 'echo'})
    assert response.status_code == 200
    assert response.json() == {'skill_name': 'echo', 'action': 'echo', 'allowed': True}

    # Revoke broad permission to validate denial path
    client.post('/v1/guardian/revoke', json={'skill_name': 'echo', 'action': 'all'})

    response = client.get('/v1/guardian/check', params={'skill_name': 'echo', 'action': 'write'})
    assert response.status_code == 200
    assert response.json() == {'skill_name': 'echo', 'action': 'write', 'allowed': False}


def test_orchestrator_simulation_endpoint():
    # Reset daemon state for deterministic behavior in test suite ordering.
    app.state.daemon = AegisDaemon()
    client.post('/v1/guardian/grant', json={'skill_name': 'echo', 'action': 'echo', 'duration_hours': 1})

    payload = {
        "steps": [
            {"skill_name": "echo", "action": "echo", "params": {"message": "hi"}}
        ]
    }
    response = client.post("/v1/orchestrator/simulate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["plan_id"]
    assert data["status"] == "SIMULATED"
    assert data["steps"][0]["status"] == "ALLOWED"


def test_metrics_telemetry_endpoint_exists():
    response = client.get("/v1/metrics/telemetry")
    assert response.status_code == 200
    assert "# HELP aegis_telemetry_metric" in response.text


def test_process_plan_endpoint():
    response = client.post("/v1/process", json={"text": "Hello world"})
    assert response.status_code == 200
    data = response.json()
    assert "plan_id" in data
    assert data["status"] == "PENDING"


def test_get_plan_endpoint_and_confirm():
    response = client.post("/v1/process", json={"text": "Run an echo"})
    plan_id = response.json()["plan_id"]

    response = client.get(f"/v1/plan/{plan_id}")
    assert response.status_code == 200
    plan_data = response.json()
    assert plan_data["plan_id"] == plan_id
    assert len(plan_data["steps"]) == 1

    step_id = plan_data["steps"][0]["id"]
    response = client.post("/v1/confirm", json={"plan_id": plan_id, "step_id": step_id, "approved": True})
    assert response.status_code == 200
    final_plan = response.json()
    assert final_plan["status"] in ["SUCCEEDED", "PENDING", "FAILED"]


def test_process_and_execute_permission_prompt_once_flow():
    app.state.daemon = AegisDaemon()

    # Force a first-run permission prompt by removing echo execution permission.
    client.post('/v1/guardian/revoke', json={'skill_name': 'echo', 'action': 'echo'})
    client.post('/v1/guardian/revoke', json={'skill_name': 'echo', 'action': 'all'})

    response = client.post('/v1/process-and-execute', json={'text': 'echo hello'})
    assert response.status_code == 200
    data = response.json()
    assert data['requires_approval'] is True
    assert data['approval']['skill'] == 'echo'
    assert data['approval']['action'] == 'echo'

    confirm = client.post(
        '/v1/confirm',
        json={
            'plan_id': data['approval']['plan_id'],
            'step_id': data['approval']['step_id'],
            'approved': True,
        },
    )
    assert confirm.status_code == 200
    assert confirm.json()['status'] == 'SUCCEEDED'

    # Next run should execute without another approval prompt.
    rerun = client.post('/v1/process-and-execute', json={'text': 'echo hello again'})
    assert rerun.status_code == 200
    assert rerun.json()['requires_approval'] is False
    assert rerun.json()['status'] in ['SUCCEEDED', 'FAILED']


def test_evolution_approve_endpoint():
    # Use the API's singleton manager instance for correctness.
    from aegis.api import evolution_manager

    proposal = evolution_manager.create_proposal("p-test", metrics={"delta_perplexity": 0.01})

    response = client.post(f"/v1/evolution/approve?proposal_id={proposal.proposal_id}")
    assert response.status_code == 200
    assert response.json()["approved"] is True


def test_voice_process_text_endpoint_requires_wakeword_and_executes():
    app.state.daemon = AegisDaemon()

    no_wake = client.post("/v1/voice/process-text", json={"transcript": "hello there"})
    assert no_wake.status_code == 200
    assert no_wake.json().get("text") == "I heard the wake word, but no command followed."

    with_wake = client.post("/v1/voice/process-text", json={"transcript": "aegis hello api"})
    assert with_wake.status_code == 200
    payload = with_wake.json()
    assert payload["plan_status"] == "SUCCEEDED"
    assert payload["steps"][0]["skill"] == "echo"


def test_voice_process_text_endpoint_rejects_empty_input():
    response = client.post("/v1/voice/process-text", json={"transcript": "   "})
    assert response.status_code == 400


def test_ops_soak_endpoint():
    response = client.post("/v1/ops/soak", json={"cycles": 2, "sleep_s": 0.0})
    assert response.status_code == 200
    data = response.json()
    assert data["cycles"] == 2
    assert "success_rate" in data


def test_ops_chaos_endpoint():
    response = client.post("/v1/ops/chaos", json={"scenario": "voice_interrupt"})
    assert response.status_code == 200
    assert response.json()["scenario"] == "voice_interrupt"


def test_update_lifecycle_endpoints(tmp_path):
    from aegis.api import update_manager

    update_manager.state_path = tmp_path / "update_state.json"
    update_manager._state = {
        "current": {"os": "0.1.0", "agent": "0.1.0", "model": "unknown"},
        "available": {},
        "history": [],
    }

    response = client.post(
        "/v1/update/available",
        json={
            "component": "agent",
            "version": "0.2.1",
            "channel": "stable",
            "notes": "test update",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "registered"

    response = client.get("/v1/update/status")
    assert response.status_code == 200
    pending = response.json()["pending_updates"]
    assert any(item["component"] == "agent" and item["available_version"] == "0.2.1" for item in pending)

    response = client.post(
        "/v1/update/apply",
        json={
            "component": "agent",
            "version": "0.2.1",
            "source": "test",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "applied"


def test_sync_connect_endpoint_rejects_invalid_port():
    response = client.post("/v1/sync/connect", json={"peer_id": "p1", "address": "127.0.0.1", "port": 0})
    assert response.status_code == 422


def test_conversation_history_rejects_empty_session_id():
    response = client.get("/v1/conversation/history", params={"session_id": ""})
    assert response.status_code == 400


def test_process_endpoint_rejects_oversized_input():
    response = client.post("/v1/process", json={"text": "x" * 60000})
    assert response.status_code == 422

