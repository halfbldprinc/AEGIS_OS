from aegis.update_manager import UpdateManager


def test_update_manager_tracks_available_and_applied_versions(tmp_path):
    state = tmp_path / "update_state.json"
    manager = UpdateManager(state_path=str(state))

    manager.set_available_update(component="agent", version="0.2.0", channel="stable", notes="agent patch")
    status = manager.status()

    assert status["available"]["agent"]["version"] == "0.2.0"
    assert any(item["component"] == "agent" for item in status["pending_updates"])

    record = manager.apply_update(component="agent", version="0.2.0", source="ota")
    assert record["component"] == "agent"

    post = manager.status()
    assert post["current"]["agent"] == "0.2.0"
    assert "agent" not in post["available"]


def test_update_manager_rejects_unknown_component(tmp_path):
    manager = UpdateManager(state_path=str(tmp_path / "update_state.json"))

    try:
        manager.set_available_update(component="firmware", version="1.0.0")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "component must be one of" in str(exc)
