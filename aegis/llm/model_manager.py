import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

try:
    from huggingface_hub import hf_hub_download, snapshot_download
except ImportError:  # pragma: no cover
    hf_hub_download = None
    snapshot_download = None

logger = logging.getLogger(__name__)


class ModelManager:
    def __init__(self, models_dir: str | Path = "~/.aegis/models"):
        self.models_dir = Path(models_dir).expanduser()
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.models_dir / "registry.json"
        self._load_registry()

    def _load_registry(self) -> None:
        if self.registry_path.exists():
            with open(self.registry_path, "r", encoding="utf-8") as f:
                self.registry = json.load(f)
        else:
            self.registry = []
            self._save_registry()

    def _save_registry(self) -> None:
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(self.registry, f, indent=2)

    @staticmethod
    def _sha256(path: str | Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def list_models(self) -> List[Dict[str, Optional[str]]]:
        return self.registry.copy()

    def get_active_model(self) -> Optional[Dict[str, Optional[str]]]:
        for item in self.registry:
            if item.get("active"):
                return item
        return None

    def get_active_model_path(self) -> Optional[str]:
        active = self.get_active_model()
        if active:
            return active.get("path")
        return None

    def download_model(self, hf_repo: str, filename: str, target_dir: str | Path) -> str:
        if snapshot_download is None and hf_hub_download is None:
            raise RuntimeError("huggingface_hub is required to download models")

        target_dir = Path(target_dir).expanduser()
        target_dir.mkdir(parents=True, exist_ok=True)

        local_path = target_dir / filename
        if not local_path.exists():
            if hf_hub_download is not None:
                hf_hub_download(repo_id=hf_repo, filename=filename, local_dir=str(target_dir))
            elif snapshot_download is not None:
                snapshot_download(repo_id=hf_repo, local_dir=str(target_dir), local_files_only=False)
            if not local_path.exists():
                raise FileNotFoundError(f"Model file {filename} not found in downloaded repo")

        sha256 = self._sha256(local_path)
        item = {
            "name": filename,
            "path": str(local_path),
            "sha256": sha256,
            "size_bytes": local_path.stat().st_size,
            "quant_type": "gguf",
            "active": False,
            "version": None,
            "created_at": None,
            "benchmark_scores": {},
            "lineage": [],
        }
        self.registry = [x for x in self.registry if x.get("name") != filename] + [item]
        self._save_registry()
        return str(local_path)

    def set_active(self, model_name: str) -> str:
        found = False
        for item in self.registry:
            if item.get("name") == model_name:
                item["active"] = True
                found = True
            else:
                item["active"] = False

        if not found:
            raise KeyError(f"Model {model_name} not found")

        self._save_registry()
        model_path = self.get_active_model_path()
        if not model_path:
            raise RuntimeError("Active model was not set")
        return model_path

    def delete_model(self, model_name: str) -> None:
        active = self.get_active_model()
        if active and active.get("name") == model_name:
            raise ValueError("Cannot delete the active model")

        self.registry = [x for x in self.registry if x.get("name") != model_name]
        self._save_registry()
        file_to_delete = self.models_dir / model_name
        if file_to_delete.exists():
            os.remove(file_to_delete)
