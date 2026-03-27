from aegis.daemon import AegisDaemon
from aegis.state import SystemState
from aegis.storage import InMemoryStateStorage


class FailingRuntime:
    def stop(self):
        return None

    def start(self):
        raise RuntimeError("runtime unavailable")


def create_daemon() -> AegisDaemon:
    return AegisDaemon(state=SystemState(storage=InMemoryStateStorage()))


def test_soak_test_reports_success_rate():
    daemon = create_daemon()
    result = daemon.run_soak_test(cycles=3, sleep_s=0.0)

    assert result["cycles"] == 3
    assert 0.0 <= result["success_rate"] <= 1.0


def test_chaos_llm_restart_degraded(monkeypatch):
    daemon = create_daemon()
    daemon.llm_runtime = FailingRuntime()

    result = daemon.run_chaos_scenario("llm_restart")
    assert result["status"] in {"degraded", "failed"}


def test_chaos_voice_interrupt_recovered():
    daemon = create_daemon()
    result = daemon.run_chaos_scenario("voice_interrupt")
    assert result["status"] == "recovered"
