import re
import urllib.request
import webbrowser
from html import unescape
from typing import Any, Dict, List

from ..result import SkillResult
from ..skill import Skill


class BrowserSkill(Skill):
    name = "browser"
    tier = 2

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action == "open_url":
            return self.open_url(params.get("url"))
        if action == "fetch_text":
            return self.fetch_text(params.get("url"), int(params.get("max_chars", 4000)))
        if action == "extract_links":
            return self.extract_links(params.get("url"), int(params.get("limit", 20)))

        return SkillResult.fail(f"Unsupported action: {action}")

    def get_permissions(self) -> List[str]:
        return ["network", "browser"]

    def open_url(self, url: str | None) -> SkillResult:
        if not url:
            return SkillResult.fail("'url' parameter is required")
        try:
            ok = webbrowser.open(url)
            return SkillResult.ok({"url": url, "opened": bool(ok)})
        except Exception as exc:
            return SkillResult.fail(str(exc))

    def fetch_text(self, url: str | None, max_chars: int) -> SkillResult:
        if not url:
            return SkillResult.fail("'url' parameter is required")

        max_chars = max(200, min(max_chars, 50000))

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AegisOS/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            return SkillResult.fail(f"Fetch failed: {exc}")

        text = re.sub(r"<script[\\s\\S]*?</script>", " ", html, flags=re.IGNORECASE)
        text = re.sub(r"<style[\\s\\S]*?</style>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = unescape(text)
        text = re.sub(r"\\s+", " ", text).strip()

        return SkillResult.ok({"url": url, "text": text[:max_chars]})

    def extract_links(self, url: str | None, limit: int) -> SkillResult:
        if not url:
            return SkillResult.fail("'url' parameter is required")

        limit = max(1, min(limit, 200))

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AegisOS/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            return SkillResult.fail(f"Fetch failed: {exc}")

        links = []
        for href in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
            href = unescape(href).strip()
            if href:
                links.append(href)
            if len(links) >= limit:
                break

        return SkillResult.ok({"url": url, "links": links})
