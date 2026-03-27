import json
from typing import Any, Dict, List

from ..result import SkillResult
from ..skill import Skill
from .action_schema import ActionSchema, ParamSpec


class JsonTransformSkill(Skill):
    """JSON parsing and transformation workflow skill."""

    name = "json_transform"
    tier = 1
    allowed_actions = {"parse", "extract", "merge", "project"}

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action == "parse":
            return self._parse(params)
        if action == "extract":
            return self._extract(params)
        if action == "merge":
            return self._merge(params)
        if action == "project":
            return self._project(params)
        return SkillResult.fail(f"Unsupported action: {action}", error_code="UNSUPPORTED_ACTION")

    def _parse(self, params: Dict[str, Any]) -> SkillResult:
        raw = params.get("text")
        if raw is None:
            return SkillResult.fail("'text' parameter is required", error_code="MISSING_TEXT")
        try:
            return SkillResult.ok({"json": json.loads(raw)})
        except Exception as exc:
            return SkillResult.fail(str(exc), error_code="INVALID_JSON")

    def _extract(self, params: Dict[str, Any]) -> SkillResult:
        data = params.get("data")
        path = params.get("path")
        if not isinstance(data, (dict, list)):
            return SkillResult.fail("'data' must be an object or list", error_code="INVALID_DATA")
        if not isinstance(path, str) or not path:
            return SkillResult.fail("'path' parameter is required", error_code="MISSING_PATH")

        current: Any = data
        for token in path.split("."):
            if isinstance(current, dict) and token in current:
                current = current[token]
                continue
            if isinstance(current, list) and token.isdigit():
                index = int(token)
                if 0 <= index < len(current):
                    current = current[index]
                    continue
            return SkillResult.fail(f"path token '{token}' not found", error_code="PATH_NOT_FOUND")

        return SkillResult.ok({"value": current})

    def _merge(self, params: Dict[str, Any]) -> SkillResult:
        base = params.get("base")
        override = params.get("override")
        if not isinstance(base, dict) or not isinstance(override, dict):
            return SkillResult.fail("'base' and 'override' must be objects", error_code="INVALID_MERGE_PAYLOAD")

        merged = dict(base)
        merged.update(override)
        return SkillResult.ok({"json": merged})

    def _project(self, params: Dict[str, Any]) -> SkillResult:
        data = params.get("data")
        fields = params.get("fields")
        if not isinstance(data, dict):
            return SkillResult.fail("'data' must be an object", error_code="INVALID_DATA")
        if not isinstance(fields, list) or not all(isinstance(x, str) for x in fields):
            return SkillResult.fail("'fields' must be a list of strings", error_code="INVALID_FIELDS")

        projected = {key: data[key] for key in fields if key in data}
        return SkillResult.ok({"json": projected})

    def get_permissions(self) -> List[str]:
        return ["parse", "extract", "merge", "project"]

    def get_action_schemas(self) -> Dict[str, ActionSchema]:
        return {
            "parse": ActionSchema(
                params={
                    "text": ParamSpec("text", str, required=True, min_length=2, max_length=2_000_000),
                }
            ),
            "extract": ActionSchema(
                params={
                    "data": ParamSpec("data", (dict, list), required=True),
                    "path": ParamSpec("path", str, required=True, min_length=1, max_length=500),
                }
            ),
            "merge": ActionSchema(
                params={
                    "base": ParamSpec("base", dict, required=True),
                    "override": ParamSpec("override", dict, required=True),
                }
            ),
            "project": ActionSchema(
                params={
                    "data": ParamSpec("data", dict, required=True),
                    "fields": ParamSpec("fields", list, required=True, min_length=1, max_length=500, element_type=str),
                }
            ),
        }
