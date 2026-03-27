import psutil
from aegis.resource_scheduler import ResourceScheduler, ResourcePolicy


def test_scheduler_low_usage():
    scheduler = ResourceScheduler(policy=ResourcePolicy(cpu_threshold=1.0, memory_threshold=1.0, wasmem_threshold=1.0))
    decision = scheduler.schedule_yield()
    assert decision["throttle"] is False


def test_scheduler_high_usage():
    scheduler = ResourceScheduler(policy=ResourcePolicy(cpu_threshold=0.001, memory_threshold=0.001, wasmem_threshold=0.001))
    decision = scheduler.schedule_yield()
    assert decision["throttle"] is True


def test_scheduler_cgroup_throttle_fallback(tmp_path, monkeypatch):
    fake_cgroup = tmp_path / "cgroup"
    fake_cgroup.mkdir()
    (fake_cgroup / "cpu.max").write_text("max", encoding="utf-8")
    (fake_cgroup / "memory.max").write_text("max", encoding="utf-8")
    (fake_cgroup / "io.max").write_text("", encoding="utf-8")

    def fake_cpu_percent(interval=0.1):
        return 95.0

    class FakeVM:
        percent = 95.0

    monkeypatch.setattr(psutil, "cpu_percent", fake_cpu_percent)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: FakeVM())
    monkeypatch.setattr(psutil, "swap_memory", lambda: FakeVM())

    scheduler = ResourceScheduler(policy=ResourcePolicy(cpu_threshold=0.5, memory_threshold=0.5, wasmem_threshold=0.5), cgroup_base_path=str(fake_cgroup))

    decision = scheduler.schedule_yield()
    assert decision["throttle"] is True
    assert decision["cgroup_path"] == str(fake_cgroup)
    assert (fake_cgroup / "cpu.max").read_text(encoding="utf-8") == "10000 100000"
    assert (fake_cgroup / "memory.max").read_text(encoding="utf-8") == "512M"


def test_scheduler_metrics_p95_history(tmp_path, monkeypatch):
    def fake_cpu_percent(interval=0.1):
        return 10.0

    class FakeVM:
        percent = 10.0

    monkeypatch.setattr(psutil, "cpu_percent", fake_cpu_percent)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: FakeVM())
    monkeypatch.setattr(psutil, "swap_memory", lambda: FakeVM())

    scheduler = ResourceScheduler(policy=ResourcePolicy(cpu_threshold=0.5, memory_threshold=0.5, wasmem_threshold=0.5))

    for _ in range(20):
        scheduler.schedule_yield()

    metrics = scheduler.get_metrics()
    assert metrics["decision_count"] == 20
    assert "latency_ms_p95" in metrics
    assert metrics["latency_ms_p95"] >= 0
