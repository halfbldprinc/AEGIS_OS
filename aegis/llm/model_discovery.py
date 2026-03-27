import json
import logging
import os
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
SUPPORTED_DISCOVERY_PROVIDERS = {"huggingface", "ollama", "feeds"}


def discover_model_profiles(existing_profiles: Optional[List[Dict[str, Any]]] = None, timeout_s: float = 5.0) -> List[Dict[str, Any]]:
    profiles = [dict(item) for item in (existing_profiles or [])]

    providers = _discovery_providers_from_env()

    if "huggingface" in providers:
        profiles.extend(_discover_huggingface_profiles(timeout_s=timeout_s))

    if "ollama" in providers:
        profiles.extend(_discover_ollama_resolved_profiles(timeout_s=timeout_s))

    if "feeds" in providers:
        profiles.extend(_discover_feed_profiles(timeout_s=timeout_s))

    deduped = _dedupe_profiles(profiles)
    if not deduped:
        return _fallback_default_profiles()
    return deduped


def _discovery_providers_from_env() -> List[str]:
    raw = os.getenv("AEGIS_MODEL_DISCOVERY_PROVIDERS", "huggingface,ollama,feeds")
    providers = [p.strip().lower() for p in raw.split(",") if p.strip()]
    unsupported = [p for p in providers if p not in SUPPORTED_DISCOVERY_PROVIDERS]
    if unsupported:
        logger.warning("Ignoring unsupported model discovery providers: %s", ", ".join(sorted(set(unsupported))))
    return [p for p in providers if p in SUPPORTED_DISCOVERY_PROVIDERS]


def _discover_huggingface_profiles(timeout_s: float = 5.0, limit: int = 20) -> List[Dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "search": "GGUF",
            "sort": "downloads",
            "direction": "-1",
            "limit": str(limit),
        }
    )
    rows = _fetch_json(f"https://huggingface.co/api/models?{query}", timeout_s=timeout_s)
    if not isinstance(rows, list):
        return []

    profiles: List[Dict[str, Any]] = []
    for row in rows:
        repo_id = str(row.get("id") or row.get("modelId") or "").strip()
        if not repo_id:
            continue
        profile = _build_profile_from_hf_repo(repo_id, timeout_s=timeout_s)
        if profile:
            profiles.append(profile)

    return profiles


def _discover_ollama_resolved_profiles(timeout_s: float = 5.0, families_limit: int = 6) -> List[Dict[str, Any]]:
    # Website-based discovery from Ollama, then resolve to downloadable GGUF repos on Hugging Face.
    html = _fetch_text("https://ollama.com/library", timeout_s=timeout_s)
    if not html:
        return []

    families = sorted(set(re.findall(r'/library/([a-zA-Z0-9_.-]+)"', html)))[:families_limit]
    profiles: List[Dict[str, Any]] = []

    for family in families:
        tags_html = _fetch_text(f"https://ollama.com/library/{family}/tags", timeout_s=timeout_s)
        if not tags_html:
            continue

        sizes = sorted(set(re.findall(rf"{re.escape(family)}:(\d+(?:\.\d+)?b)", tags_html)))
        for size in sizes[:4]:
            profile = _resolve_ollama_family_to_hf(family, size, timeout_s=timeout_s)
            if profile:
                profile["discovered_from"] = "ollama"
                profiles.append(profile)

    return profiles


def _discover_feed_profiles(timeout_s: float = 5.0) -> List[Dict[str, Any]]:
    raw = os.getenv("AEGIS_MODEL_DISCOVERY_FEEDS", "").strip()
    if not raw:
        return []

    urls = [part.strip() for part in raw.split(",") if part.strip()]
    out: List[Dict[str, Any]] = []
    for url in urls:
        data = _fetch_json(url, timeout_s=timeout_s)
        if isinstance(data, dict):
            rows = data.get("profiles", [])
        elif isinstance(data, list):
            rows = data
        else:
            rows = []
        for row in rows:
            if isinstance(row, dict):
                out.append(dict(row))
    return out


def _resolve_ollama_family_to_hf(family: str, model_size: str, timeout_s: float = 5.0) -> Optional[Dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "search": f"{family} GGUF {model_size}",
            "sort": "downloads",
            "direction": "-1",
            "limit": "6",
        }
    )
    rows = _fetch_json(f"https://huggingface.co/api/models?{query}", timeout_s=timeout_s)
    if not isinstance(rows, list):
        return None

    for row in rows:
        repo_id = str(row.get("id") or row.get("modelId") or "").strip()
        if not repo_id:
            continue
        profile = _build_profile_from_hf_repo(repo_id, timeout_s=timeout_s)
        if not profile:
            continue
        if _normalize_size(str(profile.get("model_size", ""))) != _normalize_size(model_size):
            continue
        profile["provider"] = _infer_provider_from_text(family)
        return profile

    return None


def _build_profile_from_hf_repo(repo_id: str, timeout_s: float = 5.0) -> Optional[Dict[str, Any]]:
    detail = _fetch_json(f"https://huggingface.co/api/models/{urllib.parse.quote(repo_id, safe='/')}", timeout_s=timeout_s)
    if not isinstance(detail, dict):
        return None

    siblings = detail.get("siblings") or []
    if not isinstance(siblings, list):
        return None

    selected = _select_preferred_gguf_file(siblings)
    if not selected:
        return None

    filename = str(selected.get("rfilename", "")).strip()
    if not filename:
        return None

    size_bytes = int(selected.get("size") or 0)
    parameter_count = _infer_parameter_count(repo_id, filename)
    model_size = _normalize_size(parameter_count)

    specs = _estimate_specs(parameter_count=parameter_count, size_bytes=size_bytes)
    slug = _slugify(f"{repo_id}-{model_size}")

    return {
        "profile_id": slug[:64],
        "label": f"{_title_provider(_infer_provider_from_text(repo_id))} {model_size.upper()} ({repo_id})",
        "provider": _infer_provider_from_text(repo_id),
        "model_size": model_size,
        "repo": repo_id,
        "filename": filename,
        "min_ram_gb": specs["min_ram_gb"],
        "min_storage_gb": specs["min_storage_gb"],
        "min_rom_gb": specs["min_storage_gb"],
        "min_cpu_cores": specs["min_cpu_cores"],
        "requires_gpu": specs["requires_gpu"],
        "min_vram_gb": specs["min_vram_gb"],
        "parameter_count": parameter_count,
        "quantization": _infer_quantization(filename),
        "description": f"Discovered from provider catalog ({repo_id}).",
    }


def _select_preferred_gguf_file(siblings: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    ggufs = [s for s in siblings if str(s.get("rfilename", "")).lower().endswith(".gguf")]
    if not ggufs:
        return None

    preferences = ["q4_k_m", "q4_k_s", "q5_k_m", "q5_k_s", "q8_0"]

    def score(item: Dict[str, Any]) -> tuple:
        name = str(item.get("rfilename", "")).lower()
        pref_idx = len(preferences)
        for idx, pref in enumerate(preferences):
            if pref in name:
                pref_idx = idx
                break
        size = int(item.get("size") or 10**12)
        return pref_idx, size

    return sorted(ggufs, key=score)[0]


def _estimate_specs(parameter_count: str, size_bytes: int) -> Dict[str, Any]:
    size_b = _extract_size_b(parameter_count)
    storage_gb = max(2, (size_bytes // (1024**3)) + (1 if size_bytes % (1024**3) else 0)) if size_bytes else max(3, int(size_b * 1.2) if size_b else 8)

    if size_b <= 2:
        return {
            "min_ram_gb": 8,
            "min_storage_gb": max(3, storage_gb),
            "min_cpu_cores": 4,
            "requires_gpu": False,
            "min_vram_gb": 0,
        }
    if size_b <= 8:
        return {
            "min_ram_gb": 16,
            "min_storage_gb": max(6, storage_gb),
            "min_cpu_cores": 8,
            "requires_gpu": False,
            "min_vram_gb": 0,
        }
    if size_b <= 16:
        return {
            "min_ram_gb": 32,
            "min_storage_gb": max(10, storage_gb),
            "min_cpu_cores": 12,
            "requires_gpu": True,
            "min_vram_gb": 10,
        }

    return {
        "min_ram_gb": 48,
        "min_storage_gb": max(14, storage_gb),
        "min_cpu_cores": 16,
        "requires_gpu": True,
        "min_vram_gb": 16,
    }


def _infer_quantization(filename: str) -> str:
    match = re.search(r"(Q\d+_[A-Z0-9_]+|IQ\d+_[A-Z0-9_]+)", filename, re.IGNORECASE)
    if not match:
        return "unknown"
    return match.group(1).upper()


def _infer_parameter_count(repo_id: str, filename: str) -> str:
    for text in (filename, repo_id):
        match = re.search(r"(\d+(?:\.\d+)?)\s*[Bb]", text)
        if match:
            return f"{match.group(1)}B"
    return "7B"


def _extract_size_b(parameter_count: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)", parameter_count)
    if not match:
        return 7.0
    try:
        return float(match.group(1))
    except ValueError:
        return 7.0


def _infer_provider_from_text(text: str) -> str:
    lower = text.lower()
    if "deepseek" in lower:
        return "deepseek"
    if "qwen" in lower:
        return "qwen"
    if "mistral" in lower:
        return "mistral"
    if "llama" in lower:
        return "llama"
    if "gemma" in lower:
        return "gemma"
    return "open-source"


def _normalize_size(value: str) -> str:
    return value.strip().lower().replace(" ", "")


def _title_provider(provider: str) -> str:
    return provider.replace("-", " ").title()


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return cleaned or "model"


def _dedupe_profiles(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for profile in profiles:
        key = (
            str(profile.get("provider", "")).lower(),
            str(profile.get("model_size", "")).lower(),
            str(profile.get("repo", "")).lower(),
            str(profile.get("filename", "")).lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(profile)
    return out


def _fallback_default_profiles() -> List[Dict[str, Any]]:
    return [
        {
            "profile_id": "small",
            "label": "DeepSeek 1.5B (fallback)",
            "provider": "deepseek",
            "model_size": "1.5b",
            "repo": "bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF",
            "filename": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
            "min_ram_gb": 8,
            "min_storage_gb": 3,
            "min_rom_gb": 3,
            "min_cpu_cores": 4,
            "requires_gpu": False,
            "min_vram_gb": 0,
            "parameter_count": "1.5B",
            "quantization": "Q4_K_M",
            "description": "Fallback profile when online discovery is unavailable.",
        },
        {
            "profile_id": "medium",
            "label": "DeepSeek 7B (fallback)",
            "provider": "deepseek",
            "model_size": "7b",
            "repo": "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
            "filename": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
            "min_ram_gb": 16,
            "min_storage_gb": 6,
            "min_rom_gb": 6,
            "min_cpu_cores": 8,
            "requires_gpu": False,
            "min_vram_gb": 0,
            "parameter_count": "7B",
            "quantization": "Q4_K_M",
            "description": "Fallback profile when online discovery is unavailable.",
        },
    ]


def _fetch_json(url: str, timeout_s: float = 5.0) -> Any:
    text = _fetch_text(url, timeout_s=timeout_s)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        logger.debug("Failed to parse JSON from %s", url)
        return None


def _fetch_text(url: str, timeout_s: float = 5.0) -> str:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "AegisOS-ModelDiscovery/1.0",
                "Accept": "application/json, text/plain, text/html;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as response:
            return response.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""
