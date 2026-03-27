import json
import os
import hmac
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional


class SkillRegistry:
    """Registry for skill metadata and trusted tier info."""

    DEFAULT_PATH = os.getenv("AEGIS_SKILL_METADATA", "/etc/aegis/skills.json")

    def __init__(self, path: Optional[str] = None):
        self.path = path or self.DEFAULT_PATH
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self._data = loaded if isinstance(loaded, dict) else {}
            else:
                self._data = {}
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def _save(self) -> None:
        try:
            parent = Path(self.path).parent
            parent.mkdir(parents=True, exist_ok=True)
            tmp_path = f"{self.path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp_path, self.path)
        except OSError:
            return

    def register(
        self,
        name: str,
        tier: int,
        permissions: Optional[List[str]] = None,
        hash_value: Optional[str] = None,
        trusted_builtin: bool = True,
    ) -> None:
        permissions = permissions or []
        computed_hash = hash_value or self._compute_hash(name, tier, permissions)
        record = {
            "name": name,
            "tier": tier,
            "permissions": permissions,
            "hash": computed_hash,
            "trusted_builtin": trusted_builtin,
        }
        self._data[name] = record
        self._save()

    def register_external(self, name: str, tier: int, permissions: Optional[List[str]] = None, hash_value: Optional[str] = None) -> None:
        self.register(name=name, tier=tier, permissions=permissions, hash_value=hash_value, trusted_builtin=False)

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self._data.get(name)

    def list(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._data)

    def _compute_hash(self, name: str, tier: int, permissions: List[str]) -> str:
        payload = json.dumps({"name": name, "tier": tier, "permissions": sorted(permissions)}, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def verify_signature(self, name: str, signature: Optional[str]) -> bool:
        record = self._data.get(name)
        if record is None:
            return False

        # Reject tampered metadata before signature validation.
        recomputed = self._compute_hash(record.get("name", ""), int(record.get("tier", 0)), list(record.get("permissions", [])))
        if not hmac.compare_digest(str(record.get("hash", "")), recomputed):
            return False

        # First-party built-in skills can run unsigned only when explicitly allowed.
        if signature is None:
            allow_unsigned_builtins = os.getenv("AEGIS_ALLOW_UNSIGNED_BUILTINS", "1") == "1"
            return bool(record.get("trusted_builtin", False)) and allow_unsigned_builtins

        key = os.getenv("AEGIS_SKILL_SIGNING_KEY")
        if not key:
            return False

        expected = hmac.new(
            key.encode("utf-8"),
            str(record.get("hash", "")).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)
