import os
import shutil
import subprocess
import sys


class TTSEngine:
    def __init__(self, timeout_seconds: int | None = None):
        configured = timeout_seconds if timeout_seconds is not None else int(os.getenv("AEGIS_TTS_TIMEOUT", "15"))
        self.timeout_seconds = max(1, int(configured))

    def _run_tts_command(self, cmd: list[str]) -> None:
        try:
            result = subprocess.run(cmd, check=False, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"TTS backend timed out after {self.timeout_seconds}s") from exc
        except OSError as exc:
            raise RuntimeError(f"Failed to execute TTS backend: {exc}") from exc

        if result.returncode != 0:
            raise RuntimeError(f"TTS backend failed with exit code {result.returncode}")

    def speak(self, text: str, voice: str | None = None) -> None:
        if not text:
            return

        if sys.platform == "darwin":
            if not shutil.which("say"):
                raise RuntimeError("No local TTS backend available (say)")
            cmd = ["say"]
            if voice:
                cmd.extend(["-v", voice])
            cmd.append(text)
            self._run_tts_command(cmd)
            return

        if sys.platform.startswith("linux"):
            if shutil.which("espeak"):
                self._run_tts_command(["espeak", text])
                return
            if shutil.which("spd-say"):
                self._run_tts_command(["spd-say", text])
                return

        raise RuntimeError("No local TTS backend available")
