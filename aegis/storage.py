from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict


class StateStorage(ABC):
    """Storage abstraction for system state to support testability and future backends."""

    @abstractmethod
    def read(self) -> Dict[str, Any]:
        ...

    @abstractmethod
    def write(self, state: Dict[str, Any]) -> None:
        ...


class FileStateStorage(StateStorage):
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> Dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError
        with self.path.open("r", encoding="utf-8") as f:
            import json
            return json.load(f)

    def write(self, state: Dict[str, Any]) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            import json
            json.dump(state, f, indent=2)


class InMemoryStateStorage(StateStorage):
    def __init__(self, initial_state: Dict[str, Any] = None):
        self._state = initial_state or {}

    def read(self) -> Dict[str, Any]:
        return self._state.copy()

    def write(self, state: Dict[str, Any]) -> None:
        self._state = state.copy()
