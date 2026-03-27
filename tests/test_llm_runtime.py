import json
import subprocess

import pytest

from aegis.hardware import HardwareProfile
from aegis.llm.runtime import LLMRuntime, LLMUnavailableError
from aegis.llm.model_manager import ModelManager
from aegis.llm.quantizer import Quantizer


class DummyResponse:
    def __init__(self, data: bytes, code: int = 200):
        self._data = data
        self.status = code

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_llm_runtime_generate_when_server_down_raises(monkeypatch):
    runtime = LLMRuntime(model_path="/tmp/nonexistent.gguf")

    # health check fails until start called
    with pytest.raises(LLMUnavailableError):
        runtime.generate([{"role": "user", "content": "hello"}])


def test_llm_runtime_start_and_generate(monkeypatch, tmp_path):
    started = {
        "cmd": None,
        "alive": True,
    }

    class FakePopen:
        def __init__(self, cmd, stdout=None, stderr=None):
            started["cmd"] = cmd
            self._killed = False

        def poll(self):
            return None if not self._killed else 0

        def terminate(self):
            self._killed = True

        def wait(self, timeout=None):
            return 0

    def fake_urlopen(url, timeout=0):
        if "health" in str(url):
            return DummyResponse(b"{}")

        payload = json.dumps({
            "choices": [{"message": {"content": "Hello world"}}]
        }).encode("utf-8")
        return DummyResponse(payload)

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr("aegis.llm.runtime.urllib.request.urlopen", fake_urlopen)

    runtime = LLMRuntime(model_path=str(tmp_path / "primary.gguf"))
    runtime.start()
    assert runtime.health() is True

    out = runtime.generate([{"role": "user", "content": "ping"}], temperature=0.1, max_tokens=10)
    assert out == "Hello world"

    runtime.stop()


def test_llm_runtime_auto_tunes_from_hardware(monkeypatch, tmp_path):
    started = {"cmd": None}

    class FakePopen:
        def __init__(self, cmd, stdout=None, stderr=None):
            started["cmd"] = cmd
            self._killed = False

        def poll(self):
            return None if not self._killed else 0

        def terminate(self):
            self._killed = True

        def wait(self, timeout=None):
            return 0

    def fake_urlopen(url, timeout=0):
        if "health" in str(url):
            return DummyResponse(b"{}")
        payload = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
        return DummyResponse(payload)

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr("aegis.llm.runtime.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(
        "aegis.llm.runtime.detect_hardware_profile",
        lambda: HardwareProfile(
            cpu_cores=24,
            total_ram_gb=64,
            total_storage_gb=512,
            has_gpu=True,
            gpu_vendor="nvidia",
            vram_gb=16,
        ),
    )

    runtime = LLMRuntime(model_path=str(tmp_path / "primary.gguf"), n_gpu_layers=None, threads=None)
    runtime.start()

    cmd = started["cmd"]
    assert "--n-gpu-layers" in cmd
    gpu_idx = cmd.index("--n-gpu-layers")
    assert cmd[gpu_idx + 1] == "35"

    threads_idx = cmd.index("--threads")
    assert cmd[threads_idx + 1] == "16"

    profile = runtime.runtime_profile()
    assert profile["n_gpu_layers"] == 35
    assert profile["threads"] == 16

    runtime.stop()


def test_model_manager_download_and_active(tmp_path, monkeypatch):
    # we create a fake model file and bypass huggingface download logic
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True)

    mm = ModelManager(models_dir=models_dir)
    model_file = models_dir / "test-model.gguf"
    model_file.write_text("modeldata")

    # monkeypatch snapshot_download to be a no-op
    monkeypatch.setattr("aegis.llm.model_manager.snapshot_download", lambda *args, **kwargs: None)

    path = mm.download_model("a/b", "test-model.gguf", target_dir=models_dir)
    assert path == str(model_file)

    mm.set_active("test-model.gguf")
    assert mm.get_active_model()["name"] == "test-model.gguf"

    with pytest.raises(ValueError):
        mm.delete_model("test-model.gguf")


def test_quantizer_command(monkeypatch, tmp_path):
    input_file = tmp_path / "in.gguf"
    output_file = tmp_path / "out.gguf"
    input_file.write_text("dummy")

    def fake_run(cmd, capture_output, text):
        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    q = Quantizer(llama_quantize_executable="llama-quantize")
    out = q.quantize(str(input_file), str(output_file), "Q4_K_M")

    assert out["quant_type"] == "Q4_K_M"
    assert out["output_path"] == str(output_file)
