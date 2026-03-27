from dataclasses import dataclass
from typing import Any, Optional

@dataclass(frozen=True)
class SkillResult:
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    @classmethod
    def ok(cls, data: Any = None) -> "SkillResult":
        return cls(success=True, data=data)

    @classmethod
    def fail(
        cls,
        error: str,
        data: Any = None,
        error_code: Optional[str] = None,
    ) -> "SkillResult":
        return cls(success=False, data=data, error=error, error_code=error_code)

    def is_ok(self) -> bool:
        return self.success

    def is_fail(self) -> bool:
        return not self.success
