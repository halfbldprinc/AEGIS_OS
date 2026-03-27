from aegis.skills.json_transform_skill import JsonTransformSkill


def test_json_transform_parse_extract_merge_project():
    skill = JsonTransformSkill()

    parsed = skill.execute("parse", {"text": '{"user": {"id": 7, "name": "Ada"}, "tags": ["x", "y"]}'})
    assert parsed.success
    data = parsed.data["json"]

    extracted = skill.execute("extract", {"data": data, "path": "user.name"})
    assert extracted.success
    assert extracted.data["value"] == "Ada"

    merged = skill.execute("merge", {"base": {"a": 1}, "override": {"b": 2}})
    assert merged.success
    assert merged.data["json"] == {"a": 1, "b": 2}

    projected = skill.execute("project", {"data": {"a": 1, "b": 2, "c": 3}, "fields": ["a", "c"]})
    assert projected.success
    assert projected.data["json"] == {"a": 1, "c": 3}


def test_json_transform_reports_error_codes():
    skill = JsonTransformSkill()

    bad_parse = skill.execute("parse", {})
    assert not bad_parse.success
    assert bad_parse.error_code == "MISSING_TEXT"

    bad_extract = skill.execute("extract", {"data": {"x": 1}, "path": "y"})
    assert not bad_extract.success
    assert bad_extract.error_code == "PATH_NOT_FOUND"
