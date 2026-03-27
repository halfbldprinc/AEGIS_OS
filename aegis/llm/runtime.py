import json
import logging
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    pass


class LLMRuntime:
    def __init__(
        self,
        model_path: str = "~/.aegis/models/primary-q4km.gguf",
        ctx_size: int = 8192,
        host: str = "127.0.0.1",
        port: int = 11434,
        n_gpu_layers: int = 0,
        threads: int = 8,
        silent_prompt: bool = True,
    ):
        self.model_path = str(Path(model_path).expanduser())
        self.ctx_size = ctx_size
        self.host = host
        self.port = port
        self.n_gpu_layers = n_gpu_layers
        self.threads = threads
        self.silent_prompt = silent_prompt

        self.process: Optional[subprocess.Popen] = None
        self._health_thread: Optional[threading.Thread] = None
        self._health_stop = threading.Event()

    @property
    def _base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _health_check(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self._base_url}/health", timeout=2) as resp:
                return resp.status == 200 if hasattr(resp, "status") else True
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            return False

    def _wait_until_ready(self, timeout: int = 30) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._health_check():
                return
            time.sleep(0.3)
        raise LLMUnavailableError("LLM server not ready after timeout")

    def _monitor_health(self) -> None:
        failure_count = 0
        while not self._health_stop.is_set():
            if self._health_check():
                failure_count = 0
            else:
                failure_count += 1
                logger.warning("LLM health check failure #%d", failure_count)
                if failure_count >= 3:
                    logger.error("LLM server appears down; attempting restart")
                    try:
                        self.stop()
                        self.start()
                        failure_count = 0
                    except Exception as exc:
                        logger.exception("LLM restart failed: %s", exc)
            time.sleep(30)

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            logger.info("LLM runtime already running")
            return

        cmd = [
            "llama-server",
            "--model",
            self.model_path,
            "--ctx-size",
            str(self.ctx_size),
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--n-gpu-layers",
            str(self.n_gpu_layers),
            "--threads",
            str(self.threads),
        ]
        if self.silent_prompt:
            cmd.append("--silent-prompt")

        logger.info("Starting LLM server: %s", " ".join(cmd))
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        self._wait_until_ready()

        self._health_stop.clear()
        self._health_thread = threading.Thread(target=self._monitor_health, daemon=True)
        self._health_thread.start()

    def stop(self) -> None:
        self._health_stop.set()
        if self._health_thread and self._health_thread.is_alive():
            self._health_thread.join(timeout=2)

        if self.process:
            if self.process.poll() is None:
                logger.info("Stopping LLM server")
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning("LLM server did not stop in time, killing")
                    self.process.kill()
            self.process = None

    def health(self) -> bool:
        return self.process is not None and self._health_check()

    def generate(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        grammar: Optional[str] = None,
    ) -> str:
        if not self.health():
            raise LLMUnavailableError("LLM runtime is unavailable")

        payload: Dict[str, Any] = {
            "model": "aegis-local",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if grammar is not None:
            payload["grammar"] = grammar

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8")
            result = json.loads(content)
            choices = result.get("choices", [])
            if not choices:
                raise LLMUnavailableError("LLM returned no choices")
            return choices[0].get("message", {}).get("content", "")
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            raise LLMUnavailableError("LLM generation failed") from exc

    def swap_model(self, new_model_path: str) -> bool:
        new_model_path = str(Path(new_model_path).expanduser())
        self.stop()
        self.model_path = new_model_path
        try:
            self.start()
            return True
        except LLMUnavailableError:
            return False
