import pytest

from aegis.orchestrator import Orchestrator, Plan
from aegis.orchestrator.policy import DefaultExecutionPolicy
from aegis.result import SkillResult
from aegis.skill import Skill
from aegis.skills.action_schema import ActionSchema, ParamSpec
from aegis.skills.echo_skill import EchoSkill
from aegis.trust_ledger import TrustLedger


def test_orchestrator_with_echo_skill():
    orchestrator = Orchestrator()
    orchestrator.register_skill(EchoSkill())

    plan = Plan()
    plan.add_step(skill_name="echo", action="echo", params={"message": "hi"})

    result_plan = orchestrator.execute_plan(plan)
    assert result_plan.status == "SUCCEEDED"
    assert len(result_plan.steps) == 1
    step = result_plan.steps[0]
    assert step.result is not None
    assert step.result.success
    assert step.result.data == {"echo": "hi"}


def test_orchestrator_locks_denied_skill():
    orchestrator = Orchestrator()
    orchestrator.register_skill(EchoSkill())

    # Simulate trust ledger locking the skill
    ledger = orchestrator.trust_ledger
    for _ in range(50):
        ledger.record_outcome("echo", confirmed=True)
    for _ in range(13):
        ledger.record_outcome("echo", confirmed=False)

    plan = Plan()
    plan.add_step(skill_name="echo", action="echo", params={"message": "hi"})

    result_plan = orchestrator.execute_plan(plan, allow_failure=True)
    assert result_plan.steps[0].status == "DENIED"
    assert result_plan.steps[0].result is not None
    assert not result_plan.steps[0].result.success


def test_orchestrator_container_runner_tier2(monkeypatch):
    import shutil
    import subprocess
    from aegis.orchestrator.container_runner import ContainerizedRunner

    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/podman")

    class FakeCompleted:
        returncode = 0
        stdout = '{"success": true, "data": {"echo": "hi"}}'
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: FakeCompleted())

    orchestrator = Orchestrator(runner=ContainerizedRunner())

    class Tier2Echo(EchoSkill):
        tier = 2

    orchestrator.register_skill(Tier2Echo())

    plan = Plan()
    plan.add_step(skill_name="echo", action="echo", params={"message": "hi"})

    result_plan = orchestrator.execute_plan(plan)
    assert result_plan.status == "SUCCEEDED"
    assert result_plan.steps[0].result is not None
    assert result_plan.steps[0].result.success
    assert result_plan.steps[0].result.data["result"] == {"echo": "hi"}


def test_orchestrator_podman_runner_tier3(monkeypatch):
    import shutil
    import subprocess
    from aegis.orchestrator.container_runner import PodmanContainerRunner

    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/podman")

    class FakeCompleted:
        returncode = 0
        stdout = '{"success": true, "data": {"echo": "hi"}}'
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: FakeCompleted())

    orchestrator = Orchestrator(runner=PodmanContainerRunner(allow_network=False))

    class Tier3Echo(EchoSkill):
        tier = 3

    orchestrator.register_skill(Tier3Echo())

    plan = Plan()
    plan.add_step(skill_name="echo", action="echo", params={"message": "hi"})

    result_plan = orchestrator.execute_plan(plan)
    assert result_plan.status == "SUCCEEDED"
    assert result_plan.steps[0].result is not None
    assert result_plan.steps[0].result.success
    assert result_plan.steps[0].result.data["result"] == {"echo": "hi"}


def test_orchestrator_step_on_failure_skip():
    class FailingSkill(EchoSkill):
        name = "failing"

        def execute(self, action, params):
            return SkillResult.fail("boom")

        def get_permissions(self):
            return []

    orchestrator = Orchestrator()
    orchestrator.register_skill(FailingSkill())

    plan = Plan()
    step = plan.add_step(skill_name="failing", action="anything", params={})
    step.on_failure = "skip"

    result_plan = orchestrator.execute_plan(plan)
    assert result_plan.status == "SUCCEEDED"
    assert result_plan.steps[0].status == "FAILED"


def test_orchestrator_step_retry_until_success():
    class FlakySkill(EchoSkill):
        name = "flaky"

        def __init__(self):
            self.call_count = 0

        def execute(self, action, params):
            self.call_count += 1
            if self.call_count < 2:
                return SkillResult.fail("temporarily unavailable")
            return SkillResult.ok({"echo": "ok"})

        def get_permissions(self):
            return []

    orchestrator = Orchestrator()
    orchestrator.register_skill(FlakySkill())

    plan = Plan()
    step = plan.add_step(skill_name="flaky", action="anything", params={})
    step.max_retries = 2

    result_plan = orchestrator.execute_plan(plan)
    assert result_plan.status == "SUCCEEDED"
    assert result_plan.steps[0].attempts == 2
    assert result_plan.steps[0].status == "SUCCEEDED"


def test_orchestrator_guardian_denies_without_permission():
    from aegis.guardian import Guardian

    guardian = Guardian(db_path=":memory:")
    orchestrator = Orchestrator(guardian=guardian)

    class RestrictedEcho(EchoSkill):
        name = "restricted"

        def get_permissions(self):
            return ["read"]

    orchestrator.register_skill(RestrictedEcho())

    plan = Plan()
    plan.add_step(skill_name="restricted", action="write", params={"message": "hi"})

    result_plan = orchestrator.execute_plan(plan, allow_failure=True)
    assert result_plan.steps[0].status == "DENIED"
    assert result_plan.steps[0].result is not None
    assert not result_plan.steps[0].result.success

def test_orchestrator_guardian_allows_explicit_action_permission():
    from aegis.guardian import Guardian

    guardian = Guardian(db_path=":memory:")
    guardian.grant("echo", "echo")
    orchestrator = Orchestrator(guardian=guardian)
    orchestrator.register_skill(EchoSkill())

    plan = Plan()
    plan.add_step(skill_name="echo", action="echo", params={"message": "hi"})

    result_plan = orchestrator.execute_plan(plan)
    assert result_plan.status == "SUCCEEDED"
    assert result_plan.steps[0].status == "SUCCEEDED"
    assert result_plan.steps[0].result.success


def test_orchestrator_simulate_plan_allowed():
    orchestrator = Orchestrator()
    orchestrator.register_skill(EchoSkill())

    plan = Plan()
    plan.add_step(skill_name="echo", action="echo", params={"message": "hello"})

    result = orchestrator.simulate_plan(plan)

    assert result["status"] == "SIMULATED"
    assert len(result["steps"]) == 1
    assert result["steps"][0]["status"] == "ALLOWED"


def test_orchestrator_simulate_plan_denied_by_guardian():
    from aegis.guardian import Guardian

    guardian = Guardian(db_path=":memory:")
    orchestrator = Orchestrator(guardian=guardian)
    orchestrator.register_skill(EchoSkill())
    guardian.revoke("echo", "all")

    plan = Plan()
    plan.add_step(skill_name="echo", action="echo", params={"message": "hello"})

    result = orchestrator.simulate_plan(plan)

    assert result["status"] == "SIMULATED"
    assert len(result["steps"]) == 1
    assert result["steps"][0]["status"] == "DENIED"
    assert result["steps"][0]["reason"] == "guardian_denied"


def test_orchestrator_cost_budget_policy():
    from aegis.orchestrator.policy import CostBudgetPolicy

    orchestrator = Orchestrator(policy=CostBudgetPolicy(max_step_cost=1.0, max_plan_cost=1.0))
    orchestrator.register_skill(EchoSkill())

    plan = Plan()
    plan.add_step(skill_name="echo", action="echo", params={"message": "hi", "estimated_cost": 2.0, "plan_cost": 0.0})

    result_plan = orchestrator.execute_plan(plan, allow_failure=True)
    assert result_plan.status == "FAILED" or result_plan.steps[0].status == "DENIED"


def test_default_policy_allowlist_blocks_unlisted_action():
    policy = DefaultExecutionPolicy(
        enforce_action_allowlist=True,
        allowlist={"echo": ["echo"]},
    )
    decision = policy.evaluate(
        skill_name="shell",
        action="run",
        params={},
        trust_ledger=TrustLedger(),
    )

    assert not decision.allowed
    assert "allowlist" in decision.reason


def test_default_policy_allowlist_allows_confirmed_override():
    policy = DefaultExecutionPolicy(
        enforce_action_allowlist=True,
        allowlist={"echo": ["echo"]},
    )
    decision = policy.evaluate(
        skill_name="shell",
        action="run",
        params={"confirmed": True},
        trust_ledger=TrustLedger(),
    )

    assert decision.allowed
    assert decision.reason == "allowed_by_confirmation"


def test_container_runner_sbom_and_vuln_scan():
    from aegis.orchestrator.container_runner import ContainerizedRunner

    runner = ContainerizedRunner(image_tag="aegis/skill-runtime:latest")
    sbom = runner.generate_sbom(runner.image_tag)
    assert "components" in sbom

    scan = runner.vulnerability_scan(runner.image_tag)
    assert scan["status"] == "clean"


def test_tier2_skill_without_network_permission_can_execute(monkeypatch):
    import shutil
    import subprocess
    from aegis.orchestrator.container_runner import ContainerizedRunner

    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/podman")

    class FakeCompleted:
        returncode = 0
        stdout = '{"success": true, "data": {"echo": "ok"}}'
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: FakeCompleted())

    class Tier2NoNetwork(EchoSkill):
        tier = 2

        def get_permissions(self):
            return ["echo"]

    orchestrator = Orchestrator(runner=ContainerizedRunner())
    orchestrator.register_skill(Tier2NoNetwork())

    plan = Plan()
    plan.add_step(skill_name="echo", action="echo", params={"message": "hi"})

    result_plan = orchestrator.execute_plan(plan)
    assert result_plan.status == "SUCCEEDED"
    assert result_plan.steps[0].result is not None
    assert result_plan.steps[0].result.success


def test_tier2_network_required_only_for_network_skills(monkeypatch):
    import shutil
    import subprocess
    from aegis.orchestrator.container_runner import ContainerizedRunner

    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/podman")

    class FakeCompleted:
        returncode = 0
        stdout = '{"success": true, "data": {"echo": "ok"}}'
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: FakeCompleted())

    class Tier2NetworkSkill(EchoSkill):
        name = "tier2net"
        tier = 2

        def get_permissions(self):
            return ["echo", "network"]

    orchestrator = Orchestrator(runner=ContainerizedRunner())
    orchestrator.register_skill(Tier2NetworkSkill())
    orchestrator.guardian.revoke("tier2net", "network")

    plan = Plan()
    plan.add_step(skill_name="tier2net", action="echo", params={"message": "hi"})

    result_plan = orchestrator.execute_plan(plan, allow_failure=True)
    assert result_plan.steps[0].status == "DENIED"
    assert "network access denied" in (result_plan.steps[0].result.error or "")


def test_orchestrator_denies_invalid_action_in_preflight():
    class StrictEcho(EchoSkill):
        name = "strict_echo"
        allowed_actions = {"echo"}

    orchestrator = Orchestrator()
    orchestrator.register_skill(StrictEcho())

    plan = Plan()
    plan.add_step(skill_name="strict_echo", action="not_supported", params={"message": "hi"})

    result_plan = orchestrator.execute_plan(plan, allow_failure=True)
    assert result_plan.status == "FAILED"
    assert result_plan.steps[0].status == "DENIED"
    assert "not allowed" in (result_plan.steps[0].result.error or "")


def test_orchestrator_simulate_marks_requires_confirmation():
    orchestrator = Orchestrator()
    orchestrator.register_skill(EchoSkill())

    plan = Plan()
    step = plan.add_step(skill_name="echo", action="echo", params={"message": "hello"})
    step.requires_confirmation = True

    result = orchestrator.simulate_plan(plan)
    assert result["status"] == "SIMULATED"
    assert result["steps"][0]["status"] == "DENIED"
    assert result["steps"][0]["reason"] == "requires_confirmation"


def test_inprocess_runner_enforces_skill_timeout():
    import time

    from aegis.orchestrator.container_runner import InProcessRunner
    from aegis.skill import Skill
    from aegis.result import SkillResult

    class SlowSkill(Skill):
        name = "slow"
        tier = 1

        def execute(self, action, params):
            time.sleep(0.2)
            return SkillResult.ok({"done": True})

        def get_permissions(self):
            return ["none"]

        def get_timeout(self, action):
            return 1

    runner = InProcessRunner()
    result = runner.run(SlowSkill(), "do", {}, timeout_seconds=0.05)
    assert not result.success
    assert "timed out" in (result.error or "")


def test_orchestrator_runner_timeout_compatibility_fallback():
    class LegacyRunner:
        def run(self, skill_name, action, params):
            return SkillResult.ok({"legacy": True})

    out = Orchestrator._run_runner_with_optional_timeout(
        LegacyRunner(),
        "echo",
        "echo",
        {"message": "hello"},
        5,
    )
    assert out.success
    assert out.data["legacy"] is True


def test_orchestrator_runner_timeout_fallback_does_not_swallow_unrelated_type_errors():
    class LegacyRunnerBroken:
        def run(self, skill_name, action, params):
            raise TypeError("broken legacy runner")

    with pytest.raises(TypeError, match="broken legacy runner"):
        Orchestrator._run_runner_with_optional_timeout(
            LegacyRunnerBroken(),
            "echo",
            "echo",
            {"message": "hello"},
            5,
        )


def test_orchestrator_denies_invalid_params_with_specific_error_code():
    class SchemaSkill(Skill):
        name = "schema"
        tier = 1
        allowed_actions = {"run"}

        def execute(self, action, params):
            return SkillResult.ok({"ok": True})

        def get_permissions(self):
            return ["echo"]

        def get_action_schemas(self):
            return {
                "run": ActionSchema(
                    params={
                        "count": ParamSpec("count", int, required=True, min_value=1, max_value=10),
                    },
                    allow_extra=False,
                )
            }

    orchestrator = Orchestrator()
    orchestrator.register_skill(SchemaSkill())

    plan = Plan()
    plan.add_step(skill_name="schema", action="run", params={"count": 0})

    result_plan = orchestrator.execute_plan(plan, allow_failure=True)
    assert result_plan.status == "SUCCEEDED"
    assert result_plan.steps[0].status == "DENIED"
    assert result_plan.steps[0].result is not None
    assert result_plan.steps[0].result.error_code == "PARAM_BELOW_MIN"


def test_orchestrator_skill_action_telemetry_tracks_denials_and_successes():
    orchestrator = Orchestrator()
    orchestrator.register_skill(EchoSkill())

    denied_plan = Plan()
    denied_plan.add_step(skill_name="echo", action="echo", params={"message": "one"})
    orchestrator.guardian.revoke("echo", "echo")
    orchestrator.execute_plan(denied_plan, allow_failure=True)

    allowed_plan = Plan()
    allowed_plan.add_step(skill_name="echo", action="echo", params={"message": "two"})
    orchestrator.guardian.grant("echo", "echo")
    orchestrator.execute_plan(allowed_plan)

    telemetry = orchestrator.get_skill_action_telemetry()
    key = "echo:echo"
    assert key in telemetry
    assert telemetry[key]["denials"] >= 1
    assert telemetry[key]["successes"] >= 1
    assert telemetry[key]["error_codes"]


def test_orchestrator_retry_telemetry_keeps_request_invariants():
    class FlakySkill(EchoSkill):
        name = "telemetry_flaky"

        def __init__(self):
            self.calls = 0

        def execute(self, action, params):
            self.calls += 1
            if self.calls == 1:
                return SkillResult.fail("temporarily unavailable", error_code="TEMP_UNAVAILABLE")
            return SkillResult.ok({"done": True})

        def get_permissions(self):
            return ["echo"]

    orchestrator = Orchestrator()
    orchestrator.register_skill(FlakySkill())

    plan = Plan()
    step = plan.add_step(skill_name="telemetry_flaky", action="echo", params={})
    step.max_retries = 1

    result = orchestrator.execute_plan(plan)
    assert result.status == "SUCCEEDED"

    key = "telemetry_flaky:echo"
    telemetry = orchestrator.get_skill_action_telemetry()[key]
    assert telemetry["retries"] == 1
    assert telemetry["successes"] == 1
    assert telemetry["failures"] == 1
    assert telemetry["requests"] == telemetry["successes"] + telemetry["failures"] + telemetry["denials"]
