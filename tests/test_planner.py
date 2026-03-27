import json

from aegis.planner import Planner
from aegis.llm.runtime import LLMRuntime
from aegis.orchestrator import Orchestrator, Plan
from aegis.skills.echo_skill import EchoSkill
from aegis.skill import Skill
from aegis.result import SkillResult


class DummyLLMRuntime(LLMRuntime):
    def generate(self, messages, temperature=0.7, max_tokens=1024, grammar=None):
        return json.dumps({
            "plan_name": "automated",
            "steps": [
                {"skill": "echo", "action": "echo", "params": {"message": "planned"}}
            ]
        })


def test_planner_produces_plan_from_llm():
    orchestrator = Orchestrator()
    orchestrator.register_skill(EchoSkill())
    planner = Planner(llm_runtime=DummyLLMRuntime(), orchestrator=orchestrator)

    plan = planner.plan("say hi")
    assert len(plan.steps) == 1
    assert plan.steps[0].skill_name == "echo"

    result = orchestrator.execute_plan(plan)
    assert result.status == "SUCCEEDED"
    assert result.steps[0].result.success
    assert result.steps[0].result.data == {"echo": "planned"}


def test_planner_fallback_if_malformed_output():
    class Glam(LLMRuntime):
        def generate(self, *args, **kwargs):
            return "not a valid json"

    orchestrator = Orchestrator()
    orchestrator.register_skill(EchoSkill())
    planner = Planner(llm_runtime=Glam(), orchestrator=orchestrator)

    plan = planner.plan("ping")
    assert len(plan.steps) == 1
    assert plan.steps[0].skill_name == "echo"
    assert plan.steps[0].action == "echo"


def test_planner_simulation():
    orchestrator = Orchestrator()
    orchestrator.register_skill(EchoSkill())
    planner = Planner(llm_runtime=DummyLLMRuntime(), orchestrator=orchestrator)

    sim = planner.simulate("say hi")
    assert sim["status"] == "SIMULATED"
    assert sim["steps"][0]["status"] == "ALLOWED"


def test_planner_does_not_mutate_input_conversation_history():
    orchestrator = Orchestrator()
    orchestrator.register_skill(EchoSkill())
    planner = Planner(llm_runtime=DummyLLMRuntime(), orchestrator=orchestrator)

    history = [{"role": "user", "content": "previous"}]
    before = list(history)
    planner.plan("say hi", conversation_history=history)

    assert history == before


class _NamedSkill(Skill):
    def __init__(self, name: str):
        self.name = name
        self.tier = 1

    def execute(self, action, params):
        return SkillResult.ok({"action": action, "params": params})

    def get_permissions(self):
        return ["all"]


def test_planner_rule_fallback_routes_web_search():
    class Broken(LLMRuntime):
        def generate(self, *args, **kwargs):
            return "bad-json"

    orchestrator = Orchestrator()
    orchestrator.register_skill(_NamedSkill("web_search"))
    planner = Planner(llm_runtime=Broken(), orchestrator=orchestrator)

    plan = planner.plan("search web for local llama setup")
    assert len(plan.steps) == 1
    assert plan.steps[0].skill_name == "web_search"
    assert plan.steps[0].action == "search"
    assert "local llama setup" in plan.steps[0].params["query"]


def test_planner_rule_fallback_routes_reminder_and_browser():
    class Broken(LLMRuntime):
        def generate(self, *args, **kwargs):
            return "bad-json"

    orchestrator = Orchestrator()
    orchestrator.register_skill(_NamedSkill("reminder"))
    orchestrator.register_skill(_NamedSkill("browser"))
    planner = Planner(llm_runtime=Broken(), orchestrator=orchestrator)

    reminder_plan = planner.plan("remind me to call mom in 10 minutes")
    assert reminder_plan.steps[0].skill_name == "reminder"
    assert reminder_plan.steps[0].action == "add"
    assert reminder_plan.steps[0].params["title"] == "call mom"

    browser_plan = planner.plan("open https://example.com")
    assert browser_plan.steps[0].skill_name == "browser"
    assert browser_plan.steps[0].action == "open_url"
    assert browser_plan.steps[0].params["url"] == "https://example.com"


def test_planner_prompts_and_high_risk_labels():
    orchestrator = Orchestrator()
    orchestrator.register_skill(_NamedSkill("os_control"))
    planner = Planner(llm_runtime=DummyLLMRuntime(), orchestrator=orchestrator)

    plan = planner.plan("launch TextEdit")
    assert any(step.requires_confirmation for step in plan.steps) is False

    plan2 = Plan()
    plan2.add_step(skill_name="os_control", action="close", params={})
    # this setter normally from planner; mimic behavior
    plan2.steps[0].requires_confirmation = planner._is_high_risk_step("os_control", "close")
    assert plan2.steps[0].requires_confirmation
