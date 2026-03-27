from aegis.orchestrator import container_security


def test_inspect_repo_digests_handles_invalid_json(monkeypatch):
    class _Completed:
        returncode = 0
        stdout = "not-json"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _Completed())
    assert container_security.inspect_repo_digests("podman", "python:3.14-slim") == []


def test_vulnerability_scan_invalid_json_sets_unknown(monkeypatch):
    class _Completed:
        returncode = 0
        stdout = "{"

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/trivy" if name == "trivy" else None)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _Completed())

    out = container_security.vulnerability_scan("python:3.14-slim")
    assert out["status"] == "unknown"
