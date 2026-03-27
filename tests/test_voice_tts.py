import subprocess

import pytest

from aegis.voice.tts import TTSEngine


class _Completed:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode


def test_tts_linux_backend_failure_raises(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/espeak" if name == "espeak" else None)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _Completed(returncode=1))

    tts = TTSEngine(timeout_seconds=1)
    with pytest.raises(RuntimeError, match="exit code 1"):
        tts.speak("hello")


def test_tts_timeout_raises(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/espeak" if name == "espeak" else None)

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="espeak", timeout=1)

    monkeypatch.setattr("subprocess.run", _raise_timeout)

    tts = TTSEngine(timeout_seconds=1)
    with pytest.raises(RuntimeError, match="timed out"):
        tts.speak("hello")
