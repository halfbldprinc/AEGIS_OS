from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .llm.runtime import LLMRuntime, LLMUnavailableError
from .memory import MemoryStore

if TYPE_CHECKING:
    from .ai_diagnostics import AIExecutionDiagnostics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalChunk:
    id: str
    text: str
    score: float
    scope: str


class AIExecutionEngine:
    """Runtime-backed inference pipeline with retrieval-augmented context."""

    def __init__(
        self,
        llm_runtime: LLMRuntime,
        memory_store: MemoryStore,
        diagnostics: Optional[AIExecutionDiagnostics] = None,
    ):
        self.llm_runtime = llm_runtime
        self.memory_store = memory_store
        self.diagnostics = diagnostics

    def retrieve_context(self, query: str, top_k: int = 5, scope: Optional[str] = None) -> List[RetrievalChunk]:
        rows = self.memory_store.search(query, top_k=top_k, scope=scope)
        chunks: List[RetrievalChunk] = []
        for row in rows:
            chunks.append(
                RetrievalChunk(
                    id=str(row.get("id", "")),
                    text=str(row.get("text", "")),
                    score=float(row.get("score", 0.0)),
                    scope=str(row.get("scope", "long_term")),
                )
            )
        return chunks

    @staticmethod
    def _context_to_system_prompt(context: List[RetrievalChunk]) -> str:
        if not context:
            return "No retrieval context available."

        lines = ["Retrieved memory context (most relevant first):"]
        for idx, chunk in enumerate(context, start=1):
            lines.append(f"{idx}. [{chunk.scope}] score={chunk.score:.4f} id={chunk.id}")
            lines.append(f"   {chunk.text}")
        return "\n".join(lines)

    def execute(
        self,
        query: str,
        top_k: int = 5,
        scope: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> Dict[str, Any]:
        # Retrieve with timing
        retrieval_start = time.time()
        context = self.retrieve_context(query, top_k=top_k, scope=scope)
        retrieval_time_ms = (time.time() - retrieval_start) * 1000

        # Record retrieval metrics
        if self.diagnostics:
            relevance_scores = [chunk.score for chunk in context]
            self.diagnostics.record_retrieval(
                query=query,
                retrieved_count=len(context),
                top_k_requested=top_k,
                relevance_scores=relevance_scores,
                latency_ms=retrieval_time_ms,
            )

        system_prompt = self._context_to_system_prompt(context)

        messages: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are AegisOS local AI execution engine. Use the provided retrieval context when relevant, "
                    "and answer concisely with grounded facts."
                ),
            },
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        # Generate with timing
        generation_start = time.time()
        output = self.llm_runtime.generate(messages, temperature=temperature, max_tokens=max_tokens)
        generation_time_ms = (time.time() - generation_start) * 1000

        # Record generation metrics
        if self.diagnostics:
            prompt_tokens = len(messages[0]["content"]) // 4 + len(messages[1]["content"]) // 4 + len(messages[2]["content"]) // 4
            completion_tokens = len(output) // 4
            self.diagnostics.record_generation(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                completion_latency_ms=generation_time_ms,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        return {
            "query": query,
            "response": output,
            "retrieval": [chunk.__dict__ for chunk in context],
            "retrieval_count": len(context),
            "retrieval_latency_ms": retrieval_time_ms,
            "generation_latency_ms": generation_time_ms,
            "runtime_profile": self.llm_runtime.runtime_profile() if hasattr(self.llm_runtime, "runtime_profile") else None,
        }

    def health(self) -> Dict[str, Any]:
        return {
            "runtime_available": self.llm_runtime.health(),
            "runtime_profile": self.llm_runtime.runtime_profile() if hasattr(self.llm_runtime, "runtime_profile") else None,
        }
