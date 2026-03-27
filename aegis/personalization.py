import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any


@dataclass
class UserPreference:
    key: str
    value: str
    updated_at: float


class PersonalizationStore:
    def __init__(self, db_path: str = "~/.aegis/personalization.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt TEXT NOT NULL,
                    response TEXT NOT NULL,
                    positive INTEGER NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    def set_pref(self, key: str, value: str) -> None:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO preferences (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )

    def get_pref(self, key: str) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None

    def all_prefs(self) -> Dict[str, str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT key, value FROM preferences").fetchall()
        return {k: v for k, v in rows}

    def add_feedback(self, prompt: str, response: str, positive: bool) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO feedback (prompt, response, positive, created_at) VALUES (?, ?, ?, ?)",
                (prompt, response, 1 if positive else 0, time.time()),
            )

    def summarize_feedback(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT positive FROM feedback").fetchall()

        total = len(rows)
        positive_count = sum(1 for r in rows if r[0] == 1)
        rate = positive_count / total if total else 0.0
        return {"total": total, "positive": positive_count, "positive_rate": rate}


class PersonalizationEngine:
    def __init__(self, store: PersonalizationStore | None = None):
        self.store = store or PersonalizationStore()

    def update_from_feedback(self, prompt: str, response: str, positive: bool) -> None:
        self.store.add_feedback(prompt, response, positive)

        summary = self.store.summarize_feedback()
        if summary["positive_rate"] > 0.7:
            self.store.set_pref("assistant_tone", "concise")
        elif summary["positive_rate"] < 0.4:
            self.store.set_pref("assistant_tone", "detailed")

    def inject_system_style(self) -> str:
        prefs = self.store.all_prefs()
        tone = prefs.get("assistant_tone", "balanced")
        verbosity = prefs.get("verbosity", "balanced")
        return f"Use tone={tone}; verbosity={verbosity}."
