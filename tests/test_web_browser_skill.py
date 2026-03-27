from aegis.skills.web_search_skill import WebSearchSkill
from aegis.skills.browser_skill import BrowserSkill


def test_web_search_skill(monkeypatch):
    html = '<html><body><a class="result__a" href="https://example.com">Example Result</a></body></html>'

    class DummyResp:
        def read(self):
            return html.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: DummyResp())

    skill = WebSearchSkill()
    result = skill.execute("search", {"query": "example", "limit": 3})
    assert result.success
    assert result.data["results"][0]["url"] == "https://example.com"


def test_browser_fetch_and_links(monkeypatch):
    html = '<html><body><a href="https://a.com">A</a><p>Hello world</p></body></html>'

    class DummyResp:
        def read(self):
            return html.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: DummyResp())

    skill = BrowserSkill()
    fetched = skill.execute("fetch_text", {"url": "https://example.com"})
    assert fetched.success
    assert "Hello world" in fetched.data["text"]

    links = skill.execute("extract_links", {"url": "https://example.com", "limit": 5})
    assert links.success
    assert "https://a.com" in links.data["links"]
