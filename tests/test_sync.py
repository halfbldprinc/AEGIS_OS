import time

from aegis.sync import SyncManager


def test_sync_manager_basic_merge():
    manager = SyncManager()
    manager.set("k1", "v1", timestamp=1.0)
    manager.set("k1", "v2", timestamp=2.0)  # newer should win

    manager2_state = {"k1": {"value": "v1-old", "timestamp": 1.5}, "k2": {"value": "v3", "timestamp": 3.0}}
    manager.merge(manager2_state)

    assert manager.get("k1") == "v2"
    assert manager.get("k2") == "v3"


def test_sync_manager_peer_registration():
    manager = SyncManager()
    manager.register_peer("peer-a")
    manager.register_peer("peer-a")
    manager.register_peer("peer-b")

    assert manager.peers == ["peer-a", "peer-b"]


def test_sync_manager_snapshot():
    manager = SyncManager()
    now = time.time()
    manager.set("foo", "bar", timestamp=now)

    snap = manager.snapshot()
    assert "foo" in snap
    assert snap["foo"]["value"] == "bar"
    assert snap["foo"]["timestamp"] == now


def test_sync_manager_merge_conflict():
    manager = SyncManager(device_id="a")
    manager.set("field", "value1", timestamp=1.0)

    other = SyncManager(device_id="b")
    other.set("field", "value2", timestamp=1.0)

    conflicts, merged = manager.merge(other)
    assert "field" in conflicts
    assert merged["field"]["value"] in ["value1", "value2"]
    assert manager.get_conflicts() == ["field"]

    manager.merge_conflict_resolution("field", "resolved", resolved_ts=2.0)
    assert manager.get("field") == "resolved"
    assert manager.get_conflicts() == []


def test_sync_api_conflict_endpoints(monkeypatch):
    from aegis.api import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    manager = SyncManager(device_id="a")
    manager.set("field", "value1", timestamp=1.0)

    other = SyncManager(device_id="b")
    other.set("field", "value2", timestamp=1.0)

    manager.merge(other)
    assert manager.get_conflicts() == ["field"]

    # push local conflict into endpoint by monkeypatching the internal import path that API uses.
    import aegis.sync
    monkeypatch.setattr(aegis.sync, "SyncManager", lambda *args, **kwargs: manager)

    response = client.get("/v1/sync/conflicts")
    assert response.status_code == 200
    assert response.json()["conflicts"] == ["field"]

    response = client.post("/v1/sync/conflict", json={"key": "field", "resolved_value": "resolved", "resolved_ts": 2.0})
    assert response.status_code == 200
    assert response.json()["resolved"] is True
    assert manager.get("field") == "resolved"


def test_sync_manager_persistence_roundtrip(tmp_path):
    storage = tmp_path / "sync.json"
    manager = SyncManager(device_id="local", storage_path=str(storage))
    manager.set("k1", "v1", timestamp=1.0)
    manager.register_peer("peer1")
    manager.save()

    new_manager = SyncManager(device_id="local", storage_path=str(storage))
    assert new_manager.get("k1") == "v1"
    assert "peer1" in new_manager.peers


def test_sync_manager_offline_queue_and_retry(tmp_path):
    manager = SyncManager(device_id="local", storage_path=str(tmp_path / "sync.json"))
    peer = SyncManager(device_id="peer-a", storage_path=str(tmp_path / "peer-sync.json"))

    # no peers; should enqueue blob publish
    manager.store_encrypted_blob("k1", {"value": 1})
    assert len(manager.offline_queue) == 1

    # connecting peer triggers retry
    manager.connect_peer("peer-a", peer.transport.bind_address, peer.transport.bind_port)
    retry_results = manager.retry_offline_queue()

    assert retry_results["processed"] == 1
    assert len(manager.offline_queue) == 0


def test_sync_manager_checkpoint_creation_and_apply(tmp_path):
    manager = SyncManager(device_id="local", storage_path=str(tmp_path / "sync.json"))
    manager.set("foo", "bar", timestamp=1.0)

    checkpoint = manager.create_checkpoint()
    assert checkpoint["state_snapshot"]["foo"]["value"] == "bar"

    manager.set("foo", "baz", timestamp=2.0)
    assert manager.get("foo") == "baz"

    manager.apply_checkpoint(checkpoint)
    assert manager.get("foo") == "bar"


def test_sync_manager_save_with_flat_relative_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SyncManager(device_id="local", storage_path="sync.json")
    manager.set("k", "v", timestamp=1.0)
    manager.save()

    loaded = SyncManager(device_id="local", storage_path="sync.json")
    assert loaded.get("k") == "v"


def test_sync_manager_load_ignores_malformed_payload(tmp_path):
    path = tmp_path / "broken-sync.json"
    path.write_text("{not-json", encoding="utf-8")

    manager = SyncManager(device_id="local", storage_path=str(path))
    assert manager.snapshot() == {}


def test_sync_manager_atomic_save_cleans_temp_file(tmp_path):
    path = tmp_path / "sync-atomic.json"
    manager = SyncManager(device_id="local", storage_path=str(path))
    manager.set("k", "v", timestamp=1.0)
    manager.save()

    assert path.exists()
    assert not (tmp_path / "sync-atomic.json.tmp").exists()

