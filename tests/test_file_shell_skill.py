from aegis.skills.file_skill import FileSkill
from aegis.skills.shell_skill import ShellSkill


def test_file_write_read_delete(tmp_path):
    skill = FileSkill()
    file_path = tmp_path / "test.txt"

    res = skill.execute("write", {"path": str(file_path), "content": "hello"})
    assert res.success

    res = skill.execute("read", {"path": str(file_path)})
    assert res.success
    assert res.data["content"] == "hello"

    res = skill.execute("append", {"path": str(file_path), "content": " world"})
    assert res.success

    res = skill.execute("read", {"path": str(file_path)})
    assert res.success
    assert res.data["content"] == "hello world"

    res = skill.execute("delete", {"path": str(file_path)})
    assert not res.success
    assert "explicit approval" in (res.error or "")

    res = skill.execute("delete", {"path": str(file_path), "approved": True})
    assert res.success
    assert not file_path.exists()


def test_file_list_move_copy(tmp_path):
    skill = FileSkill()
    dir_path = tmp_path / "dir"
    dir_path.mkdir()
    (dir_path / "a.txt").write_text("a")

    res = skill.execute("list", {"path": str(dir_path)})
    assert res.success
    assert "a.txt" in res.data["children"]

    target_path = tmp_path / "b.txt"
    res = skill.execute("copy", {"path": str(dir_path / "a.txt"), "target": str(target_path)})
    assert res.success
    assert target_path.exists()

    move_target = tmp_path / "c.txt"
    res = skill.execute("move", {"path": str(target_path), "target": str(move_target)})
    assert res.success
    assert move_target.exists()


def test_shell_run_cmd(tmp_path):
    skill = ShellSkill()
    res = skill.execute("run", {"command": "echo hello", "cwd": str(tmp_path), "timeout": 10})
    assert res.success
    assert "hello" in res.data["stdout"]


def test_shell_rejects_disallowed_command(tmp_path):
    skill = ShellSkill()
    res = skill.execute("run", {"command": "rm some_file", "cwd": str(tmp_path), "timeout": 10})
    assert not res.success
    assert "blocked by whitelist" in (res.error or "")


def test_shell_rejects_unsafe_cwd():
    skill = ShellSkill()
    res = skill.execute("run", {"command": "echo hello", "cwd": "/etc", "timeout": 10})
    assert not res.success
    assert "outside allowed boundaries" in (res.error or "")
