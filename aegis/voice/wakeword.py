from dataclasses import dataclass


@dataclass
class WakeWordDetector:
    wake_phrase: str = "aegis"

    def detect(self, transcript: str) -> bool:
        if not transcript:
            return False
        return self.wake_phrase.lower() in transcript.lower()
