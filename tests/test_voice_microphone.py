import subprocess

from aegis.voice.microphone import CommandMicrophoneSource
from aegis.voice.session import VoiceSessionManager
from aegis.voice.stt import STTEngine
from aegis.voice.tts import TTSEngine
from aegis.voice.wakeword import WakeWordDetector


class DummySTT(STTEngine):
    def transcribe(self, audio_path: str, model_path: str | None = None) -> str:
        return "aegis hello"


class DummyTTS(TTSEngine):
    def __init__(self):
        self.spoken = []

    def speak(self, text: str, voice: str | None = None) -> None:
        self.spoken.append(text)


class FakeMic:
    def __init__(self, path: str | None):
        self.path = path

    def capture(self):
        return self.path


def test_command_microphone_source_returns_none_without_backend(monkeypatch, tmp_path):
    source = CommandMicrophoneSource(chunk_seconds=1.0, output_dir=str(tmp_path))
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert source.capture() is None


def test_microphone_vad_rejects_silence(monkeypatch, tmp_path):
    source = CommandMicrophoneSource(chunk_seconds=1.0, output_dir=str(tmp_path))

    wav = tmp_path / "silent.wav"
    wav.write_bytes(b"RIFF")

    monkeypatch.setattr(source, "_build_command", lambda out_path: ["dummy"]) 

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Completed())
    monkeypatch.setattr(source, "_has_voice_activity", lambda path: False)
    monkeypatch.setattr("os.path.exists", lambda path: True)
    monkeypatch.setattr("os.path.getsize", lambda path: 10)

    assert source.capture() is None


def test_microphone_capture_timeout_returns_none(monkeypatch, tmp_path):
    source = CommandMicrophoneSource(chunk_seconds=1.0, output_dir=str(tmp_path))
    monkeypatch.setattr(source, "_build_command", lambda out_path: ["dummy"])

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="dummy", timeout=1)

    monkeypatch.setattr("subprocess.run", _raise_timeout)
    assert source.capture() is None


def test_voice_session_listen_uses_microphone_source(tmp_path):
    wav = tmp_path / "chunk.wav"
    wav.write_bytes(b"RIFF0000WAVE")

    session = VoiceSessionManager(
        stt=DummySTT(),
        tts=DummyTTS(),
        wakeword=WakeWordDetector("aegis"),
        process_text=lambda text: {"spoken": text},
        microphone_source=FakeMic(str(wav)),
    )

    assert session.listen() == str(wav)


def test_voice_session_stream_loop_with_real_listen_backend(tmp_path):
    wav = tmp_path / "chunk.wav"
    wav.write_bytes(b"RIFF0000WAVE")

    tts = DummyTTS()
    session = VoiceSessionManager(
        stt=DummySTT(),
        tts=tts,
        wakeword=WakeWordDetector("aegis"),
        process_text=lambda text: {"spoken": f"ok:{text}"},
        microphone_source=FakeMic(str(wav)),
    )

    events = session.stream_loop(audio_source=session.listen, poll_interval=0.0, max_iterations=1)

    assert len(events) == 1
    assert events[0]["wakeword"] is True
    assert tts.spoken == ["ok:aegis hello"]
