import json

from aegis.skills.http_skill import HttpSkill


class DummyResponse:
    def __init__(self, status=200, body=b"{}", headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {"Content-Type": "application/json"}

    def read(self, amount=-1):
        if amount is None or amount < 0:
            return self._body
        return self._body[:amount]

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_http_skill_get_json(monkeypatch):
    def fake_urlopen(req, timeout=0):
        assert req.full_url == "https://example.com/api"
        return DummyResponse(body=json.dumps({"ok": True}).encode("utf-8"))

    monkeypatch.setattr("aegis.skills.http_skill.urllib.request.urlopen", fake_urlopen)

    skill = HttpSkill()
    result = skill.execute("request", {"url": "https://example.com/api", "method": "GET"})

    assert result.success
    assert result.data["status"] == 200
    assert result.data["body_json"] == {"ok": True}


def test_http_skill_blocks_non_http_scheme():
    skill = HttpSkill()
    result = skill.execute("request", {"url": "file:///etc/passwd", "method": "GET"})
    assert not result.success
    assert "http/https" in (result.error or "")


def test_http_skill_rejects_unknown_method():
    skill = HttpSkill()
    result = skill.execute("request", {"url": "https://example.com", "method": "TRACE"})
    assert not result.success
    assert "Unsupported HTTP method" in (result.error or "")
