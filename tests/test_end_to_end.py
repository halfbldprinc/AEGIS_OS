from fastapi.testclient import TestClient
from aegis.api import app

client = TestClient(app)


def test_end_to_end_integration_flow():
    # 1. Basic status
    response = client.get("/status")
    assert response.status_code == 200

    # 2. Guardian grant/check/deny flow
    response = client.post('/v1/guardian/grant', json={'skill_name': 'echo', 'action': 'echo', 'duration_hours': 1})
    assert response.status_code == 200

    response = client.get('/v1/guardian/check', params={'skill_name': 'echo', 'action': 'echo'})
    assert response.status_code == 200
    assert response.json()['allowed'] is True

    # 3. Orchestrator simulation flow
    payload = {
        'steps': [
            {'skill_name': 'echo', 'action': 'echo', 'params': {'message': 'hello'}}
        ]
    }
    response = client.post('/v1/orchestrator/simulate', json=payload)
    assert response.status_code == 200
    assert response.json()['status'] == 'SIMULATED'

    # 4. Resource metrics
    response = client.get('/v1/metrics')
    assert response.status_code == 200
    assert 'resource_metrics' in response.json()

    # 5. Security health
    response = client.get('/v1/security/health')
    assert response.status_code == 200
    assert 'audit_integrity' in response.json()
