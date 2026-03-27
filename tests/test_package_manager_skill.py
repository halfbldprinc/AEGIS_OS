import os
import shutil
import subprocess

from aegis.skills.package_manager_skill import PackageManagerSkill


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_package_resolve_alias(monkeypatch):
    skill = PackageManagerSkill()
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/apt-get" if cmd in {"apt-get", "dpkg-query"} else None)

    result = skill.execute("resolve", {"package": "vscode"})

    assert result.success
    assert result.data["backend"] == "apt"
    assert result.data["resolved"] == "code"


def test_package_install_requires_confirmation():
    skill = PackageManagerSkill()

    result = skill.execute("install", {"package": "git", "confirmed": False})

    assert not result.success
    assert "explicit approval" in (result.error or "")


def test_package_search_apt(monkeypatch):
    skill = PackageManagerSkill()

    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/apt-get" if cmd in {"apt-get", "dpkg-query"} else None)

    def fake_run(cmd, check, capture_output, text, timeout):
        assert cmd[:3] == ["apt-cache", "search", "git"]
        return _Completed(returncode=0, stdout="git - fast version control\ngit-doc - docs\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = skill.execute("search", {"package": "git", "limit": 5})

    assert result.success
    assert result.data["backend"] == "apt"
    assert len(result.data["results"]) == 2


def test_package_install_uses_sudo_when_not_root(monkeypatch):
    skill = PackageManagerSkill()

    def fake_which(cmd):
        mapping = {
            "apt-get": "/usr/bin/apt-get",
            "dpkg-query": "/usr/bin/dpkg-query",
            "sudo": "/usr/bin/sudo",
        }
        return mapping.get(cmd)

    monkeypatch.setattr(shutil, "which", fake_which)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)

    def fake_run(cmd, check, capture_output, text, timeout):
        assert cmd[0].endswith("sudo")
        assert cmd[1] == "apt-get"
        assert cmd[2:] == ["install", "-y", "git"]
        return _Completed(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = skill.execute("install", {"package": "git", "confirmed": True})

    assert result.success
    assert result.data["action"] == "install"


def test_package_invalid_name_rejected():
    skill = PackageManagerSkill()

    result = skill.execute("resolve", {"package": "git; rm -rf /"})

    assert not result.success
    assert result.error_code == "MISSING_PACKAGE"


def test_package_blocklist_enforced(monkeypatch):
    monkeypatch.setenv("AEGIS_PACKAGE_BLOCKLIST", "docker.io")
    skill = PackageManagerSkill()

    result = skill.execute("install", {"package": "docker", "confirmed": True})

    assert not result.success
    assert result.error_code == "PACKAGE_BLOCKED"


def test_package_allowlist_enforced(monkeypatch):
    monkeypatch.setenv("AEGIS_PACKAGE_ALLOWLIST", "git,python3")
    skill = PackageManagerSkill()

    result = skill.execute("remove", {"package": "nodejs", "confirmed": True})

    assert not result.success
    assert result.error_code == "PACKAGE_NOT_ALLOWED"
