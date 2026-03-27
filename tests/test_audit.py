from aegis.audit import AuditLog, AuditEvent


def test_audit_log_record_and_read(tmp_path):
    log_file = tmp_path / "audit.log"
    audit = AuditLog(path=log_file)

    audit.record("test", "unit_test", {"outcome": "pass"})
    audit.record("test", "unit_test", {"outcome": "pass2"})

    events = audit.read_all()
    assert len(events) == 2
    assert isinstance(events[0], AuditEvent)
    assert events[0].source == "test"


def test_audit_log_skip_bad_line(tmp_path):
    log_file = tmp_path / "audit.log"
    log_file.write_text("not-a-json\n{\"timestamp\": \"t\", \"source\": \"test\", \"event_type\": \"ok\", \"details\": {}}\n", encoding="utf-8")

    audit = AuditLog(path=log_file)
    events = audit.read_all()
    assert len(events) == 1


def test_encrypted_audit_log(tmp_path):
    log_file = tmp_path / "audit.log"
    key = "test-audit-key-1234567890abcdef"
    audit = AuditLog(path=log_file, encryption_key=key)

    audit.record("test", "encrypted", {"info": "secret"})
    assert log_file.exists()

    loaded = AuditLog(path=log_file, encryption_key=key).read_all()
    assert len(loaded) == 1
    assert loaded[0].source == "test"
    assert loaded[0].details["info"] == "secret"


def test_audit_record_non_serializable_details_does_not_raise(tmp_path):
    log_file = tmp_path / "audit.log"
    audit = AuditLog(path=log_file)

    # set() is not JSON-serializable; audit log should catch and continue.
    audit.record("test", "bad_payload", {"values": {1, 2, 3}})

    events = audit.read_all()
    assert events == []


def test_audit_read_from_offset_streams_incrementally(tmp_path):
    log_file = tmp_path / "audit.log"
    audit = AuditLog(path=log_file)

    audit.record("test", "first", {"n": 1})
    events_1, offset_1 = audit.read_from_offset(0)
    assert len(events_1) == 1
    assert events_1[0].event_type == "first"

    audit.record("test", "second", {"n": 2})
    events_2, offset_2 = audit.read_from_offset(offset_1)
    assert len(events_2) == 1
    assert events_2[0].event_type == "second"
    assert offset_2 >= offset_1


def test_audit_read_from_offset_respects_max_events(tmp_path):
    log_file = tmp_path / "audit.log"
    audit = AuditLog(path=log_file)

    for idx in range(3):
        audit.record("test", f"event-{idx}", {"i": idx})

    events, _ = audit.read_from_offset(0, max_events=2)
    assert len(events) == 2
    assert events[0].event_type == "event-0"
    assert events[1].event_type == "event-1"


def test_audit_read_from_offset_resets_when_offset_stale(tmp_path):
    log_file = tmp_path / "audit.log"
    audit = AuditLog(path=log_file)

    audit.record("test", "event-a", {"payload": "x" * 5000})
    _, offset = audit.read_from_offset(0)

    log_file.write_text("", encoding="utf-8")
    audit.record("test", "event-b", {"n": 2})

    events, _ = audit.read_from_offset(offset)
    assert len(events) == 1
    assert events[0].event_type == "event-b"


def test_audit_rotation_keeps_recent_files(tmp_path):
    log_file = tmp_path / "audit.log"
    audit = AuditLog(path=log_file)

    for idx in range(5):
        audit.record("test", f"event-{idx}", {"value": "x" * 200})
        audit.rotate(max_backups=2)

    assert (tmp_path / "audit.log.1").exists()
    assert not (tmp_path / "audit.log.3").exists()
