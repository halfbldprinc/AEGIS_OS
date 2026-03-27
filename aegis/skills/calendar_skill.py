import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from ..result import SkillResult
from ..skill import Skill


class CalendarSkill(Skill):
    name = "calendar"
    tier = 2

    def __init__(self, db_path: str = "~/.aegis/calendar.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    start_at REAL NOT NULL,
                    end_at REAL NOT NULL,
                    notes TEXT,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action == "add_event":
            return self.add_event(params)
        if action == "list_events":
            return self.list_events(params)
        if action == "update_event":
            return self.update_event(params)
        if action == "cancel_event":
            return self.cancel_event(params.get("id"))
        return SkillResult.fail(f"Unsupported action: {action}")

    def get_permissions(self) -> List[str]:
        return ["calendar"]

    def add_event(self, params: Dict[str, Any]) -> SkillResult:
        title = params.get("title")
        start_at = params.get("start_at")
        end_at = params.get("end_at")
        notes = params.get("notes", "")

        if not title:
            return SkillResult.fail("'title' parameter is required")

        try:
            start_ts = float(start_at)
            end_ts = float(end_at)
        except (TypeError, ValueError):
            return SkillResult.fail("'start_at' and 'end_at' must be unix timestamps")

        if end_ts <= start_ts:
            return SkillResult.fail("Event end must be after start")

        eid = str(uuid.uuid4())
        created_at = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO events (id, title, start_at, end_at, notes, status, created_at) VALUES (?, ?, ?, ?, ?, 'active', ?)",
                (eid, title, start_ts, end_ts, notes, created_at),
            )

        return SkillResult.ok({"id": eid, "title": title, "start_at": start_ts, "end_at": end_ts})

    def list_events(self, params: Dict[str, Any]) -> SkillResult:
        start_after = params.get("start_after")
        end_before = params.get("end_before")
        include_cancelled = bool(params.get("include_cancelled", False))

        clauses = []
        vals: List[Any] = []

        if not include_cancelled:
            clauses.append("status = 'active'")
        if start_after is not None:
            clauses.append("start_at >= ?")
            vals.append(float(start_after))
        if end_before is not None:
            clauses.append("end_at <= ?")
            vals.append(float(end_before))

        query = "SELECT id, title, start_at, end_at, notes, status, created_at FROM events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY start_at ASC"

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, tuple(vals)).fetchall()

        events = [
            {
                "id": r[0],
                "title": r[1],
                "start_at": r[2],
                "end_at": r[3],
                "notes": r[4],
                "status": r[5],
                "created_at": r[6],
            }
            for r in rows
        ]
        return SkillResult.ok({"events": events})

    def update_event(self, params: Dict[str, Any]) -> SkillResult:
        event_id = params.get("id")
        if not event_id:
            return SkillResult.fail("'id' parameter is required")

        fields = []
        vals: List[Any] = []

        if "title" in params:
            fields.append("title = ?")
            vals.append(params["title"])
        if "start_at" in params:
            fields.append("start_at = ?")
            vals.append(float(params["start_at"]))
        if "end_at" in params:
            fields.append("end_at = ?")
            vals.append(float(params["end_at"]))
        if "notes" in params:
            fields.append("notes = ?")
            vals.append(params["notes"])

        if not fields:
            return SkillResult.fail("No updatable fields provided")

        vals.append(event_id)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(f"UPDATE events SET {', '.join(fields)} WHERE id = ?", tuple(vals))
            if cur.rowcount == 0:
                return SkillResult.fail("Event not found")

        return SkillResult.ok({"id": event_id, "updated": True})

    def cancel_event(self, event_id: str | None) -> SkillResult:
        if not event_id:
            return SkillResult.fail("'id' parameter is required")

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("UPDATE events SET status = 'cancelled' WHERE id = ?", (event_id,))
            if cur.rowcount == 0:
                return SkillResult.fail("Event not found")

        return SkillResult.ok({"id": event_id, "cancelled": True})
