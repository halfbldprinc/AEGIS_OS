import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .guardian import Guardian
from .llm.model_discovery import discover_model_profiles
from .llm.model_manager import ModelManager


@dataclass
class ModelProfile:
    profile_id: str
    label: str
    repo: str
    filename: str
    min_ram_gb: int
    description: str
    parameter_count: str = "unknown"
    quantization: str = "unknown"
    provider: str = "unknown"
    model_size: str = "unknown"
    min_cpu_cores: int = 4
    min_storage_gb: int = 8
    min_rom_gb: int = 8
    requires_gpu: bool = False
    min_vram_gb: int = 0


@dataclass
class PermissionGrant:
    skill_name: str
    action: str
    duration_hours: Optional[int] = None


@dataclass
class PermissionProfile:
    profile_id: str
    label: str
    description: str
    grants: List[PermissionGrant]


DEFAULT_PROFILES: List[ModelProfile] = [
    ModelProfile(
        profile_id="small",
        label="DeepSeek 1.5B (fastest)",
        repo="bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF",
        filename="DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
        min_ram_gb=8,
        description="Low memory footprint and fast startup.",
        parameter_count="1.5B",
        quantization="Q4_K_M",
        provider="deepseek",
        model_size="1.5b",
        min_cpu_cores=4,
        min_storage_gb=3,
        min_rom_gb=3,
        requires_gpu=False,
        min_vram_gb=0,
    ),
    ModelProfile(
        profile_id="medium",
        label="DeepSeek 7B (balanced)",
        repo="bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        filename="DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
        min_ram_gb=16,
        description="Balanced quality and latency for daily use.",
        parameter_count="7B",
        quantization="Q4_K_M",
        provider="deepseek",
        model_size="7b",
        min_cpu_cores=8,
        min_storage_gb=6,
        min_rom_gb=6,
        requires_gpu=False,
        min_vram_gb=0,
    ),
    ModelProfile(
        profile_id="large",
        label="DeepSeek 14B (best quality)",
        repo="bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF",
        filename="DeepSeek-R1-Distill-Qwen-14B-Q4_K_M.gguf",
        min_ram_gb=32,
        description="Higher quality with larger hardware requirements.",
        parameter_count="14B",
        quantization="Q4_K_M",
        provider="deepseek",
        model_size="14b",
        min_cpu_cores=12,
        min_storage_gb=10,
        min_rom_gb=10,
        requires_gpu=True,
        min_vram_gb=10,
    ),
]


DEFAULT_PERMISSION_PROFILES: List[PermissionProfile] = [
    PermissionProfile(
        profile_id="strict",
        label="Strict",
        description="Safer defaults, no destructive permissions pre-granted.",
        grants=[
            PermissionGrant("echo", "echo"),
            PermissionGrant("web_search", "search"),
            PermissionGrant("http", "request"),
            PermissionGrant("json_transform", "all"),
            PermissionGrant("browser", "fetch_text"),
            PermissionGrant("browser", "extract_links"),
            PermissionGrant("llm", "reason"),
        ],
    ),
    PermissionProfile(
        profile_id="prompt_once",
        label="Prompt Once (recommended)",
        description="Prompts on first sensitive task execution, then remembers approval per skill/action.",
        grants=[
            PermissionGrant("echo", "all"),
            PermissionGrant("llm", "all"),
            PermissionGrant("web_search", "all"),
            PermissionGrant("http", "request"),
            PermissionGrant("json_transform", "all"),
            PermissionGrant("browser", "all"),
            PermissionGrant("calendar", "read"),
            PermissionGrant("reminder", "read"),
        ],
    ),
    PermissionProfile(
        profile_id="balanced",
        label="Balanced",
        description="Everyday assistant actions enabled, destructive actions still gated.",
        grants=[
            PermissionGrant("echo", "all"),
            PermissionGrant("llm", "all"),
            PermissionGrant("web_search", "all"),
            PermissionGrant("http", "request"),
            PermissionGrant("json_transform", "all"),
            PermissionGrant("browser", "all"),
            PermissionGrant("calendar", "all"),
            PermissionGrant("reminder", "all"),
            PermissionGrant("email", "draft"),
            PermissionGrant("file", "read"),
            PermissionGrant("file", "search"),
            PermissionGrant("file_batch", "batch"),
            PermissionGrant("shell", "run", duration_hours=4),
        ],
    ),
    PermissionProfile(
        profile_id="open",
        label="Open",
        description="Broad local automation enabled. Recommended only for trusted personal devices.",
        grants=[
            PermissionGrant("echo", "all"),
            PermissionGrant("llm", "all"),
            PermissionGrant("web_search", "all"),
            PermissionGrant("http", "request"),
            PermissionGrant("json_transform", "all"),
            PermissionGrant("browser", "all"),
            PermissionGrant("calendar", "all"),
            PermissionGrant("reminder", "all"),
            PermissionGrant("email", "all"),
            PermissionGrant("file", "all"),
            PermissionGrant("file_batch", "batch"),
            PermissionGrant("shell", "run"),
            PermissionGrant("os_control", "all"),
            PermissionGrant("settings", "all"),
            PermissionGrant("container", "all"),
        ],
    ),
]


def load_profiles(catalog_path: Optional[str]) -> List[ModelProfile]:
    catalog_profiles: List[Dict[str, object]] = []
    if catalog_path:
        path = Path(catalog_path)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            catalog_profiles = list(data.get("profiles", []))

    dynamic_enabled = os.getenv("AEGIS_DYNAMIC_MODEL_DISCOVERY", "1").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if dynamic_enabled:
        timeout_s = float(os.getenv("AEGIS_MODEL_DISCOVERY_TIMEOUT_SECONDS", "5"))
        catalog_profiles = discover_model_profiles(catalog_profiles, timeout_s=timeout_s)

    profiles = []
    for item in catalog_profiles:
        provider, model_size = _resolve_provider_and_size(item)
        profiles.append(
            ModelProfile(
                profile_id=str(item["profile_id"]),
                label=str(item["label"]),
                repo=str(item["repo"]),
                filename=str(item["filename"]),
                min_ram_gb=int(item.get("min_ram_gb", 8)),
                description=str(item.get("description", "")),
                parameter_count=str(item.get("parameter_count", "unknown")),
                quantization=str(item.get("quantization", "unknown")),
                provider=provider,
                model_size=model_size,
                min_cpu_cores=int(item.get("min_cpu_cores", 4)),
                min_storage_gb=int(item.get("min_storage_gb", item.get("min_rom_gb", 8))),
                min_rom_gb=int(item.get("min_rom_gb", item.get("min_storage_gb", 8))),
                requires_gpu=bool(item.get("requires_gpu", False)),
                min_vram_gb=int(item.get("min_vram_gb", 0)),
            )
        )

    return profiles or list(DEFAULT_PROFILES)


def choose_profile(
    profiles: List[ModelProfile],
    selected_profile: Optional[str],
    interactive: bool,
    selected_provider: Optional[str] = None,
    selected_model_size: Optional[str] = None,
) -> ModelProfile:
    if not profiles:
        raise ValueError("No model profiles available")

    if selected_profile:
        profile = _find_by_profile_id(profiles, selected_profile)
        if profile:
            return profile
        raise ValueError(f"Unknown model profile: {selected_profile}")

    if selected_provider or selected_model_size:
        profile = _resolve_by_provider_size(profiles, selected_provider, selected_model_size)
        if profile:
            return profile
        raise ValueError(
            "Unknown model provider/size combination: "
            f"provider={selected_provider or '<unset>'}, size={selected_model_size or '<unset>'}"
        )

    env_profile = os.getenv("AEGIS_MODEL_PROFILE")
    if env_profile:
        profile = _find_by_profile_id(profiles, env_profile)
        if profile:
            return profile

    env_provider = os.getenv("AEGIS_MODEL_PROVIDER")
    env_model_size = os.getenv("AEGIS_MODEL_SIZE")
    if env_provider or env_model_size:
        profile = _resolve_by_provider_size(profiles, env_provider, env_model_size)
        if profile:
            return profile

    if interactive and os.isatty(0):
        provider = _interactive_provider_select(profiles)
        return _interactive_size_select(profiles, provider)

    return _default_profile(profiles)


def _normalize_choice(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _normalize_size(value: Optional[str]) -> str:
    return _normalize_choice(value).replace(" ", "")


def _resolve_provider_and_size(item: Dict[str, object]) -> Tuple[str, str]:
    provider = _normalize_choice(str(item.get("provider", "")))
    if not provider:
        repo = _normalize_choice(str(item.get("repo", "")))
        if "deepseek" in repo:
            provider = "deepseek"
        elif "mistral" in repo:
            provider = "mistral"
        elif "qwen" in repo:
            provider = "qwen"
        elif "llama" in repo:
            provider = "llama"
        else:
            provider = "unknown"

    raw_size = item.get("model_size") or item.get("size") or item.get("parameter_count") or item.get("profile_id")
    model_size = _normalize_size(str(raw_size))
    size_aliases = {
        "small": "1.5b",
        "medium": "7b",
        "large": "14b",
    }
    model_size = size_aliases.get(model_size, model_size)
    return provider, model_size


def _find_by_profile_id(profiles: List[ModelProfile], profile_id: str) -> Optional[ModelProfile]:
    for profile in profiles:
        if profile.profile_id == profile_id:
            return profile
    return None


def _resolve_by_provider_size(
    profiles: List[ModelProfile],
    provider: Optional[str],
    model_size: Optional[str],
) -> Optional[ModelProfile]:
    provider_key = _normalize_choice(provider)
    size_key = _normalize_size(model_size)

    provider_matches = [p for p in profiles if _normalize_choice(p.provider) == provider_key] if provider_key else list(profiles)
    if not provider_matches:
        return None

    if size_key:
        for profile in provider_matches:
            if _normalize_size(profile.model_size) == size_key:
                return profile
        return None

    return _default_profile(provider_matches)


def _default_profile(profiles: List[ModelProfile]) -> ModelProfile:
    preferred = _find_by_profile_id(profiles, "medium")
    if preferred:
        return preferred

    for wanted in ("7b", "8b", "10b", "14b"):
        for profile in profiles:
            if _normalize_size(profile.model_size) == wanted:
                return profile

    return profiles[0]


def _interactive_provider_select(profiles: List[ModelProfile]) -> str:
    providers = []
    for profile in profiles:
        provider = profile.provider
        if provider not in providers:
            providers.append(provider)

    print("Select AegisOS model provider:")
    for index, provider in enumerate(providers, start=1):
        print(f"{index}. {provider}")

    default_provider = _default_profile(profiles).provider
    default_index = providers.index(default_provider) + 1 if default_provider in providers else 1
    raw = input(f"Enter provider number (default {default_index}): ").strip() or str(default_index)
    try:
        idx = int(raw)
        if idx < 1 or idx > len(providers):
            raise ValueError
        return providers[idx - 1]
    except ValueError as exc:
        raise ValueError("Invalid model provider selection") from exc


def _interactive_size_select(profiles: List[ModelProfile], provider: str) -> ModelProfile:
    provider_profiles = [p for p in profiles if p.provider == provider]
    if not provider_profiles:
        raise ValueError(f"No model profiles available for provider: {provider}")

    print(f"Select model size for provider '{provider}':")
    for index, profile in enumerate(provider_profiles, start=1):
        print(
            f"{index}. size={profile.model_size} [{profile.profile_id}] "
            f"params={profile.parameter_count} quant={profile.quantization} "
            f"min_ram={profile.min_ram_gb}GB - {profile.description}"
        )
        print(f"   {format_hardware_info(profile)}")

    default_profile = _default_profile(provider_profiles)
    default_index = provider_profiles.index(default_profile) + 1
    raw = input(f"Enter size number (default {default_index}): ").strip() or str(default_index)
    try:
        idx = int(raw)
        if idx < 1 or idx > len(provider_profiles):
            raise ValueError
        return provider_profiles[idx - 1]
    except ValueError as exc:
        raise ValueError("Invalid model size selection") from exc


def format_hardware_info(profile: ModelProfile) -> str:
    gpu_text = "not required"
    if profile.requires_gpu:
        gpu_text = f"required ({profile.min_vram_gb}GB VRAM minimum)"
    return (
        "Spec Requirement Bar: "
        f"RAM>={profile.min_ram_gb}GB | ROM>={profile.min_rom_gb}GB | "
        f"CPU>={profile.min_cpu_cores} cores | GPU={gpu_text} | "
        f"Storage>={profile.min_storage_gb}GB"
    )


def load_permission_profiles(catalog_path: Optional[str]) -> List[PermissionProfile]:
    if not catalog_path:
        return list(DEFAULT_PERMISSION_PROFILES)

    path = Path(catalog_path)
    if not path.exists():
        return list(DEFAULT_PERMISSION_PROFILES)

    data = json.loads(path.read_text(encoding="utf-8"))
    profiles = []
    for item in data.get("permission_profiles", []):
        grants = []
        for grant in item.get("grants", []):
            grants.append(
                PermissionGrant(
                    skill_name=str(grant["skill_name"]),
                    action=str(grant["action"]),
                    duration_hours=grant.get("duration_hours"),
                )
            )
        profiles.append(
            PermissionProfile(
                profile_id=str(item["profile_id"]),
                label=str(item["label"]),
                description=str(item.get("description", "")),
                grants=grants,
            )
        )

    return profiles or list(DEFAULT_PERMISSION_PROFILES)


def choose_permission_profile(
    profiles: List[PermissionProfile],
    selected_profile: Optional[str],
    interactive: bool,
) -> PermissionProfile:
    if selected_profile:
        for profile in profiles:
            if profile.profile_id == selected_profile:
                return profile
        raise ValueError(f"Unknown permission profile: {selected_profile}")

    env_profile = os.getenv("AEGIS_PERMISSION_PROFILE")
    if env_profile:
        for profile in profiles:
            if profile.profile_id == env_profile:
                return profile

    if interactive and os.isatty(0):
        print("Select AegisOS permission profile:")
        for index, profile in enumerate(profiles, start=1):
            print(f"{index}. {profile.label} [{profile.profile_id}] - {profile.description}")

        raw = input("Enter selection number (default 2): ").strip() or "2"
        try:
            idx = int(raw)
            if idx < 1 or idx > len(profiles):
                raise ValueError
            return profiles[idx - 1]
        except ValueError as exc:
            raise ValueError("Invalid permission profile selection") from exc

    for profile in profiles:
        if profile.profile_id == "prompt_once":
            return profile

    return profiles[0]


def apply_permission_profile(profile: PermissionProfile, guardian_db: Optional[str] = None) -> None:
    guardian = Guardian(db_path=guardian_db) if guardian_db else Guardian()
    for grant in profile.grants:
        guardian.grant(grant.skill_name, grant.action, duration_hours=grant.duration_hours)


def run_firstboot(
    models_dir: str,
    catalog_path: Optional[str] = None,
    selected_profile: Optional[str] = None,
    selected_provider: Optional[str] = None,
    selected_model_size: Optional[str] = None,
    selected_permission_profile: Optional[str] = None,
    interactive: bool = False,
    interactive_permissions: bool = False,
    guardian_db: Optional[str] = None,
    stamp_path: Optional[str] = None,
) -> dict:
    model_profiles = load_profiles(catalog_path)
    permission_profiles = load_permission_profiles(catalog_path)

    chosen = choose_profile(
        model_profiles,
        selected_profile=selected_profile,
        interactive=interactive,
        selected_provider=selected_provider,
        selected_model_size=selected_model_size,
    )
    chosen_perms = choose_permission_profile(
        permission_profiles,
        selected_profile=selected_permission_profile,
        interactive=interactive_permissions,
    )

    manager = ModelManager(models_dir=models_dir)
    model_path = manager.download_model(chosen.repo, chosen.filename, models_dir)
    manager.set_active(chosen.filename)

    apply_permission_profile(chosen_perms, guardian_db=guardian_db)

    if stamp_path:
        stamp = Path(stamp_path)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(
            json.dumps(
                {
                    "profile_id": chosen.profile_id,
                    "provider": chosen.provider,
                    "model_size": chosen.model_size,
                    "hardware_info": format_hardware_info(chosen),
                    "permission_profile_id": chosen_perms.profile_id,
                    "model": chosen.filename,
                    "path": model_path,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return {
        "profile_id": chosen.profile_id,
        "provider": chosen.provider,
        "model_size": chosen.model_size,
        "hardware_info": format_hardware_info(chosen),
        "permission_profile_id": chosen_perms.profile_id,
        "model": chosen.filename,
        "path": model_path,
    }


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="AegisOS first-boot setup for integrated local assistant")
    parser.add_argument("--models-dir", default="/var/lib/aegis/models")
    parser.add_argument("--catalog", default="/etc/aegis/model_catalog.json")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model-size", default=None)
    parser.add_argument("--permission-profile", default=None)
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--interactive-permissions", action="store_true")
    parser.add_argument("--guardian-db", default=None)
    parser.add_argument("--stamp", default="/var/lib/aegis/.firstboot_done")
    args = parser.parse_args(argv)

    result = run_firstboot(
        models_dir=args.models_dir,
        catalog_path=args.catalog,
        selected_profile=args.profile,
        selected_provider=args.provider,
        selected_model_size=args.model_size,
        selected_permission_profile=args.permission_profile,
        interactive=args.interactive,
        interactive_permissions=args.interactive_permissions,
        guardian_db=args.guardian_db,
        stamp_path=args.stamp,
    )
    print(result)


if __name__ == "__main__":
    main()
