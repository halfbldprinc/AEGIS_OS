import os
import platform
import shutil
import subprocess
import time
import wave
from math import sqrt
from pathlib import Path
from tempfile import mkdtemp
from typing import Optional


class CommandMicrophoneSource:
    """Chunked microphone capture backend using local command-line tools.

    Captures short WAV chunks that can be transcribed by STT engines in a
    continuous loop. This is local-only and does not require network services.
    """

    def __init__(self, chunk_seconds: float = 2.0, output_dir: Optional[str] = None):
        self.chunk_seconds = max(0.5, float(chunk_seconds))
        self.output_dir = output_dir or mkdtemp(prefix="aegis-mic-")
        self.vad_min_rms = float(os.getenv("AEGIS_VAD_MIN_RMS", "200"))
        self.capture_timeout_seconds = max(
            2,
            int(os.getenv("AEGIS_VOICE_CAPTURE_TIMEOUT", str(max(10, int(self.chunk_seconds) + 5)))),
        )
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def _has_voice_activity(self, wav_path: str) -> bool:
        try:
            with wave.open(wav_path, "rb") as wf:
                n_frames = wf.getnframes()
                if n_frames <= 0:
                    return False
                raw = wf.readframes(n_frames)
                sample_width = wf.getsampwidth()
                if sample_width != 2:
                    # For non-16bit formats, keep chunk to avoid false negatives.
                    return True

                if len(raw) < 2:
                    return False

                count = len(raw) // 2
                if count == 0:
                    return False

                total_sq = 0.0
                for i in range(0, len(raw), 2):
                    sample = int.from_bytes(raw[i:i + 2], byteorder="little", signed=True)
                    total_sq += float(sample * sample)
                rms = sqrt(total_sq / count)
                return rms >= self.vad_min_rms
        except Exception:
            return True

    def _build_command(self, out_path: str, duration_seconds: Optional[float] = None) -> Optional[list[str]]:
        duration = str(max(0.2, float(duration_seconds if duration_seconds is not None else self.chunk_seconds)))
        system_name = platform.system()
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "avfoundation" if system_name == "Darwin" else "alsa",
                "-i",
                ":0" if system_name == "Darwin" else "default",
                "-t",
                duration,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-y",
                out_path,
            ]

        arecord = shutil.which("arecord")
        if arecord:
            return [
                arecord,
                "-d",
                str(max(1, int(float(duration)))),
                "-f",
                "S16_LE",
                "-r",
                "16000",
                "-c",
                "1",
                out_path,
            ]

        rec = shutil.which("rec")
        if rec:
            return [rec, out_path, "trim", "0", duration]

        return None

    def backend_status(self) -> tuple[bool, str]:
        """Return whether microphone capture backend is operational.

        This is a lightweight startup probe used to decide whether to run
        voice monitoring or a text-command fallback loop.
        """

        probe_path = str(Path(self.output_dir) / "backend-probe.wav")
        cmd = self._build_command(probe_path, duration_seconds=0.2)
        if not cmd:
            return False, "No microphone backend found (ffmpeg/arecord/rec missing)"

        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=min(5, self.capture_timeout_seconds),
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return False, f"Microphone backend probe failed: {exc}"
        finally:
            try:
                if os.path.exists(probe_path):
                    os.remove(probe_path)
            except OSError:
                pass

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip().splitlines()
            detail = stderr[-1] if stderr else f"exit={completed.returncode}"
            return False, f"Microphone backend unavailable: {detail}"

        return True, "Microphone backend ready"

    def capture(self) -> Optional[str]:
        out_path = str(Path(self.output_dir) / f"chunk-{int(time.time() * 1000)}.wav")
        cmd = self._build_command(out_path)
        if not cmd:
            return None

        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.capture_timeout_seconds,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None

        if completed.returncode != 0:
            return None

        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            return None
        if not self._has_voice_activity(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
            return None
        return out_path
