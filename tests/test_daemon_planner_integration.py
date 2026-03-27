from aegis.daemon import AegisDaemon
from aegis.skills.llm_skill import LLMSkill
from aegis.llm.runtime import LLMRuntime


class StaticLLM(LLMRuntime):
    def generate(self, messages, temperature=0.7, max_tokens=1024, grammar=None):
        return '{"plan_name":"x","steps":[{"skill":"echo","action":"echo","params":{"message":"daemon-response"}}]}'


def test_daemon_process_input_queue():
    daemon = AegisDaemon()
    daemon.llm_runtime = StaticLLM()
    daemon.planner.llm_runtime = daemon.llm_runtime
    daemon.orchestrator.skills.pop("llm", None)
    daemon.orchestrator.register_skill(LLMSkill(llm_runtime=daemon.llm_runtime))

    for _ in range(50):
        daemon.trust_ledger.record_outcome("echo", confirmed=True)

    daemon.enqueue_input("Hello")
    daemon.run_cycle()  # observation mode first; may spawn shadow

    # force active mode and process
    daemon.state.set("mode", daemon.ACTIVE_MODE)
    daemon.enqueue_input("Hello")

    daemon.run_cycle()
    assert len(daemon.plan_store) >= 1
    plan = list(daemon.plan_store.values())[-1]
    assert plan.status == "SUCCEEDED"
