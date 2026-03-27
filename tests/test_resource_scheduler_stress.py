import time
import psutil
from aegis.resource_scheduler import ResourceScheduler, ResourcePolicy


def test_resource_scheduler_stress_small():
    scheduler = ResourceScheduler(policy=ResourcePolicy(cpu_threshold=0.95, memory_threshold=0.95, wasmem_threshold=0.95))
    for _ in range(10):
        decision = scheduler.schedule_yield()
        assert isinstance(decision["throttle"], bool)
        time.sleep(0.01)


def test_resource_scheduler_cgroup_path_fallback(tmp_path, monkeypatch):
    fake_cgroup = tmp_path / "cgroup"
    fake_cgroup.mkdir()

    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=0.1: 95.0)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: type("T", (), {"percent": 95.0})())
    monkeypatch.setattr(psutil, "swap_memory", lambda: type("T", (), {"percent": 95.0})())

    scheduler = ResourceScheduler(policy=ResourcePolicy(cpu_threshold=0.5, memory_threshold=0.5, wasmem_threshold=0.5), cgroup_base_path=str(fake_cgroup))
    decision = scheduler.schedule_yield()
    assert decision["throttle"] is True


def test_resource_scheduler_stress_run_many_cycles(tmp_path, monkeypatch):
    state = {"counter": 0}

    def fake_cpu_percent(interval=0.1):
        state["counter"] += 1
        return 95.0 if state["counter"] % 2 == 0 else 15.0

    class FakeVM:
        def __init__(self, percent):
            self.percent = percent

    monkeypatch.setattr(psutil, "cpu_percent", fake_cpu_percent)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: FakeVM(35.0))
    monkeypatch.setattr(psutil, "swap_memory", lambda: FakeVM(10.0))

    scheduler = ResourceScheduler(policy=ResourcePolicy(cpu_threshold=0.6, memory_threshold=0.8, wasmem_threshold=0.8), cgroup_base_path=str(tmp_path / "cgroup"))
    decisions = [scheduler.schedule_yield() for _ in range(100)]

    assert len(decisions) == 100
    assert scheduler.get_metrics()["decision_count"] == 100
    assert any(d["throttle"] for d in decisions)

