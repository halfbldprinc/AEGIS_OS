import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .audit import AuditLog
from .utils.time import now_utc


class Guardian:
    """Permissions ledger for skills and actions (capability-based security)."""

    DEFAULT_DB = os.getenv("AEGIS_GUARDIAN_DB", "/var/lib/aegis/guardian.db")

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or self.DEFAULT_DB
        self.in_memory: Dict[Tuple[str, str], datetime] = {}
        self._heartbeat = now_utc()
        self.audit = AuditLog()
        self._connect()

    def _connect(self) -> None:
        try:
            os.makedirs(Path(self.db_path).parent, exist_ok=True)
            self.conn = sqlite3.connect(self.db_path, detect_types=0)
            self.conn.row_factory = sqlite3.Row
            self._init_db()
        except (PermissionError, sqlite3.Error):
            self.conn = None

    def _init_db(self) -> None:
        if self.conn is None:
            return
        with closing(self.conn.cursor()) as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS permissions (
                    skill_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    expires_at TIMESTAMP NULL,
                    PRIMARY KEY (skill_name, action)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS roles (
                    role_name TEXT PRIMARY KEY,
                    description TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS role_assignments (
                    role_name TEXT,
                    skill_name TEXT,
                    action TEXT,
                    PRIMARY KEY (role_name, skill_name, action)
                )
                """
            )
            self.conn.commit()

    def _write_permission(self, skill_name: str, action: str, expires_at: Optional[datetime]) -> None:
        if self.conn is None:
            self.in_memory[(skill_name, action)] = expires_at if expires_at else datetime.max
            return
        expires = None
        if expires_at is not None and expires_at != datetime.max.replace(tzinfo=timezone.utc):
            expires = expires_at.isoformat()

        with closing(self.conn.cursor()) as cur:
            cur.execute(
                "INSERT OR REPLACE INTO permissions (skill_name, action, expires_at) VALUES (?, ?, ?)",
                (skill_name, action, expires),
            )
            self.conn.commit()

    def _delete_permission(self, skill_name: str, action: str) -> None:
        if self.conn is None:
            self.in_memory.pop((skill_name, action), None)
            return
        with closing(self.conn.cursor()) as cur:
            cur.execute(
                "DELETE FROM permissions WHERE skill_name = ? AND action = ?", (skill_name, action)
            )
            self.conn.commit()

    def _read_permissions(self) -> List[Tuple[str, str, Optional[datetime]]]:
        if self.conn is None:
            return [(k[0], k[1], v if v != datetime.max else None) for k, v in self.in_memory.items()]

        with closing(self.conn.cursor()) as cur:
            cur.execute("SELECT skill_name, action, expires_at FROM permissions")
            rows = cur.fetchall()

        return [(row["skill_name"], row["action"], row["expires_at"]) for row in rows]

    def grant(self, skill_name: str, action: str, duration_hours: Optional[int] = None) -> None:
        expires_at = None
        if duration_hours is not None:
            expires_at = now_utc() + timedelta(hours=duration_hours)
        self._write_permission(skill_name, action, expires_at)
        self.audit.record("guardian", "grant_permission", {"skill_name": skill_name, "action": action, "expires_at": expires_at.isoformat() if expires_at else None})

    def revoke(self, skill_name: str, action: str) -> None:
        self._delete_permission(skill_name, action)
        self.audit.record("guardian", "revoke_permission", {"skill_name": skill_name, "action": action})

    def list_permissions(self) -> List[Dict[str, Optional[str]]]:
        perms = []
        for skill_name, action, expires_at in self._read_permissions():
            perms.append(
                {
                    "skill_name": skill_name,
                    "action": action,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                }
            )
        return perms

    def create_role(self, role_name: str, description: Optional[str] = None) -> None:
        if self.conn is None:
            return
        with closing(self.conn.cursor()) as cur:
            cur.execute("INSERT OR IGNORE INTO roles (role_name, description) VALUES (?, ?)", (role_name, description or ""))
            self.conn.commit()
        self.audit.record("guardian", "create_role", {"role_name": role_name, "description": description})

    def assign_role(self, role_name: str, skill_name: str, action: str) -> None:
        if self.conn is None:
            return
        self.create_role(role_name)
        with closing(self.conn.cursor()) as cur:
            cur.execute(
                "INSERT OR REPLACE INTO role_assignments (role_name, skill_name, action) VALUES (?, ?, ?)",
                (role_name, skill_name, action),
            )
            self.conn.commit()
        self.audit.record("guardian", "assign_role", {"role_name": role_name, "skill_name": skill_name, "action": action})

    def get_role_permissions(self, role_name: str) -> List[Dict[str, Any]]:
        if self.conn is None:
            return []
        with closing(self.conn.cursor()) as cur:
            cur.execute(
                "SELECT skill_name, action FROM role_assignments WHERE role_name = ?",
                (role_name,),
            )
            rows = cur.fetchall()
        return [{"skill_name": row["skill_name"], "action": row["action"]} for row in rows]

    def _normalize_timestamp(self, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def _check_entry(self, expires_at: Optional[datetime], now: datetime) -> bool:
        if expires_at is None or expires_at == datetime.max.replace(tzinfo=timezone.utc):
            return True

        expires_at = self._normalize_timestamp(expires_at)
        if expires_at is None:
            return True

        return now <= expires_at

    def check(self, skill_name: str, action: str) -> bool:
        now = now_utc()

        candidates = [(skill_name, action), (skill_name, "all"), (skill_name, "none")]

        if self.conn is not None:
            with closing(self.conn.cursor()) as cur:
                for skill_key, action_key in candidates:
                    cur.execute(
                        "SELECT expires_at FROM permissions WHERE skill_name = ? AND action = ?", (skill_key, action_key)
                    )
                    row = cur.fetchone()
                    if row is None:
                        continue
                    expires_at = self._normalize_timestamp(row["expires_at"])
                    if self._check_entry(expires_at, now):
                        return True
            return False

        for skill_key, action_key in candidates:
            expires_at = self.in_memory.get((skill_key, action_key))
            if expires_at is None:
                continue
            if self._check_entry(expires_at, now):
                return True

        return False

    def cleanup(self) -> None:
        now = now_utc()
        if self.conn is not None:
            with closing(self.conn.cursor()) as cur:
                cur.execute("DELETE FROM permissions WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
                self.conn.commit()
        else:
            for key, expires_at in list(self.in_memory.items()):
                if expires_at is not None and expires_at != datetime.max and now > expires_at:
                    self.in_memory.pop(key, None)
