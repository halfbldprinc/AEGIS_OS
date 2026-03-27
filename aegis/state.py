from pathlib import Path
from typing import Any, Dict, Optional

from .storage import FileStateStorage, StateStorage

STATE_PATH = Path("/var/lib/aegis/state.json")
LOCAL_FALLBACK_STATE_PATH = Path(".aegis/state.json")
DEFAULT_STATE: Dict[str, Any] = {
    "mode": "OBSERVATION_MODE",
    "day": 1,
    "trust": {},
}


class SystemState:
    """Represents persistent system state for cold-start and mode transitions."""

    def __init__(
        self,
        storage: Optional[StateStorage] = None,
        path: Optional[Path] = None,
    ):  # pragma: no cover
        from os import getenv

        env_path = getenv("AEGIS_STATE_PATH")
        final_path = Path(env_path) if env_path else (path or STATE_PATH)

        if storage is not None:
            self.storage = storage
            self.path = getattr(storage, "path", final_path)
        else:
            self.path = final_path
            try:
                self.storage = FileStateStorage(self.path)
            except PermissionError:
                # Fallback to local workspace storage if /var is not writable.
                self.path = LOCAL_FALLBACK_STATE_PATH
                self.storage = FileStateStorage(self.path)

        self._state: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        try:
            self._state = self.storage.read()
        except FileNotFoundError:
            self._state = dict(DEFAULT_STATE)
            self.save()
        except PermissionError:
            # For development / test environments without /var permissions
            self._switch_to_fallback_storage()
            self._state = dict(DEFAULT_STATE)
            self.save()

    def save(self) -> None:
        try:
            self.storage.write(self._state)
        except PermissionError:
            self._switch_to_fallback_storage()
            self.storage.write(self._state)

    def _switch_to_fallback_storage(self) -> None:
        self.path = LOCAL_FALLBACK_STATE_PATH
        self.storage = FileStateStorage(self.path)

    def get(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._state[key] = value
        self.save()

    def increment(self, key: str, step: int = 1) -> int:
        value = self._state.get(key, 0)
        if not isinstance(value, int):
            raise ValueError(f"State key {key} is not an integer")
        value += step
        self._state[key] = value
        self.save()
        return value

