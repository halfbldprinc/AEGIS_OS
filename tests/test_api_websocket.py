from fastapi.testclient import TestClient
from aegis.api import app
from aegis.daemon import AegisDaemon

client = TestClient(app)


def test_plan_events_websocket_stream():
    app.state.daemon = AegisDaemon()

    with client.websocket_connect('/v1/ws/plan-events') as ws:
        # Trigger a simple cycle to generate events
        client.post('/run-cycle')
        # Receive at least one event from the stream
        message = ws.receive_json()
        assert 'timestamp' in message
        assert 'source' in message
        assert 'event_type' in message
