import re
import urllib.parse
import urllib.request
from html import unescape
from typing import Any, Dict, List

from ..result import SkillResult
from ..skill import Skill


class WebSearchSkill(Skill):
    name = "web_search"
    tier = 2

    DUCKDUCKGO_HTML = "https://duckduckgo.com/html/"

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action != "search":
            return SkillResult.fail(f"Unsupported action: {action}")

        query = params.get("query")
        limit = int(params.get("limit", 5))
        if not query:
            return SkillResult.fail("'query' parameter is required")

        limit = max(1, min(limit, 20))
        return self.search(query, limit)

    def get_permissions(self) -> List[str]:
        return ["network"]

    def search(self, query: str, limit: int) -> SkillResult:
        encoded = urllib.parse.urlencode({"q": query})
        url = f"{self.DUCKDUCKGO_HTML}?{encoded}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AegisOS/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            return SkillResult.fail(f"Search request failed: {exc}")

        pattern = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
        items = []

        for href, title_html in pattern.findall(html):
            title = re.sub(r"<.*?>", "", title_html)
            title = unescape(title).strip()
            href = unescape(href)
            if title and href:
                items.append({"title": title, "url": href})
            if len(items) >= limit:
                break

        return SkillResult.ok({"query": query, "results": items})
