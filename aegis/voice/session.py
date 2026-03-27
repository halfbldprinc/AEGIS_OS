from dataclasses import dataclass
from time import sleep
from typing import Callable, Dict, Any, Optional

from .microphone import CommandMicrophoneSource
from .wakeword import WakeWordDetector
from .stt import STTEngine
from .tts import TTSEngine


@dataclass
class VoiceSessionManager:
    stt: STTEngine
    tts: TTSEngine
    wakeword: WakeWordDetector
    process_text: Callable[[str], Dict[str, Any]]
    microphone_source: Optional[CommandMicrophoneSource] = None

    def __post_init__(self) -> None:
        self._interrupt_requested = False
        self._streaming = False
        if self.microphone_source is None:
            self.microphone_source = CommandMicrophoneSource()

    def handle_audio(self, audio_path: str) -> Dict[str, Any]:
        transcript = self.stt.transcribe(audio_path)
        if not self.wakeword.detect(transcript):
            return {"wakeword": False, "transcript": transcript}

        response = self.process_text(transcript)
        spoken = response.get("spoken") or response.get("text") or "Done"
        self.tts.speak(str(spoken))

        return {
            "wakeword": True,
            "transcript": transcript,
            "response": response,
        }

    def listen(self) -> str | None:
        """Capture one audio chunk from the configured microphone backend."""
        if self.microphone_source is None:
            return None
        return self.microphone_source.capture()

    @property
    def is_streaming(self) -> bool:
        return self._streaming

    def interrupt(self) -> None:
        self._interrupt_requested = True

    def reset_interrupt(self) -> None:
        self._interrupt_requested = False

    def stream_loop(
        self,
        audio_source: Optional[Callable[[], Optional[str]]] = None,
        wakeword_required: bool = True,
        poll_interval: float = 0.05,
        max_iterations: Optional[int] = None,
        on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> list[Dict[str, Any]]:
        source = audio_source or self.listen
        events: list[Dict[str, Any]] = []
        iterations = 0
        self.reset_interrupt()
        self._streaming = True

        try:
            while not self._interrupt_requested:
                if max_iterations is not None and iterations >= max_iterations:
                    break
                iterations += 1

                audio_path = source()
                if not audio_path:
                    sleep(poll_interval)
                    continue

                try:
                    transcript = self.stt.transcribe(audio_path)
                    if wakeword_required and not self.wakeword.detect(transcript):
                        event = {"wakeword": False, "transcript": transcript}
                    else:
                        response = self.process_text(transcript)
                        spoken = response.get("spoken") or response.get("text") or "Done"
                        self.tts.speak(str(spoken))
                        event = {"wakeword": True, "transcript": transcript, "response": response}
                except Exception as exc:
                    event = {
                        "wakeword": False,
                        "error": str(exc),
                        "stage": "voice_pipeline",
                    }

                events.append(event)
                if on_result is not None:
                    on_result(event)

                sleep(poll_interval)
        finally:
            self._streaming = False

        return events
