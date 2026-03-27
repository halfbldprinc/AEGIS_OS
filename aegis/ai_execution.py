from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .llm.runtime import LLMRuntime, LLMUnavailableError
from .memory import MemoryStore


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
    ):
        self.llm_runtime = llm_runtime
        self.memory_store = memory_store

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
        context = self.retrieve_context(query, top_k=top_k, scope=scope)
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

        output = self.llm_runtime.generate(messages, temperature=temperature, max_tokens=max_tokens)
        return {
            "query": query,
            "response": output,
            "retrieval": [chunk.__dict__ for chunk in context],
            "retrieval_count": len(context),
            "runtime_profile": self.llm_runtime.runtime_profile() if hasattr(self.llm_runtime, "runtime_profile") else None,
        }

    def health(self) -> Dict[str, Any]:
        return {
            "runtime_available": self.llm_runtime.health(),
            "runtime_profile": self.llm_runtime.runtime_profile() if hasattr(self.llm_runtime, "runtime_profile") else None,
        }
