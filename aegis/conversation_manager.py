"""Conversation history management with multi-turn support and satisfaction tracking."""

import json
import logging
import sqlite3
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConversationTurn:
    turn_id: str
    session_id: str
    user_input: str
    plan_result: Dict[str, Any]
    plan_status: str
    user_satisfaction: int | None
    created_at: float


class ConversationManager:
    """Manages conversation history with multi-turn support and satisfaction tracking."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._closed = False
        self._init_db()

    def _get_connection(self):
        """Get shared database connection."""
        if self._closed:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._closed = False
        return self._conn

    def close(self) -> None:
        with self.lock:
            if self._closed:
                return
            try:
                self._conn.close()
            except sqlite3.Error as exc:
                logger.warning("Error closing conversation DB: %s", exc)
            finally:
                self._closed = True

    def _init_db(self) -> None:
        """Initialize conversation database schema."""
        with self.lock:
            try:
                conn = self._get_connection()
                conn.execute(
                    """\
                    CREATE TABLE IF NOT EXISTS conversation_turns (
                        turn_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        user_input TEXT NOT NULL,
                        plan_result TEXT NOT NULL,
                        plan_status TEXT NOT NULL,
                        user_satisfaction INTEGER,
                        created_at REAL NOT NULL
                    )
                    """
                )
                conn.commit()
            except sqlite3.Error as exc:
                logger.warning("Error initializing conversation DB: %s", exc)

    def record_turn(
        self,
        session_id: str,
        user_input: str,
        plan_result: Dict[str, Any],
        plan_status: str,
    ) -> str:
        """Record a conversation turn and return turn_id."""
        turn_id = str(uuid.uuid4())
        created_at = time.time()

        with self.lock:
            try:
                conn = self._get_connection()
                conn.execute(
                    """\
                    INSERT INTO conversation_turns
                    (turn_id, session_id, user_input, plan_result, plan_status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        turn_id,
                        session_id,
                        user_input,
                        json.dumps(plan_result),
                        plan_status,
                        created_at,
                    ),
                )
                conn.commit()
            except sqlite3.Error as exc:
                logger.warning("Error recording conversation turn: %s", exc)

        return turn_id

    def rate_turn(self, turn_id: str, satisfaction: int) -> bool:
        """Record user satisfaction rating for a conversation turn (1-5 scale)."""
        if not 1 <= satisfaction <= 5:
            return False

        with self.lock:
            try:
                conn = self._get_connection()
                result = conn.execute(
                    "UPDATE conversation_turns SET user_satisfaction = ? WHERE turn_id = ?",
                    (satisfaction, turn_id),
                )
                conn.commit()
                return result.rowcount > 0
            except sqlite3.Error as exc:
                logger.warning("Error rating turn: %s", exc)
                return False

    def get_session_history(self, session_id: str) -> List[ConversationTurn]:
        """Retrieve all turns from a session."""
        with self.lock:
            try:
                conn = self._get_connection()
                rows = conn.execute(
                    """\
                    SELECT turn_id, session_id, user_input, plan_result, plan_status,
                           user_satisfaction, created_at
                    FROM conversation_turns
                    WHERE session_id = ?
                    ORDER BY created_at ASC
                    """,
                    (session_id,),
                ).fetchall()

                turns = []
                for row in rows:
                    turn_id, sid, user_input, plan_result_json, plan_status, satisfaction, created_at = row
                    turns.append(
                        ConversationTurn(
                            turn_id=turn_id,
                            session_id=sid,
                            user_input=user_input,
                            plan_result=self._safe_load_plan_result(plan_result_json),
                            plan_status=plan_status,
                            user_satisfaction=satisfaction,
                            created_at=created_at,
                        )
                    )
                return turns
            except sqlite3.Error as exc:
                logger.warning("Error retrieving session history: %s", exc)
                return []

    def get_satisfaction_stats(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Get satisfaction statistics, optionally filtered by session_id."""
        with self.lock:
            try:
                conn = self._get_connection()
                if session_id:
                    rows = conn.execute(
                        """\
                        SELECT user_satisfaction FROM conversation_turns
                        WHERE session_id = ? AND user_satisfaction IS NOT NULL
                        """,
                        (session_id,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """\
                        SELECT user_satisfaction FROM conversation_turns
                        WHERE user_satisfaction IS NOT NULL
                        """
                    ).fetchall()

                if not rows:
                    return {
                        "total_rated": 0,
                        "average_satisfaction": 0.0,
                        "distribution": {},
                    }

                ratings = [row[0] for row in rows]
                distribution = dict(Counter(ratings))

                return {
                    "total_rated": len(ratings),
                    "average_satisfaction": sum(ratings) / len(ratings),
                    "distribution": distribution,
                }
            except sqlite3.Error as exc:
                logger.warning("Error computing satisfaction stats: %s", exc)
                return {
                    "total_rated": 0,
                    "average_satisfaction": 0.0,
                    "distribution": {},
                }

    def list_sessions(self) -> List[str]:
        with self.lock:
            try:
                conn = self._get_connection()
                rows = conn.execute("SELECT DISTINCT session_id FROM conversation_turns").fetchall()
                return [str(row[0]) for row in rows if row and row[0] is not None]
            except sqlite3.Error as exc:
                logger.warning("Error listing sessions: %s", exc)
                return []

    @staticmethod
    def _safe_load_plan_result(raw: str) -> Dict[str, Any]:
        try:
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, dict) else {"value": loaded}
        except json.JSONDecodeError:
            return {"raw": raw}
