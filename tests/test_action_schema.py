from aegis.skills.action_schema import ActionSchema, ParamSpec, SkillActionSchemaValidator


def test_schema_validator_required_type_and_bounds():
    validator = SkillActionSchemaValidator()
    schema = ActionSchema(
        params={
            "name": ParamSpec("name", str, required=True, min_length=2, max_length=10),
            "count": ParamSpec("count", int, required=True, min_value=1, max_value=5),
        },
        allow_extra=False,
    )

    missing = validator.validate("run", {"count": 1}, schema)
    assert missing is not None
    assert missing.error_code == "MISSING_REQUIRED_PARAM"

    wrong_type = validator.validate("run", {"name": "ok", "count": "1"}, schema)
    assert wrong_type is not None
    assert wrong_type.error_code == "INVALID_PARAM_TYPE"

    out_of_bounds = validator.validate("run", {"name": "ok", "count": 6}, schema)
    assert out_of_bounds is not None
    assert out_of_bounds.error_code == "PARAM_ABOVE_MAX"

    unexpected = validator.validate("run", {"name": "ok", "count": 2, "extra": True}, schema)
    assert unexpected is not None
    assert unexpected.error_code == "UNEXPECTED_PARAMS"

    valid = validator.validate("run", {"name": "good", "count": 2}, schema)
    assert valid is None
