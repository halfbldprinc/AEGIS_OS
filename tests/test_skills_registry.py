from aegis.skills.registry import SkillRegistry
import hashlib
import hmac
import os


def test_skill_registry_register_and_get(tmp_path):
    db_path = tmp_path / "skills.json"
    registry = SkillRegistry(str(db_path))

    registry.register("echo", tier=1, permissions=["echo"], hash_value="abc123")
    entry = registry.get("echo")

    assert entry is not None
    assert entry["tier"] == 1
    assert entry["permissions"] == ["echo"]
    assert entry["hash"] == "abc123"

    # reload from disk to ensure persistence layer works
    registry2 = SkillRegistry(str(db_path))
    entry2 = registry2.get("echo")
    assert entry2 == entry


def test_skill_registry_verify_signature():
    registry = SkillRegistry("/tmp/nonexistent_registry.json")
    registry.register("echo", tier=1, permissions=["echo"])

    os.environ["AEGIS_SKILL_SIGNING_KEY"] = "test-key"
    expected = hmac.new(
        b"test-key",
        registry.get("echo")["hash"].encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert registry.verify_signature("echo", expected) is True
    assert registry.verify_signature("echo", "signature-data") is False
    assert registry.verify_signature("echo", None) is True
    assert registry.verify_signature("missing", "signature-data") is False


def test_skill_registry_tampered_metadata_fails_verification(tmp_path):
    db_path = tmp_path / "skills.json"
    registry = SkillRegistry(str(db_path))
    registry.register("echo", tier=1, permissions=["echo"])

    entry = registry.get("echo")
    entry["permissions"].append("network")
    registry._save()

    # reload and tamper persisted record directly
    registry2 = SkillRegistry(str(db_path))
    registry2._data["echo"]["permissions"].append("filesystem")
    registry2._save()

    registry3 = SkillRegistry(str(db_path))
    assert registry3.verify_signature("echo", None) is False


def test_skill_registry_external_unsigned_denied(tmp_path):
    db_path = tmp_path / "skills.json"
    registry = SkillRegistry(str(db_path))
    registry.register_external("external_tool", tier=2, permissions=["network"])

    assert registry.verify_signature("external_tool", None) is False
