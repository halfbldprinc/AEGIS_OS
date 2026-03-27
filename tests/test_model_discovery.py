from aegis.llm import model_discovery


def test_discovery_ignores_unsupported_providers(monkeypatch):
    monkeypatch.setenv("AEGIS_MODEL_DISCOVERY_PROVIDERS", "unknown,feeds")
    monkeypatch.setattr(model_discovery, "_discover_feed_profiles", lambda timeout_s=5.0: [])

    profiles = model_discovery.discover_model_profiles(existing_profiles=[{"profile_id": "p1"}], timeout_s=0.1)
    assert profiles[0]["profile_id"] == "p1"


def test_discovery_falls_back_when_no_profiles(monkeypatch):
    monkeypatch.setenv("AEGIS_MODEL_DISCOVERY_PROVIDERS", "feeds")
    monkeypatch.setattr(model_discovery, "_discover_feed_profiles", lambda timeout_s=5.0: [])

    profiles = model_discovery.discover_model_profiles(existing_profiles=[], timeout_s=0.1)
    assert profiles
    assert "profile_id" in profiles[0]
