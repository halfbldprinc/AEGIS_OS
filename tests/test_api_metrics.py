from fastapi.testclient import TestClient
from aegis.api import app
from aegis.daemon import AegisDaemon

client = TestClient(app)


def test_metrics_endpoint_exposes_resource_and_trust():
    app.state.daemon = AegisDaemon()
    response = client.get('/v1/metrics')
    assert response.status_code == 200
    data = response.json()
    assert 'resource_metrics' in data
    assert 'trust_snapshot' in data
    assert 'mode' in data
