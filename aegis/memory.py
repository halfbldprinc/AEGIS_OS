import json
import re
import sqlite3
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None


@dataclass
class ConversationTurn:
    turn_id: str
    session_id: str
    user_input: str
    plan_result: Dict[str, Any]
    plan_status: str
    user_satisfaction: int | None
    created_at: float


@dataclass
class MemoryEntry:
    id: str
    text: str
    metadata: Dict[str, Any]
    created_at: float
    embedding: List[float]


class EmbeddingModel:
    def __init__(self):
        self.lock = threading.RLock()
        self._impl = None
        self._mode = None
        if SentenceTransformer is not None:
            try:
                self._impl = SentenceTransformer("all-MiniLM-L6-v2")
                self._mode = "transformer"
            except Exception:
                self._impl = None
                self._mode = None

        if self._impl is None:
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer

                self._impl = TfidfVectorizer(stop_words="english")
                self._mode = "tfidf"
            except Exception:
                self._impl = None
                self._mode = None

        if self._impl is None:
            self._mode = "bow"

    def encode(self, texts: List[str]) -> List[List[float]]:
        with self.lock:
            if self._mode == "transformer":
                return self._impl.encode(texts, show_progress_bar=False, convert_to_numpy=True).tolist()

            if self._mode == "tfidf":
                vectors = self._impl.fit_transform(texts)
                return [vec.toarray()[0].tolist() for vec in vectors]

            # BOW fallback
            return [self._count_vector(t) for t in texts]

    def _count_vector(self, text: str) -> List[float]:
        tokens = self._tokenize(text)
        c = Counter(tokens)
        # Sorted term vector, deterministic from base vocabulary
        terms = sorted(c.keys())
        return [float(c[t]) for t in terms]

    def _tokenize(self, text: str) -> List[str]:
        return [t for t in re.findall(r"\\w+", text.lower()) if len(t) > 1]


class MemoryStore:
    def __init__(self, db_path: str = "~/.aegis/memory.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedding_model = EmbeddingModel()
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    metadata TEXT,
                    created_at REAL NOT NULL,
                    embedding TEXT NOT NULL
                )
                """
            )

    def upsert(self, text: str, metadata: Optional[Dict[str, Any]] = None, entry_id: Optional[str] = None) -> MemoryEntry:
        if metadata is None:
            metadata = {}

        if entry_id is None:
            entry_id = str(uuid.uuid4())

        created_at = time.time()
        embedding = self.embedding_model.encode([text])[0]

        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO memory (id, text, metadata, created_at, embedding) VALUES (?, ?, ?, ?, ?)",
                (entry_id, text, json.dumps(metadata), created_at, json.dumps(embedding)),
            )

        return MemoryEntry(id=entry_id, text=text, metadata=metadata, created_at=created_at, embedding=embedding)

    def delete(self, entry_id: str) -> bool:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM memory WHERE id = ?", (entry_id,))
            return cursor.rowcount > 0

    def get(self, entry_id: str) -> Optional[MemoryEntry]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT id, text, metadata, created_at, embedding FROM memory WHERE id = ?", (entry_id,)).fetchone()
            if row is None:
                return None
            return MemoryEntry(
                id=row[0],
                text=row[1],
                metadata=json.loads(row[2]) if row[2] else {},
                created_at=row[3],
                embedding=json.loads(row[4]),
            )

    def list(self, limit: int = 100) -> List[MemoryEntry]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT id, text, metadata, created_at, embedding FROM memory ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [
                MemoryEntry(
                    id=row[0],
                    text=row[1],
                    metadata=json.loads(row[2]) if row[2] else {},
                    created_at=row[3],
                    embedding=json.loads(row[4]),
                )
                for row in rows
            ]

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_emb = self.embedding_model.encode([query])[0]
        query_terms = self._tokenize(query)

        candidates = self.list(limit=1000)
        scores = []

        for entry in candidates:
            if not entry.embedding:
                continue
            # Embedding backends can produce vectors with mismatched dimensions
            # across independently encoded texts. Blend cosine with lexical overlap
            # so search remains functional and deterministic.
            cosine_score = self._cosine_similarity(query_emb, entry.embedding)
            lexical_score = self._lexical_overlap_score(query_terms, self._tokenize(entry.text))
            score = max(cosine_score, lexical_score)
            scores.append((score, entry))

        scores.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, entry in scores[:top_k]:
            results.append(
                {
                    "id": entry.id,
                    "text": entry.text,
                    "metadata": entry.metadata,
                    "created_at": datetime.fromtimestamp(entry.created_at).isoformat(),
                    "score": score,
                }
            )

        return results

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return [t for t in re.findall(r"\w+", text.lower()) if len(t) > 1]

    @staticmethod
    def _lexical_overlap_score(query_terms: List[str], text_terms: List[str]) -> float:
        if not query_terms or not text_terms:
            return 0.0
        q = set(query_terms)
        t = set(text_terms)
        if not q:
            return 0.0
        return len(q.intersection(t)) / float(len(q))

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        if len(a) != len(b):
            # when vectors not same length, fallback to 0.0
            return 0.0

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
