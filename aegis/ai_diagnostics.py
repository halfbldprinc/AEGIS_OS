"""Diagnostics and observability for AI execution pipeline (retrieval + generation)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict
from typing import Any, Deque, Dict, List, Optional
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class RetrievalMetric:
    query: str
    query_len: int
    retrieved_count: int
    top_k_requested: int
    avg_relevance_score: float
    max_relevance_score: float
    min_relevance_score: float
    coverage_ratio: float  # retrieved_count / top_k_requested
    latency_ms: float
    timestamp: float


@dataclass
class GenerationMetric:
    prompt_tokens: int
    completion_tokens: int
    completion_latency_ms: float
    temperature: float
    max_tokens: int
    actual_tokens: int
    timestamp: float


class AIExecutionDiagnostics:
    """Track and aggregate AI execution pipeline quality metrics."""

    def __init__(self, max_samples: int = 1000):
        self.max_samples = max_samples
        self.retrieval_history: Deque[RetrievalMetric] = deque(maxlen=max_samples)
        self.generation_history: Deque[GenerationMetric] = deque(maxlen=max_samples)

    def record_retrieval(
        self,
        query: str,
        retrieved_count: int,
        top_k_requested: int,
        relevance_scores: List[float],
        latency_ms: float,
    ) -> None:
        """Record a retrieval operation."""
        scores = [float(s) for s in relevance_scores] if relevance_scores else []
        avg_score = sum(scores) / len(scores) if scores else 0.0
        max_score = max(scores) if scores else 0.0
        min_score = min(scores) if scores else 0.0
        coverage = retrieved_count / max(1, top_k_requested)

        metric = RetrievalMetric(
            query=query,
            query_len=len(query),
            retrieved_count=retrieved_count,
            top_k_requested=top_k_requested,
            avg_relevance_score=avg_score,
            max_relevance_score=max_score,
            min_relevance_score=min_score,
            coverage_ratio=coverage,
            latency_ms=latency_ms,
            timestamp=time.time(),
        )
        self.retrieval_history.append(metric)
        logger.debug("Retrieval metric recorded: %s results, avg_score=%.3f, latency=%.1fms", 
                     retrieved_count, avg_score, latency_ms)

    def record_generation(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        completion_latency_ms: float,
        temperature: float,
        max_tokens: int,
    ) -> None:
        """Record a generation operation."""
        metric = GenerationMetric(
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            completion_latency_ms=float(completion_latency_ms),
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            actual_tokens=int(completion_tokens),
            timestamp=time.time(),
        )
        self.generation_history.append(metric)
        logger.debug("Generation metric: %d prompt + %d completion tokens, %.1fms", 
                     prompt_tokens, completion_tokens, completion_latency_ms)

    def get_retrieval_summary(self) -> Dict[str, Any]:
        """Summarize retrieval metrics."""
        if not self.retrieval_history:
            return {
                "sample_count": 0,
                "avg_coverage_ratio": 0.0,
                "avg_relevance_score": 0.0,
                "latency_ms_p50": 0.0,
                "latency_ms_p95": 0.0,
            }

        records = list(self.retrieval_history)
        latencies = sorted([m.latency_ms for m in records])
        relevance_scores = [m.avg_relevance_score for m in records]
        coverage = [m.coverage_ratio for m in records]

        p50_idx = int(len(latencies) * 0.50)
        p95_idx = int(len(latencies) * 0.95) if len(latencies) > 1 else 0

        return {
            "sample_count": len(records),
            "avg_coverage_ratio": sum(coverage) / len(coverage) if coverage else 0.0,
            "avg_relevance_score": sum(relevance_scores) / len(relevance_scores) if relevance_scores else 0.0,
            "latency_ms_p50": latencies[p50_idx] if latencies else 0.0,
            "latency_ms_p95": latencies[p95_idx] if latencies else 0.0,
            "recent_queries": [m.query[:64] for m in records[-5:]]  # Last 5
        }

    def get_generation_summary(self) -> Dict[str, Any]:
        """Summarize generation metrics."""
        if not self.generation_history:
            return {
                "sample_count": 0,
                "avg_prompt_tokens": 0,
                "avg_completion_tokens": 0,
                "latency_ms_p50": 0.0,
                "latency_ms_p95": 0.0,
                "avg_temperature": 0.0,
            }

        records = list(self.generation_history)
        latencies = sorted([m.completion_latency_ms for m in records])
        prompt_tokens = [m.prompt_tokens for m in records]
        completion_tokens = [m.completion_tokens for m in records]
        temperatures = [m.temperature for m in records]

        p50_idx = int(len(latencies) * 0.50)
        p95_idx = int(len(latencies) * 0.95) if len(latencies) > 1 else 0

        return {
            "sample_count": len(records),
            "avg_prompt_tokens": sum(prompt_tokens) / len(prompt_tokens) if prompt_tokens else 0,
            "avg_completion_tokens": sum(completion_tokens) / len(completion_tokens) if completion_tokens else 0,
            "latency_ms_p50": latencies[p50_idx] if latencies else 0.0,
            "latency_ms_p95": latencies[p95_idx] if latencies else 0.0,
            "avg_temperature": sum(temperatures) / len(temperatures) if temperatures else 0.0,
        }

    def get_diagnostics(self) -> Dict[str, Any]:
        """Get full diagnostics snapshot."""
        return {
            "retrieval": self.get_retrieval_summary(),
            "generation": self.get_generation_summary(),
            "total_cycles": len(self.retrieval_history) + len(self.generation_history),
        }
