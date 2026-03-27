import json
import sqlite3

import pytest

from aegis.firstboot import (
    DEFAULT_PERMISSION_PROFILES,
    ModelProfile,
    _choose_profile_for_hardware,
    choose_permission_profile,
    choose_profile,
    format_hardware_info,
    load_profiles,
    run_firstboot,
)
from aegis.hardware import HardwareProfile


@pytest.fixture(autouse=True)
def disable_online_discovery(monkeypatch):
    monkeypatch.setenv("AEGIS_DYNAMIC_MODEL_DISCOVERY", "0")


def test_choose_profile_default_medium():
    profiles = [
        ModelProfile("small", "S", "r1", "f1", 8, "d1"),
        ModelProfile("medium", "M", "r2", "f2", 16, "d2"),
    ]

    chosen = choose_profile(profiles, selected_profile=None, interactive=False)
    assert chosen.profile_id == "medium"


def test_load_profiles_from_catalog(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "profile_id": "x",
                        "label": "X",
                        "provider": "deepseek",
                        "model_size": "7b",
                        "repo": "repo/x",
                        "filename": "x.gguf",
                        "min_ram_gb": 12,
                        "description": "x",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    profiles = load_profiles(str(catalog))
    assert len(profiles) == 1
    assert profiles[0].profile_id == "x"
    assert profiles[0].provider == "deepseek"
    assert profiles[0].model_size == "7b"


def test_load_profiles_from_legacy_catalog_infers_provider_and_size(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "profile_id": "medium",
                        "label": "M",
                        "repo": "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
                        "filename": "m.gguf",
                        "min_ram_gb": 16,
                        "description": "m",
                        "parameter_count": "7B",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    profiles = load_profiles(str(catalog))
    assert profiles[0].provider == "deepseek"
    assert profiles[0].model_size == "7b"


def test_choose_profile_by_provider_and_size():
    profiles = [
        ModelProfile("small", "S", "r1", "f1", 8, "d1", provider="deepseek", model_size="1.5b"),
        ModelProfile("medium", "M", "r2", "f2", 16, "d2", provider="deepseek", model_size="7b"),
    ]

    chosen = choose_profile(
        profiles,
        selected_profile=None,
        interactive=False,
        selected_provider="deepseek",
        selected_model_size="7b",
    )
    assert chosen.profile_id == "medium"


def test_choose_profile_from_env_provider_and_size(monkeypatch):
    profiles = [
        ModelProfile("small", "S", "r1", "f1", 8, "d1", provider="deepseek", model_size="1.5b"),
        ModelProfile("medium", "M", "r2", "f2", 16, "d2", provider="deepseek", model_size="7b"),
    ]

    monkeypatch.delenv("AEGIS_MODEL_PROFILE", raising=False)
    monkeypatch.setenv("AEGIS_MODEL_PROVIDER", "deepseek")
    monkeypatch.setenv("AEGIS_MODEL_SIZE", "7b")

    chosen = choose_profile(profiles, selected_profile=None, interactive=False)
    assert chosen.profile_id == "medium"


def test_choose_profile_for_hardware_prefers_largest_eligible_profile():
    profiles = [
        ModelProfile("small", "S", "r1", "f1", 8, "d1", min_cpu_cores=4, min_storage_gb=3),
        ModelProfile("medium", "M", "r2", "f2", 16, "d2", min_cpu_cores=8, min_storage_gb=6),
        ModelProfile(
            "large",
            "L",
            "r3",
            "f3",
            32,
            "d3",
            min_cpu_cores=12,
            min_storage_gb=10,
            requires_gpu=True,
            min_vram_gb=10,
        ),
    ]
    hardware = HardwareProfile(
        cpu_cores=16,
        total_ram_gb=64,
        total_storage_gb=512,
        has_gpu=True,
        gpu_vendor="nvidia",
        vram_gb=16,
    )

    chosen = _choose_profile_for_hardware(profiles, hardware)
    assert chosen is not None
    assert chosen.profile_id == "large"


def test_choose_profile_auto_hardware_mode(monkeypatch):
    profiles = [
        ModelProfile("small", "S", "r1", "f1", 8, "d1", min_cpu_cores=4, min_storage_gb=3),
        ModelProfile("medium", "M", "r2", "f2", 16, "d2", min_cpu_cores=8, min_storage_gb=6),
    ]

    monkeypatch.setattr(
        "aegis.firstboot.detect_hardware_profile",
        lambda: HardwareProfile(
            cpu_cores=4,
            total_ram_gb=8,
            total_storage_gb=128,
            has_gpu=False,
            gpu_vendor="none",
            vram_gb=0,
        ),
    )

    chosen = choose_profile(
        profiles,
        selected_profile=None,
        interactive=False,
        auto_profile_by_hardware=True,
    )
    assert chosen.profile_id == "small"


def test_run_firstboot_downloads_and_sets_active(monkeypatch, tmp_path):
    calls = {"download": 0, "set_active": 0}

    class DummyModelManager:
        def __init__(self, models_dir):
            self.models_dir = models_dir

        def download_model(self, repo, filename, target_dir):
            calls["download"] += 1
            return str(tmp_path / filename)

        def set_active(self, model_name):
            calls["set_active"] += 1
            return None

    monkeypatch.setattr("aegis.firstboot.ModelManager", DummyModelManager)

    stamp = tmp_path / "stamp.json"
    result = run_firstboot(
        models_dir=str(tmp_path / "models"),
        selected_profile="small",
        selected_permission_profile="strict",
        interactive=False,
        interactive_permissions=False,
        guardian_db=str(tmp_path / "guardian.db"),
        stamp_path=str(stamp),
    )

    assert result["profile_id"] == "small"
    assert result["provider"] == "deepseek"
    assert result["model_size"] == "1.5b"
    assert result["permission_profile_id"] == "strict"
    assert calls["download"] == 1
    assert calls["set_active"] == 1
    assert stamp.exists()


def test_choose_permission_profile_default_prompt_once():
    chosen = choose_permission_profile(DEFAULT_PERMISSION_PROFILES, selected_profile=None, interactive=False)
    assert chosen.profile_id == "prompt_once"


def test_firstboot_applies_guardian_permissions(monkeypatch, tmp_path):
    class DummyModelManager:
        def __init__(self, models_dir):
            self.models_dir = models_dir

        def download_model(self, repo, filename, target_dir):
            return str(tmp_path / filename)

        def set_active(self, model_name):
            return None

    monkeypatch.setattr("aegis.firstboot.ModelManager", DummyModelManager)

    guardian_db = tmp_path / "guardian.db"
    run_firstboot(
        models_dir=str(tmp_path / "models"),
        selected_profile="small",
        selected_permission_profile="strict",
        guardian_db=str(guardian_db),
    )

    conn = sqlite3.connect(str(guardian_db))
    rows = conn.execute("SELECT skill_name, action FROM permissions").fetchall()
    conn.close()

    assert ("echo", "echo") in rows
    assert ("http", "request") in rows
    assert ("json_transform", "all") in rows


def test_format_hardware_info_contains_required_dimensions():
    profile = ModelProfile(
        "x",
        "X",
        "repo/x",
        "x.gguf",
        16,
        "desc",
        min_cpu_cores=8,
        min_storage_gb=10,
        min_rom_gb=10,
        requires_gpu=True,
        min_vram_gb=8,
    )

    info = format_hardware_info(profile)
    assert "RAM>=16GB" in info
    assert "ROM>=10GB" in info
    assert "CPU>=8 cores" in info
    assert "GPU=required (8GB VRAM minimum)" in info
    assert "Storage>=10GB" in info
