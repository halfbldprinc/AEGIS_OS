import json

from aegis.orchestrator.container_runner import ContainerizedRunner


class _Completed:
    def __init__(self, returncode=0, stdout='{"success": true, "data": {"ok": true}}', stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_container_runner_rejects_unallowlisted_image():
    runner = ContainerizedRunner(image_tag="untrusted/image:latest")
    runner._detect_runtime = lambda: "/usr/bin/podman"
    result = runner.run("echo", "echo", {"message": "hi"})
    assert result.success is False
    assert "provenance" in (result.error or "").lower()


def test_container_runner_builds_strict_sandbox_command(monkeypatch, tmp_path):
    seen_cmd = {}

    runner = ContainerizedRunner(image_tag="python:3.14-slim", sandbox_root=str(tmp_path / "sandbox"))

    monkeypatch.setattr(runner, "_detect_runtime", lambda: "/usr/bin/podman")

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "/usr/bin/podman" and cmd[1] == "run":
            seen_cmd["cmd"] = cmd
            return _Completed()
        if isinstance(cmd, list) and len(cmd) >= 3 and cmd[1] == "image" and cmd[2] == "inspect":
            return _Completed(stdout=json.dumps(["python@sha256:abc"]))
        return _Completed()

    monkeypatch.setattr("subprocess.run", fake_run)

    result = runner.run("echo", "echo", {"message": "hi"})
    assert result.success is True

    cmd = seen_cmd["cmd"]
    assert "--read-only" in cmd
    assert "--cap-drop=ALL" in cmd
    assert any(item.startswith("--pids-limit=") for item in cmd)
    assert any("seccomp=" in item for item in cmd)


def test_container_runner_digest_policy_with_expected_digest(monkeypatch):
    runner = ContainerizedRunner(image_tag="python:3.14-slim")

    monkeypatch.setenv("AEGIS_IMAGE_DIGESTS", json.dumps({"python:3.14-slim": "sha256:expected"}))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/podman")
    monkeypatch.setattr(runner, "_inspect_repo_digests", lambda runtime, image: ["python@sha256:unexpected"])

    assert runner.verify_image_provenance("python:3.14-slim") is False


def test_container_runner_strict_provenance_requires_digest_policy(monkeypatch):
    runner = ContainerizedRunner(image_tag="python:3.14-slim")
    monkeypatch.setenv("AEGIS_STRICT_PROVENANCE", "1")
    monkeypatch.delenv("AEGIS_IMAGE_DIGESTS", raising=False)

    assert runner.verify_image_provenance("python:3.14-slim") is False


def test_container_runner_cosign_required_without_binary_fails(monkeypatch):
    runner = ContainerizedRunner(image_tag="python:3.14-slim")
    monkeypatch.setenv("AEGIS_REQUIRE_COSIGN", "1")
    monkeypatch.setattr("shutil.which", lambda name: None if name == "cosign" else "/usr/bin/podman")

    assert runner.verify_image_provenance("python:3.14-slim") is False
