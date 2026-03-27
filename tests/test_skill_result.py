from aegis.result import SkillResult


def test_skill_result_ok():
    r = SkillResult.ok({"hello": "world"})
    assert r.success
    assert r.data == {"hello": "world"}
    assert r.is_ok()
    assert not r.is_fail()


def test_skill_result_fail():
    r = SkillResult.fail("error", data={"reason": "bad"})
    assert not r.success
    assert r.error == "error"
    assert r.data == {"reason": "bad"}
    assert r.is_fail()
