import subprocess

from aegis.skills.system_control_skill import SystemControlSkill


class _Completed:
    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_service_status_rejects_non_allowlisted_service():
    skill = SystemControlSkill()
    result = skill.execute("service_status", {"service": "ssh.service"})
    assert not result.success
    assert result.error_code == "SERVICE_NOT_ALLOWED"


def test_service_mutations_require_confirmation():
    skill = SystemControlSkill()
    result = skill.execute("service_restart", {"service": "aegis-api.service", "confirmed": False})
    assert not result.success
    assert result.error_code == "CONFIRMATION_REQUIRED"


def test_wifi_status_uses_nmcli(monkeypatch):
    skill = SystemControlSkill()

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/nmcli" if name == "nmcli" else None)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: _Completed(returncode=0, stdout="enabled\n", stderr=""),
    )

    result = skill.execute("wifi_status", {})
    assert result.success
    assert result.data["wifi_enabled"] is True


def test_bluetooth_toggle_requires_confirmation():
    skill = SystemControlSkill()
    result = skill.execute("bluetooth_toggle", {"enabled": True, "confirmed": False})
    assert not result.success
    assert result.error_code == "CONFIRMATION_REQUIRED"


def test_service_status_success(monkeypatch):
    skill = SystemControlSkill()

    def _which(name):
        if name == "systemctl":
            return "/bin/systemctl"
        return None

    monkeypatch.setattr("shutil.which", _which)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: _Completed(returncode=0, stdout="active", stderr=""),
    )

    result = skill.execute("service_status", {"service": "aegis-api.service"})
    assert result.success
    assert result.data["returncode"] == 0
