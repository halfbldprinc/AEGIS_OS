import json
import sys

from aegis.security import SecurityManager


def test_security_status_and_secret_rotation(tmp_path):
    manager = SecurityManager()
    manager.secret_manager.storage_path = str(tmp_path / "secrets.json")

    record = manager.secret_manager.create_secret("api_key")
    assert record.key_id == "api_key"
    assert manager.secret_manager.get_secret("api_key") is not None

    rotated = manager.secret_manager.rotate_secret("api_key")
    assert rotated.key_id == "api_key"
    assert rotated.value != record.value

    status = manager.status()
    assert status["secret_count"] == 1


def test_selinux_policy_apply_and_validate(tmp_path):
    manager = SecurityManager()
    manager.selinux_manager.policy_path = str(tmp_path / "aegis.policy")

    manager.selinux_manager.apply_policy("allow aegis_t self_t:process transition;")
    assert manager.selinux_manager.validate_policy()


def test_selinux_policy_rejects_invalid_rules(tmp_path):
    manager = SecurityManager()
    manager.selinux_manager.policy_path = str(tmp_path / "aegis.policy")

    try:
        manager.selinux_manager.apply_policy("allow aegis_t self_t:process transition")
        assert False, "Expected ValueError for missing ';' terminator"
    except ValueError:
        assert True


def test_selinux_policy_validate_detects_bad_file(tmp_path):
    manager = SecurityManager()
    manager.selinux_manager.policy_path = str(tmp_path / "aegis.policy")

    (tmp_path / "aegis.policy").write_text("this is not a policy;\n", encoding="utf-8")
    assert manager.selinux_manager.validate_policy() is False


def test_security_audit_key_rotation():
    manager = SecurityManager()
    key1 = manager.ensure_audit_key()
    key2 = manager.ensure_audit_key()

    assert key1 == key2

    manager.secret_manager.rotate_secret("audit_log_key")
    key3 = manager.ensure_audit_key()
    assert key3 != key1


def test_security_audit_integrity_and_health(tmp_path):
    manager = SecurityManager()
    manager.secret_manager.storage_path = str(tmp_path / "secrets.json")

    manager.secret_manager.create_secret("test-key")
    manager.prepare_fscrypt_path(str(tmp_path))

    health = manager.health_status()
    assert health["audit_integrity"] is True
    assert health["secrets"] >= 1


def test_prepare_luks_volume_on_non_linux_raises():
    manager = SecurityManager()
    try:
        manager.prepare_luks_volume("/dev/fake")
        if not sys.platform.startswith("linux"):
            assert False, "Expected EnvironmentError on non-Linux"
    except EnvironmentError:
        assert not sys.platform.startswith("linux")


def test_prepare_fscrypt_path(tmp_path):
    p = tmp_path / "data"
    p.mkdir()

    manager = SecurityManager()
    result = manager.prepare_fscrypt_path(str(p))
    assert result["path"] == str(p)
    assert result["status"] in ["planned", "prepared", "failed"]


def test_audit_log_backup_and_retention(tmp_path):
    manager = SecurityManager()
    log_path = tmp_path / ".aegis" / "audit.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Use the same AuditLog instance for the secret manager path
    manager.secret_manager.audit.path = log_path

    # create old and new events
    manager.secret_manager.audit.record("security", "event1", {"x": 1})
    stale_event = {
        "chain_hash": "0",
        "event": {"timestamp": "2000-01-01T00:00:00", "source": "security", "event_type": "old", "details": {}}
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(stale_event) + "\n")

    result = manager.backup_audit_log(str(tmp_path / "audit.backup"))
    assert result["success"] is True

    retention_result = manager.enforce_audit_retention(age_days=365 * 20)
    assert retention_result["expired_count"] >= 1


def test_security_apparmor_profile(tmp_path):
    manager = SecurityManager()
    result = manager.apply_apparmor_profile("aegis_test", "# profile test")
    assert result["status"] in ["applied", "failed"]

