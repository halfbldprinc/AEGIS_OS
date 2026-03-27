import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from ..result import SkillResult
from ..skill import Skill
from .action_schema import ActionSchema, ParamSpec


class HttpSkill(Skill):
    """Safe HTTP client skill for API integration and diagnostics."""

    name = "http"
    tier = 2
    allowed_actions = {"request"}

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action != "request":
            return SkillResult.fail(f"Unsupported action: {action}", error_code="UNSUPPORTED_ACTION")

        method = str(params.get("method", "GET")).upper()
        url = str(params.get("url", "")).strip()
        headers = params.get("headers", {}) or {}
        body = params.get("body")
        timeout = max(1, min(int(params.get("timeout", 15)), 120))
        max_bytes = max(1024, min(int(params.get("max_bytes", 1024 * 1024)), 2 * 1024 * 1024))

        if not url:
            return SkillResult.fail("'url' parameter is required", error_code="MISSING_URL")

        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return SkillResult.fail("Only http/https URLs are allowed", error_code="UNSUPPORTED_URL_SCHEME")

        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
            return SkillResult.fail(f"Unsupported HTTP method: {method}", error_code="UNSUPPORTED_HTTP_METHOD")

        data = None
        if body is not None:
            if isinstance(body, str):
                data = body.encode("utf-8")
            else:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers = dict(headers)
                headers.setdefault("Content-Type", "application/json")

        req = urllib.request.Request(url=url, method=method, headers=dict(headers), data=data)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status = int(getattr(response, "status", response.getcode()))
                content_type = str(response.headers.get("Content-Type", ""))
                raw = response.read(max_bytes + 1)

            truncated = len(raw) > max_bytes
            if truncated:
                raw = raw[:max_bytes]

            text = raw.decode("utf-8", errors="replace")
            payload: Dict[str, Any] = {
                "url": url,
                "method": method,
                "status": status,
                "content_type": content_type,
                "headers": dict(response.headers.items()),
                "truncated": truncated,
                "body_text": text,
            }

            if "application/json" in content_type.lower():
                try:
                    payload["body_json"] = json.loads(text)
                except Exception:
                    payload["body_json"] = None

            if 200 <= status < 400:
                return SkillResult.ok(payload)
            return SkillResult.fail(
                f"HTTP request failed with status {status}",
                data=payload,
                error_code="HTTP_STATUS_ERROR",
            )

        except urllib.error.HTTPError as exc:
            return SkillResult.fail(f"HTTP error {exc.code}: {exc.reason}", error_code="HTTP_ERROR")
        except urllib.error.URLError as exc:
            return SkillResult.fail(f"Request failed: {exc.reason}", error_code="NETWORK_ERROR")
        except Exception as exc:
            return SkillResult.fail(str(exc), error_code="REQUEST_EXECUTION_ERROR")

    def get_permissions(self) -> List[str]:
        return ["network"]

    def get_timeout(self, action: str) -> int:
        return 30

    def get_action_schemas(self) -> Dict[str, ActionSchema]:
        return {
            "request": ActionSchema(
                params={
                    "url": ParamSpec("url", str, required=True, min_length=8, max_length=4096),
                    "method": ParamSpec(
                        "method",
                        str,
                        required=False,
                        choices={"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "get", "post", "put", "patch", "delete", "head"},
                    ),
                    "headers": ParamSpec("headers", dict, required=False),
                    "body": ParamSpec("body", (dict, list, str), required=False),
                    "timeout": ParamSpec("timeout", int, required=False, min_value=1, max_value=120),
                    "max_bytes": ParamSpec("max_bytes", int, required=False, min_value=1024, max_value=2 * 1024 * 1024),
                },
                allow_extra=True,
            )
        }
