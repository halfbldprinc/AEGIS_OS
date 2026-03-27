from dataclasses import dataclass, field
import re
from typing import Any, Dict, Iterable, Optional, Tuple


@dataclass(frozen=True)
class ParamSpec:
    name: str
    param_type: type | Tuple[type, ...]
    required: bool = False
    min_value: float | None = None
    max_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    choices: Iterable[Any] | None = None
    pattern: str | None = None
    element_type: type | None = None


@dataclass(frozen=True)
class ActionSchema:
    params: Dict[str, ParamSpec] = field(default_factory=dict)
    allow_extra: bool = True


@dataclass(frozen=True)
class ValidationError:
    message: str
    error_code: str


class SkillActionSchemaValidator:
    """Unified validator for skill action parameters (required/type/bounds)."""

    def validate(self, action: str, params: Dict[str, Any], schema: ActionSchema | None) -> Optional[ValidationError]:
        if schema is None:
            return None

        if not isinstance(params, dict):
            return ValidationError("params must be an object", "INVALID_PARAMS_TYPE")

        for name, spec in schema.params.items():
            if spec.required and name not in params:
                return ValidationError(f"missing required parameter '{name}'", "MISSING_REQUIRED_PARAM")

            if name not in params:
                continue

            value = params[name]
            if value is None and spec.required:
                return ValidationError(f"parameter '{name}' cannot be null", "INVALID_PARAM_VALUE")
            if value is None:
                continue

            if not isinstance(value, spec.param_type):
                expected = (
                    ",".join(t.__name__ for t in spec.param_type)
                    if isinstance(spec.param_type, tuple)
                    else spec.param_type.__name__
                )
                return ValidationError(
                    f"parameter '{name}' must be of type {expected}",
                    "INVALID_PARAM_TYPE",
                )

            if isinstance(value, (int, float)):
                if spec.min_value is not None and value < spec.min_value:
                    return ValidationError(
                        f"parameter '{name}' must be >= {spec.min_value}",
                        "PARAM_BELOW_MIN",
                    )
                if spec.max_value is not None and value > spec.max_value:
                    return ValidationError(
                        f"parameter '{name}' must be <= {spec.max_value}",
                        "PARAM_ABOVE_MAX",
                    )

            if isinstance(value, (str, list, tuple, dict)):
                length = len(value)
                if spec.min_length is not None and length < spec.min_length:
                    return ValidationError(
                        f"parameter '{name}' length must be >= {spec.min_length}",
                        "PARAM_LENGTH_BELOW_MIN",
                    )
                if spec.max_length is not None and length > spec.max_length:
                    return ValidationError(
                        f"parameter '{name}' length must be <= {spec.max_length}",
                        "PARAM_LENGTH_ABOVE_MAX",
                    )

            if spec.choices is not None and value not in set(spec.choices):
                return ValidationError(
                    f"parameter '{name}' must be one of {list(spec.choices)}",
                    "PARAM_INVALID_CHOICE",
                )

            if spec.pattern and isinstance(value, str):
                if not re.fullmatch(spec.pattern, value):
                    return ValidationError(
                        f"parameter '{name}' does not match required format",
                        "PARAM_PATTERN_MISMATCH",
                    )

            if spec.element_type and isinstance(value, list):
                for idx, element in enumerate(value):
                    if not isinstance(element, spec.element_type):
                        return ValidationError(
                            f"parameter '{name}[{idx}]' must be {spec.element_type.__name__}",
                            "PARAM_INVALID_ELEMENT_TYPE",
                        )

        if not schema.allow_extra:
            allowed = set(schema.params.keys())
            extras = [k for k in params.keys() if k not in allowed]
            if extras:
                return ValidationError(
                    f"unexpected parameters: {extras}",
                    "UNEXPECTED_PARAMS",
                )

        return None
