from aegis.sync import SyncManager


def test_sync_blob_storage_and_retrieve():
    manager = SyncManager(device_id="local")
    blob_hash = manager.store_encrypted_blob("config", {"a": 1})
    assert blob_hash is not None

    retrieved = manager.retrieve_encrypted_blob("config")
    assert retrieved == {"a": 1}


def test_p2p_transport_connect_list_disconnect():
    manager = SyncManager(device_id="local")
    assert manager.transport.connect("peer1", "127.0.0.1", 8000)
    assert "peer1" in manager.transport.list_peers()
    assert manager.transport.disconnect("peer1")


def test_p2p_fetch_state_from_connected_peer():
    peer_a = SyncManager(device_id="peer-a")
    peer_b = SyncManager(device_id="peer-b")

    peer_b.set("task", "done", timestamp=42.0)

    assert peer_a.connect_peer("peer-b", peer_b.transport.bind_address, peer_b.transport.bind_port)
    fetched = peer_a.transport.fetch_state("peer-b")

    assert fetched is not None
    assert fetched["task"]["value"] == "done"
    assert fetched["task"]["timestamp"] == 42.0
