import copy

from aegis.sync import SyncManager
from aegis.sync.net import P2PTransport


def test_signed_envelope_delivery_to_authenticated_peer():
    peer_a = SyncManager(device_id="peer-a")
    peer_b = SyncManager(device_id="peer-b")

    assert peer_a.connect_peer("peer-b", peer_b.transport.bind_address, peer_b.transport.bind_port)
    published = peer_a.transport.publish_state({"x": {"value": 1, "timestamp": 1.0}})

    assert published is True
    stored = peer_b.transport.retrieve_blob("state:peer-a")
    assert stored is not None
    assert stored["x"]["value"] == 1


def test_peer_auth_rejects_wrong_token():
    peer_a = P2PTransport(node_id="peer-a")
    peer_b = P2PTransport(node_id="peer-b")

    assert peer_a.connect("peer-b", peer_b.bind_address, peer_b.bind_port, auth_token="invalid-token") is False


def test_tampered_signature_is_rejected():
    peer_a = P2PTransport(node_id="peer-a")
    peer_b = P2PTransport(node_id="peer-b")

    assert peer_a.connect("peer-b", peer_b.bind_address, peer_b.bind_port) is True

    envelope = peer_a._build_envelope(peer_id="peer-b", message_type="state_update", payload={"foo": {"value": "bar", "timestamp": 1.0}})
    tampered = copy.deepcopy(envelope)
    tampered["sig"] = "0" * 64

    assert peer_b._receive_envelope(tampered) is False


def test_fetch_state_retry_limit_exhaustion():
    transport = P2PTransport(node_id="local")
    assert transport.connect("missing-peer", "127.0.0.1", 65501) is True

    for _ in range(transport.MAX_RETRY):
        assert transport.fetch_state("missing-peer") is None

    assert transport.fetch_state("missing-peer") is None
    assert transport.retry_attempts["missing-peer"] == transport.MAX_RETRY + 1


def test_publish_state_succeeds_with_partial_peer_availability():
    origin = P2PTransport(node_id="origin")
    online = P2PTransport(node_id="online")

    assert origin.connect("online", online.bind_address, online.bind_port) is True
    assert origin.connect("offline", "127.0.0.1", 65502) is True

    # At least one peer is reachable, so publish should succeed.
    assert origin.publish_state({"k": {"value": "v", "timestamp": 2.0}}) is True


def test_connect_rejects_invalid_peer_endpoints():
    transport = P2PTransport(node_id="origin")

    assert transport.connect("", "127.0.0.1", 1234) is False
    assert transport.connect("peer", "", 1234) is False
    assert transport.connect("peer", "127.0.0.1", 0) is False
    assert transport.connect("peer", "127.0.0.1", 70000) is False
