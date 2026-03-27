from aegis.evolution import EvolutionManager
import json
import math


def test_evolution_proposal_lifecycle():
    manager = EvolutionManager()
    proposal = manager.create_proposal("p1", metrics={"delta_perplexity": 0.05})

    assert proposal.proposal_id == "p1"
    assert not proposal.approved
    assert not proposal.applied

    manager.approve_proposal("p1")
    assert manager.list_proposals()[0].approved

    manager.apply_proposal("p1")
    assert manager.list_proposals()[0].applied


def test_evolution_proposal_requires_approval_before_apply():
    manager = EvolutionManager()
    manager.create_proposal("p2", metrics={"delta_perplexity": 0.03})

    try:
        manager.apply_proposal("p2")
        assert False, "Expected ValueError for unapproved proposal"
    except ValueError:
        assert True


def test_evolution_proposal_delta_gate_and_snapshot():
    manager = EvolutionManager()
    manager.create_proposal("p3", metrics={"delta_perplexity": 0.10})
    manager.approve_proposal("p3")

    proposal = manager.apply_proposal("p3")
    assert proposal.applied
    assert len(manager.adapter_snapshots) == 1

    previous_snapshot = manager.adapter_snapshots[0]
    assert previous_snapshot["proposal_id"] == "p3"


def test_evolution_proposal_delta_exceeds_threshold():
    manager = EvolutionManager()
    manager.create_proposal("p4", metrics={"delta_perplexity": 0.22})
    manager.approve_proposal("p4")

    try:
        manager.apply_proposal("p4")
        assert False, "Expected ValueError for delta over threshold"
    except ValueError as exc:
        assert "exceeds safety threshold" in str(exc)


def test_evolution_execute_requires_audit_signoff():
    manager = EvolutionManager()
    manager.create_proposal("p5", metrics={"delta_perplexity": 0.05}, canary_percentage=50.0, audit_signoff_required=True)
    manager.approve_proposal("p5")

    try:
        manager.execute_proposal("p5", canary_percentage=50.0, audit_signoff=False)
        assert False, "Expected ValueError for missing audit signoff"
    except ValueError as exc:
        assert "requires audit signoff" in str(exc)

    proposal = manager.execute_proposal("p5", canary_percentage=50.0, audit_signoff=True)
    assert proposal.applied


def test_evolution_execute_canary_mode():
    manager = EvolutionManager()
    manager.create_proposal("p6", metrics={"delta_perplexity": 0.05}, canary_percentage=20.0)
    manager.approve_proposal("p6")

    proposal = manager.execute_proposal("p6", canary_percentage=20.0, audit_signoff=True)
    assert proposal.applied
    assert proposal.canary_percentage == 20.0


def test_evolution_proposal_not_reapplied():
    manager = EvolutionManager()
    manager.create_proposal("p7", metrics={"delta_perplexity": 0.05}, canary_percentage=100.0)
    manager.approve_proposal("p7")
    manager.execute_proposal("p7", canary_percentage=100.0, audit_signoff=True)

    try:
        manager.apply_proposal("p7")
        assert False, "Expected ValueError for reapply"
    except ValueError as exc:
        assert "already been applied" in str(exc)


def test_evolution_snapshot_retention_limit():
    manager = EvolutionManager()

    for i in range(6):
        pid = f"p{i}"
        manager.create_proposal(pid, metrics={"delta_perplexity": 0.01})
        manager.approve_proposal(pid)
        manager.apply_proposal(pid)

    assert len(manager.adapter_snapshots) == manager.MAX_SNAPSHOTS
    assert manager.adapter_snapshots[0]["proposal_id"] == "p2"


def test_evolution_benchmark_smoke_gate_pass(tmp_path):
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(json.dumps({"samples": [{"expected_pass": True}, {"expected_pass": True}]}), encoding="utf-8")

    manager = EvolutionManager()
    manager.create_proposal(
        "p-bench-pass",
        metrics={
            "delta_perplexity": 0.05,
            "benchmark_path": str(benchmark),
            "model_name": "local-candidate",
            "min_eval_score": 0.5,
        },
    )
    manager.approve_proposal("p-bench-pass")
    proposal = manager.apply_proposal("p-bench-pass")

    assert proposal.applied is True


def test_evolution_benchmark_smoke_gate_fail(tmp_path):
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(json.dumps({"samples": [{"expected_pass": False}, {"expected_pass": False}]}), encoding="utf-8")

    manager = EvolutionManager()
    manager.create_proposal(
        "p-bench-fail",
        metrics={
            "delta_perplexity": 0.05,
            "benchmark_path": str(benchmark),
            "model_name": "local-candidate",
            "min_eval_score": 0.8,
        },
    )
    manager.approve_proposal("p-bench-fail")

    try:
        manager.apply_proposal("p-bench-fail")
        assert False, "Expected RuntimeError for failed smoke evaluation"
    except RuntimeError as exc:
        assert "Smoke tests failed" in str(exc)


def test_evolution_rejects_non_finite_delta_perplexity():
    manager = EvolutionManager()
    manager.create_proposal("p-nan", metrics={"delta_perplexity": math.inf})
    manager.approve_proposal("p-nan")

    try:
        manager.apply_proposal("p-nan")
        assert False, "Expected ValueError for non-finite delta"
    except ValueError as exc:
        assert "finite" in str(exc)
