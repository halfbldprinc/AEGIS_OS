import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class UpdateRecord:
    component: str
    version: str
    source: str
    applied_at: float


class UpdateManager:
    """Tracks OS/agent/model versions and available updates separately."""

    def __init__(self, state_path: str = "~/.aegis/update_state.json"):
        self.state_path = Path(state_path).expanduser()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._state: Dict[str, Any] = {
            "current": {"os": "0.1.0", "agent": "0.1.0", "model": "unknown"},
            "available": {},
            "history": [],
        }
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._state["current"] = dict(raw.get("current", self._state["current"]))
                self._state["available"] = dict(raw.get("available", {}))
                self._state["history"] = list(raw.get("history", []))
        except (OSError, json.JSONDecodeError):
            return

    def _save(self) -> None:
        self.state_path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    @staticmethod
    def _normalize_component(component: str) -> str:
        value = (component or "").strip().lower()
        if value not in {"os", "agent", "model"}:
            raise ValueError("component must be one of: os, agent, model")
        return value

    def status(self) -> Dict[str, Any]:
        with self._lock:
            current = dict(self._state["current"])
            available = dict(self._state["available"])
            pending = []
            for component, metadata in available.items():
                if not isinstance(metadata, dict):
                    continue
                next_version = str(metadata.get("version", ""))
                if next_version and current.get(component) != next_version:
                    pending.append(
                        {
                            "component": component,
                            "current_version": current.get(component),
                            "available_version": next_version,
                            "channel": metadata.get("channel", "stable"),
                            "notes": metadata.get("notes", ""),
                        }
                    )
            return {
                "current": current,
                "available": available,
                "pending_updates": pending,
                "history": list(self._state["history"]),
            }

    def set_available_update(
        self,
        component: str,
        version: str,
        channel: str = "stable",
        notes: str = "",
    ) -> Dict[str, Any]:
        normalized_component = self._normalize_component(component)
        if not version:
            raise ValueError("version is required")
        with self._lock:
            self._state["available"][normalized_component] = {
                "version": str(version),
                "channel": str(channel or "stable"),
                "notes": str(notes or ""),
                "published_at": time.time(),
            }
            self._save()
            return dict(self._state["available"][normalized_component])

    def apply_update(self, component: str, version: str, source: str = "manual") -> Dict[str, Any]:
        normalized_component = self._normalize_component(component)
        if not version:
            raise ValueError("version is required")

        with self._lock:
            self._state["current"][normalized_component] = str(version)
            available = self._state["available"].get(normalized_component)
            if isinstance(available, dict) and str(available.get("version", "")) == str(version):
                self._state["available"].pop(normalized_component, None)

            record = UpdateRecord(
                component=normalized_component,
                version=str(version),
                source=str(source or "manual"),
                applied_at=time.time(),
            )
            self._state["history"].append(record.__dict__)
            self._state["history"] = self._state["history"][-200:]
            self._save()
            return record.__dict__.copy()
