import sys

from aegis.skills.os_control_skill import OSControlSkill
from aegis.skills.settings_skill import SettingsSkill


def test_clipboard_cycle_exists():
    skill = OSControlSkill()
    if sys.platform not in ["darwin", "linux"]:
        assert skill.clipboard_set("x") is not None
        return

    result = skill.clipboard_set("test-data")
    assert result.success or "required" in (result.error or "")

    result = skill.clipboard_get()
    assert result.success or "required" in (result.error or "")


def test_notify_available():
    skill = OSControlSkill()
    result = skill.notify("AegisOS", "Integration test notification")
    assert result.success or "required" in (result.error or "")


def test_settings_volume_supported():
    skill = SettingsSkill()
    result = skill.set_volume(10)
    assert result.success or "required" in (result.error or "")


def test_settings_snapshot_and_revert(monkeypatch):
    skill = SettingsSkill()

    monkeypatch.setattr(skill, "get_volume_level", lambda: 22)
    monkeypatch.setattr(skill, "get_brightness_level", lambda: 44)
    monkeypatch.setattr(skill, "get_network_state", lambda: True)
    monkeypatch.setattr(skill, "get_dnd_state", lambda: False)

    applied = []

    def fake_set_volume(v):
        applied.append(("volume", v))
        return skill._run_cmd(["echo", "ok"])

    def fake_set_brightness(v):
        applied.append(("brightness", v))
        return skill._run_cmd(["echo", "ok"])

    def fake_set_network(v):
        applied.append(("network", v))
        return skill._run_cmd(["echo", "ok"])

    def fake_set_dnd(v):
        applied.append(("dnd", v))
        return skill._run_cmd(["echo", "ok"])

    monkeypatch.setattr(skill, "set_volume", fake_set_volume)
    monkeypatch.setattr(skill, "set_brightness", fake_set_brightness)
    monkeypatch.setattr(skill, "set_network", fake_set_network)
    monkeypatch.setattr(skill, "set_dnd", fake_set_dnd)

    snap = skill.execute("snapshot", {})
    assert snap.success

    rev = skill.execute("revert", {})
    assert rev.success
    assert ("volume", 22) in applied
    assert ("brightness", 44) in applied
    assert ("network", True) in applied
    assert ("dnd", False) in applied
