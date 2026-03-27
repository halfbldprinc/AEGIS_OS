from datetime import datetime, timezone

from aegis.guardian import Guardian


def test_guardian_grant_revoke_cycle():
    guardian = Guardian(db_path=":memory:")

    assert not guardian.check("echo", "echo")

    guardian.grant("echo", "echo")
    assert guardian.check("echo", "echo")

    guardian.revoke("echo", "echo")
    assert not guardian.check("echo", "echo")


def test_guardian_expiry():
    guardian = Guardian(db_path=":memory:")
    guardian.grant("echo", "echo", duration_hours=1)

    assert guardian.check("echo", "echo")

    # Simulate expiry by writing old timestamp directly.
    guardian._write_permission("echo", "echo", datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert not guardian.check("echo", "echo")


def test_guardian_role_assignment():
    guardian = Guardian(db_path=":memory:")
    guardian.create_role("developer", "developer role")
    guardian.assign_role("developer", "echo", "execute")
    permissions = guardian.get_role_permissions("developer")

    assert {"skill_name": "echo", "action": "execute"} in permissions
