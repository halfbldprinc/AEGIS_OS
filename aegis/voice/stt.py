import os
import shutil
import subprocess
from pathlib import Path


class STTEngine:
    def __init__(self, timeout_seconds: int | None = None):
        configured = timeout_seconds if timeout_seconds is not None else int(os.getenv("AEGIS_STT_TIMEOUT", "300"))
        self.timeout_seconds = max(5, int(configured))

    def transcribe(self, audio_path: str, model_path: str | None = None) -> str:
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        whisper = shutil.which("whisper-cli") or shutil.which("whisper")
        if not whisper:
            raise RuntimeError("No local STT backend available (whisper-cli/whisper)")

        cmd = [whisper, str(path)]
        if model_path:
            cmd.extend(["-m", model_path])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"STT backend timed out after {self.timeout_seconds}s") from exc
        except OSError as exc:
            raise RuntimeError(f"Failed to execute STT backend: {exc}") from exc

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "STT command failed")

        text = result.stdout.strip()
        if not text:
            raise RuntimeError("No transcript produced")
        return text
