from aegis.voice.session import VoiceSessionManager
from aegis.voice.stt import STTEngine
from aegis.voice.tts import TTSEngine
from aegis.voice.wakeword import WakeWordDetector


class QueueSTT(STTEngine):
    def __init__(self, transcripts: dict[str, str]):
        self.transcripts = transcripts

    def transcribe(self, audio_path: str, model_path: str | None = None) -> str:
        return self.transcripts[audio_path]


class RecordingTTS(TTSEngine):
    def __init__(self):
        self.spoken: list[str] = []

    def speak(self, text: str, voice: str | None = None) -> None:
        self.spoken.append(text)


def test_stream_loop_processes_audio_and_speaks():
    stt = QueueSTT({"a1": "aegis status", "a2": "aegis hello"})
    tts = RecordingTTS()
    events_seen = []

    queue = ["a1", "a2", None]

    def source():
        return queue.pop(0) if queue else None

    def process_text(transcript: str):
        return {"spoken": f"ok:{transcript}"}

    manager = VoiceSessionManager(
        stt=stt,
        tts=tts,
        wakeword=WakeWordDetector("aegis"),
        process_text=process_text,
    )

    events = manager.stream_loop(audio_source=source, poll_interval=0.0, max_iterations=4, on_result=events_seen.append)

    assert len(events) == 2
    assert len(events_seen) == 2
    assert all(event["wakeword"] for event in events)
    assert tts.spoken == ["ok:aegis status", "ok:aegis hello"]
    assert manager.is_streaming is False


def test_stream_loop_interrupt_stops_processing():
    stt = QueueSTT({"a1": "aegis do something"})
    tts = RecordingTTS()

    def source():
        return "a1"

    manager = VoiceSessionManager(
        stt=stt,
        tts=tts,
        wakeword=WakeWordDetector("aegis"),
        process_text=lambda transcript: {"spoken": f"done:{transcript}"},
    )

    def on_result(_event):
        manager.interrupt()

    events = manager.stream_loop(audio_source=source, poll_interval=0.0, max_iterations=50, on_result=on_result)

    assert len(events) == 1
    assert tts.spoken == ["done:aegis do something"]
    assert manager.is_streaming is False


def test_stream_loop_continues_after_pipeline_error():
    class FlakySTT(STTEngine):
        def __init__(self):
            self.calls = 0

        def transcribe(self, audio_path: str, model_path: str | None = None) -> str:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary stt failure")
            return "aegis recovered"

    stt = FlakySTT()
    tts = RecordingTTS()
    queue = ["a1", "a2", None]

    def source():
        return queue.pop(0) if queue else None

    manager = VoiceSessionManager(
        stt=stt,
        tts=tts,
        wakeword=WakeWordDetector("aegis"),
        process_text=lambda transcript: {"spoken": f"ok:{transcript}"},
    )

    events = manager.stream_loop(audio_source=source, poll_interval=0.0, max_iterations=4)

    assert len(events) == 2
    assert events[0]["stage"] == "voice_pipeline"
    assert "temporary stt failure" in events[0]["error"]
    assert events[1]["wakeword"] is True
    assert tts.spoken == ["ok:aegis recovered"]
