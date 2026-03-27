"""Tests for AI execution diagnostics."""

import pytest
from aegis.ai_diagnostics import AIExecutionDiagnostics, RetrievalMetric, GenerationMetric


def test_retrieval_metric_recording():
    diag = AIExecutionDiagnostics()
    diag.record_retrieval(
        query="how does aegisos work?",
        retrieved_count=3,
        top_k_requested=5,
        relevance_scores=[0.95, 0.87, 0.72],
        latency_ms=12.5,
    )

    assert len(diag.retrieval_history) == 1
    summary = diag.get_retrieval_summary()
    assert summary["sample_count"] == 1
    assert summary["avg_relevance_score"] == 0.95 * (1/3) + 0.87 * (1/3) + 0.72 * (1/3)
    # 3 retrieved / 5 requested = 0.6 coverage
    assert summary["avg_coverage_ratio"] == pytest.approx(0.6, abs=0.01)
    assert summary["latency_ms_p50"] == 12.5


def test_generation_metric_recording():
    diag = AIExecutionDiagnostics()
    diag.record_generation(
        prompt_tokens=100,
        completion_tokens=50,
        completion_latency_ms=234.5,
        temperature=0.7,
        max_tokens=512,
    )

    assert len(diag.generation_history) == 1
    summary = diag.get_generation_summary()
    assert summary["sample_count"] == 1
    assert summary["avg_prompt_tokens"] == 100
    assert summary["avg_completion_tokens"] == 50
    assert summary["latency_ms_p50"] == 234.5
    assert summary["avg_temperature"] == 0.7


def test_percentile_calculations():
    diag = AIExecutionDiagnostics()
    for i in range(100):
        diag.record_retrieval(
            query=f"query_{i}",
            retrieved_count=i % 5 + 1,
            top_k_requested=5,
            relevance_scores=[0.5 + (i / 200)],
            latency_ms=10.0 + i,
        )

    summary = diag.get_retrieval_summary()
    assert summary["sample_count"] == 100
    # p50 should be around 59.5, p95 around 104.5
    assert 50 < summary["latency_ms_p50"] < 70
    assert 100 < summary["latency_ms_p95"] < 110


def test_empty_diagnostics():
    diag = AIExecutionDiagnostics()
    assert len(diag.retrieval_history) == 0
    assert len(diag.generation_history) == 0

    summary = diag.get_diagnostics()
    assert summary["retrieval"]["sample_count"] == 0
    assert summary["generation"]["sample_count"] == 0
    assert summary["total_cycles"] == 0


def test_max_samples_buffer():
    diag = AIExecutionDiagnostics(max_samples=50)
    for i in range(100):
        diag.record_retrieval(
            query=f"q{i}",
            retrieved_count=2,
            top_k_requested=5,
            relevance_scores=[0.8],
            latency_ms=10.0,
        )

    assert len(diag.retrieval_history) == 50
