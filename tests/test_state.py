from pathlib import Path
import pytest

from aegis.state import SystemState
from aegis.storage import FileStateStorage, InMemoryStateStorage


def test_system_state_in_memory_storage_behaves_like_file_backed_state():
    storage = InMemoryStateStorage()
    state = SystemState(storage=storage)

    assert state.get("mode") in {None, "OBSERVATION_MODE"}

    state.set("mode", "ACTIVE_MODE")
    assert state.get("mode") == "ACTIVE_MODE"

    restored = SystemState(storage=storage)
    assert restored.get("mode") == "ACTIVE_MODE"


def test_system_state_file_storage_roundtrip(tmp_path: Path):
    storage = FileStateStorage(tmp_path / "state.json")
    state = SystemState(storage=storage)

    assert state.get("mode") == "OBSERVATION_MODE"
    assert state.get("day") == 1

    state.set("mode", "ACTIVE_SHADOW_MODE")
    state.set("day", 10)

    loaded = SystemState(storage=storage)
    assert loaded.get("mode") == "ACTIVE_SHADOW_MODE"
    assert loaded.get("day") == 10


def test_system_state_save_permission_error_switches_to_local_fallback(monkeypatch, tmp_path: Path):
    class FlakyStorage(InMemoryStateStorage):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def write(self, state):
            self.calls += 1
            if self.calls == 1:
                raise PermissionError("denied")
            return super().write(state)

    storage = FlakyStorage()
    state = SystemState(storage=storage)

    monkeypatch.chdir(tmp_path)
    state.set("mode", "ACTIVE_MODE")

    assert state.path == Path(".aegis/state.json")
    assert state.get("mode") == "ACTIVE_MODE"
