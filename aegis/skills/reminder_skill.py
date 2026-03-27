import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from ..result import SkillResult
from ..skill import Skill


class ReminderSkill(Skill):
    name = "reminder"
    tier = 2

    def __init__(self, db_path: str = "~/.aegis/reminders.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    due_at REAL NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                )
                """
            )

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action == "add":
            return self.add(params.get("title"), params.get("due_at"))
        if action == "list":
            return self.list_items(bool(params.get("include_completed", False)))
        if action == "complete":
            return self.complete(params.get("id"))
        if action == "delete":
            return self.delete(params.get("id"))
        if action == "due":
            return self.due()
        return SkillResult.fail(f"Unsupported action: {action}")

    def get_permissions(self) -> List[str]:
        return ["reminders"]

    def add(self, title: str | None, due_at: Any) -> SkillResult:
        if not title:
            return SkillResult.fail("'title' parameter is required")
        if due_at is None:
            return SkillResult.fail("'due_at' parameter is required")

        try:
            due_ts = float(due_at)
        except (TypeError, ValueError):
            return SkillResult.fail("'due_at' must be a unix timestamp")

        rid = str(uuid.uuid4())
        created_at = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO reminders (id, title, due_at, completed, created_at) VALUES (?, ?, ?, 0, ?)",
                (rid, title, due_ts, created_at),
            )
        return SkillResult.ok({"id": rid, "title": title, "due_at": due_ts})

    def list_items(self, include_completed: bool) -> SkillResult:
        query = "SELECT id, title, due_at, completed, created_at FROM reminders"
        args: tuple = ()
        if not include_completed:
            query += " WHERE completed = 0"
        query += " ORDER BY due_at ASC"

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, args).fetchall()

        reminders = [
            {
                "id": r[0],
                "title": r[1],
                "due_at": r[2],
                "completed": bool(r[3]),
                "created_at": r[4],
            }
            for r in rows
        ]
        return SkillResult.ok({"reminders": reminders})

    def complete(self, reminder_id: str | None) -> SkillResult:
        if not reminder_id:
            return SkillResult.fail("'id' parameter is required")
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (reminder_id,))
            if cur.rowcount == 0:
                return SkillResult.fail("Reminder not found")
        return SkillResult.ok({"id": reminder_id, "completed": True})

    def delete(self, reminder_id: str | None) -> SkillResult:
        if not reminder_id:
            return SkillResult.fail("'id' parameter is required")
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            if cur.rowcount == 0:
                return SkillResult.fail("Reminder not found")
        return SkillResult.ok({"id": reminder_id, "deleted": True})

    def due(self) -> SkillResult:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, title, due_at FROM reminders WHERE completed = 0 AND due_at <= ? ORDER BY due_at ASC",
                (now,),
            ).fetchall()
        return SkillResult.ok({"due": [{"id": r[0], "title": r[1], "due_at": r[2]} for r in rows]})
