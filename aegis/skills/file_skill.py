import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..result import SkillResult
from ..skill import Skill


class FileSkill(Skill):
    name = "file"
    tier = 2

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        path = params.get("path")
        if not path:
            return SkillResult.fail("'path' parameter is required")

        path_obj = Path(path).expanduser()

        if action == "read":
            return self.read(path_obj)
        if action == "write":
            return self.write(path_obj, params.get("content"))
        if action == "append":
            return self.append(path_obj, params.get("content"))
        if action == "delete":
            return self.delete(path_obj, approved=bool(params.get("approved", False)))
        if action == "move":
            return self.move(path_obj, Path(params.get("target", "")))
        if action == "copy":
            return self.copy(path_obj, Path(params.get("target", "")))
        if action == "list":
            return self.list_dir(path_obj)

        return SkillResult.fail(f"Unsupported action: {action}")

    def get_permissions(self) -> List[str]:
        return ["read", "write", "append", "delete", "move", "copy", "list"]

    def _check_within_project(self, path_obj: Path) -> bool:
        try:
            target = path_obj.resolve()
            base = Path.cwd().resolve()
            # Allow cwd project paths and system temporary space for tests / safe operations.
            if base in target.parents or target == base:
                return True
            tmp = Path(tempfile.gettempdir()).resolve()
            if tmp in target.parents or target == tmp:
                return True
            return False
        except Exception:
            return False

    def _backup(self, path_obj: Path) -> Optional[Dict[str, Any]]:
        if not path_obj.exists():
            return None
        if path_obj.is_dir():
            return None

        backup_path = path_obj.with_suffix(path_obj.suffix + ".aegisbak")
        shutil.copy2(path_obj, backup_path)
        checksum = hashlib.sha256(path_obj.read_bytes()).hexdigest()
        return {
            "backup_path": str(backup_path),
            "src_path": str(path_obj),
            "checksum": checksum,
        }

    def read(self, path_obj: Path) -> SkillResult:
        if not path_obj.exists():
            return SkillResult.fail("File not found")
        if path_obj.is_dir():
            return SkillResult.fail("Path is a directory")

        try:
            content = path_obj.read_text(encoding="utf-8")
            return SkillResult.ok({"path": str(path_obj), "content": content})
        except Exception as exc:
            return SkillResult.fail(str(exc))

    def write(self, path_obj: Path, content: Optional[str]) -> SkillResult:
        if content is None:
            return SkillResult.fail("'content' parameter is required for write")

        if not self._check_within_project(path_obj):
            return SkillResult.fail("Write operation blocked: path outside project boundaries")

        backup = self._backup(path_obj)

        try:
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            path_obj.write_text(content, encoding="utf-8")
            return SkillResult.ok({"path": str(path_obj), "backup": backup})
        except Exception as exc:
            if backup and Path(backup["backup_path"]).exists():
                shutil.copy2(backup["backup_path"], path_obj)
            return SkillResult.fail(str(exc))

    def append(self, path_obj: Path, content: Optional[str]) -> SkillResult:
        if content is None:
            return SkillResult.fail("'content' parameter is required for append")

        if not self._check_within_project(path_obj):
            return SkillResult.fail("Append operation blocked: path outside project boundaries")

        try:
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            with path_obj.open("a", encoding="utf-8") as f:
                f.write(content)
            return SkillResult.ok({"path": str(path_obj)})
        except Exception as exc:
            return SkillResult.fail(str(exc))

    def delete(self, path_obj: Path, approved: bool = False) -> SkillResult:
        if not path_obj.exists():
            return SkillResult.fail("File not found")

        if not approved:
            return SkillResult.fail("Delete operation requires explicit approval")

        if not self._check_within_project(path_obj):
            return SkillResult.fail("Delete operation blocked: path outside project boundaries")

        try:
            if path_obj.is_dir():
                shutil.rmtree(path_obj)
            else:
                path_obj.unlink()
            return SkillResult.ok({"path": str(path_obj)})
        except Exception as exc:
            return SkillResult.fail(str(exc))

    def move(self, path_obj: Path, target: Path) -> SkillResult:
        if not path_obj.exists():
            return SkillResult.fail("Source path not found")

        if not self._check_within_project(path_obj) or not self._check_within_project(target):
            return SkillResult.fail("Move operation blocked: path outside project boundaries")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path_obj), str(target))
            return SkillResult.ok({"from": str(path_obj), "to": str(target)})
        except Exception as exc:
            return SkillResult.fail(str(exc))

    def copy(self, path_obj: Path, target: Path) -> SkillResult:
        if not path_obj.exists():
            return SkillResult.fail("Source path not found")

        if not self._check_within_project(path_obj) or not self._check_within_project(target):
            return SkillResult.fail("Copy operation blocked: path outside project boundaries")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if path_obj.is_dir():
                shutil.copytree(path_obj, target)
            else:
                shutil.copy2(path_obj, target)
            return SkillResult.ok({"from": str(path_obj), "to": str(target)})
        except Exception as exc:
            return SkillResult.fail(str(exc))

    def list_dir(self, path_obj: Path) -> SkillResult:
        if not path_obj.exists() or not path_obj.is_dir():
            return SkillResult.fail("Directory not found")

        try:
            content = [p.name for p in sorted(path_obj.iterdir())]
            return SkillResult.ok({"path": str(path_obj), "children": content})
        except Exception as exc:
            return SkillResult.fail(str(exc))
