"""Small HTTP client helpers for Aegis desktop UI apps."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib import error, parse, request


@dataclass
class ApiError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


class AegisApiClient:
    def __init__(self, api_base_url: str = "http://127.0.0.1:8000"):
        self.api_base_url = api_base_url.rstrip("/")

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Dict[str, Any]:
        query = ""
        if params:
            query = "?" + parse.urlencode(params)
        return self._request("GET", f"{path}{query}", payload=None, timeout=timeout)

    def post(self, path: str, payload: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
        return self._request("POST", path, payload=payload, timeout=timeout)

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]], timeout: int) -> Dict[str, Any]:
        req = request.Request(
            f"{self.api_base_url}{path}",
            method=method,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise ApiError(f"HTTP {exc.code} for {path}: {detail or exc.reason}") from exc
        except (error.URLError, TimeoutError) as exc:
            raise ApiError(f"Request failed for {path}: {exc}") from exc

        if not body:
            return {}

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ApiError(f"Invalid JSON response for {path}") from exc

        if not isinstance(parsed, dict):
            raise ApiError(f"Unexpected response payload for {path}")
        return parsed
