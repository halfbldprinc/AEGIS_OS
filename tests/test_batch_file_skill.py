from aegis.skills.batch_file_skill import BatchFileSkill


def test_batch_file_skill_executes_batch_successfully(tmp_path):
    skill = BatchFileSkill()
    target = tmp_path / "batch.txt"

    result = skill.execute(
        "batch",
        {
            "operations": [
                {"action": "write", "params": {"path": str(target), "content": "hello"}},
                {"action": "append", "params": {"path": str(target), "content": " world"}},
                {"action": "read", "params": {"path": str(target)}},
            ]
        },
    )

    assert result.success
    assert result.data["succeeded"] == 3
    assert result.data["failed"] == 0
    assert result.data["results"][2]["data"]["content"] == "hello world"


def test_batch_file_skill_aborts_without_continue_on_error(tmp_path):
    skill = BatchFileSkill()
    target = tmp_path / "missing" / "file.txt"

    result = skill.execute(
        "batch",
        {
            "operations": [
                {"action": "read", "params": {"path": str(target)}},
                {"action": "write", "params": {"path": str(tmp_path / "later.txt"), "content": "ok"}},
            ],
            "continue_on_error": False,
        },
    )

    assert not result.success
    assert result.error_code == "BATCH_ABORTED"
    assert result.data["failed"] == 1
    assert result.data["succeeded"] == 0
