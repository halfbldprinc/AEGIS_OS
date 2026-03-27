from typing import Any, Dict, List

from ..result import SkillResult
from ..skill import Skill
from .action_schema import ActionSchema, ParamSpec
from .file_skill import FileSkill


class BatchFileSkill(Skill):
    """Batched filesystem workflow skill built on top of FileSkill operations."""

    name = "file_batch"
    tier = 2
    allowed_actions = {"batch"}

    def __init__(self, file_skill: FileSkill | None = None):
        self._file_skill = file_skill or FileSkill()

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action != "batch":
            return SkillResult.fail(f"Unsupported action: {action}", error_code="UNSUPPORTED_ACTION")

        operations = params.get("operations", [])
        continue_on_error = bool(params.get("continue_on_error", False))

        if not isinstance(operations, list) or not operations:
            return SkillResult.fail("'operations' must be a non-empty list", error_code="INVALID_OPERATIONS")

        if len(operations) > 50:
            return SkillResult.fail("'operations' exceeds maximum batch size of 50", error_code="BATCH_TOO_LARGE")

        results = []
        succeeded = 0
        failed = 0

        for index, op in enumerate(operations):
            if not isinstance(op, dict):
                result = SkillResult.fail("operation must be an object", error_code="INVALID_OPERATION_ITEM")
            else:
                op_action = op.get("action")
                op_params = op.get("params", {})
                result = self._file_skill.execute(op_action, op_params)

            item = {
                "index": index,
                "success": result.success,
                "error": result.error,
                "error_code": result.error_code,
                "data": result.data,
            }
            results.append(item)

            if result.success:
                succeeded += 1
            else:
                failed += 1
                if not continue_on_error:
                    return SkillResult.fail(
                        "batch aborted after operation failure",
                        data={
                            "succeeded": succeeded,
                            "failed": failed,
                            "results": results,
                        },
                        error_code="BATCH_ABORTED",
                    )

        return SkillResult.ok(
            {
                "succeeded": succeeded,
                "failed": failed,
                "results": results,
            }
        )

    def get_permissions(self) -> List[str]:
        return ["batch"]

    def get_action_schemas(self) -> Dict[str, ActionSchema]:
        return {
            "batch": ActionSchema(
                params={
                    "operations": ParamSpec("operations", list, required=True, min_length=1, max_length=50, element_type=dict),
                    "continue_on_error": ParamSpec("continue_on_error", bool, required=False),
                },
                allow_extra=True,
            )
        }
