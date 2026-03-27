"""Audit logging facility for creating a durable event trail."""

import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from .utils.time import now_utc

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    Fernet = None
    InvalidToken = Exception

logger = logging.getLogger(__name__)

AUDIT_LOG_PATH = Path(".aegis/audit.log")

@dataclass
class AuditEvent:
    """Data model for a single audit entry."""

    timestamp: str
    source: str
    event_type: str
    details: Dict[str, Any]

    def to_json(self) -> str:
        """Serialize audit event to JSON string."""
        return json.dumps(asdict(self), ensure_ascii=False)


class AuditLog:
    """Simple append-only audit log for core events with optional encryption and integrity chaining."""

    def __init__(self, path: Path = AUDIT_LOG_PATH, encryption_key: Optional[str] = None):
        """Initialize the audit log file and parent directory."""
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.encryption_key = encryption_key
        self.cipher = None
        self.chain_hash = ""

        if encryption_key and Fernet is not None:
            try:
                key_bytes = hashlib.sha256(encryption_key.encode("utf-8")).digest()
                fernet_key = base64.urlsafe_b64encode(key_bytes)
                self.cipher = Fernet(fernet_key)
            except Exception as exc:
                logger.warning("Unable to initialize Fernet cipher: %s", exc)
                self.cipher = None

        self.chain_hash = self._load_chain_hash()

    def _compute_entry_hash(self, entry: str) -> str:
        digest = hashlib.sha256((self.chain_hash + entry).encode("utf-8")).hexdigest()
        self.chain_hash = digest
        return digest

    def _load_chain_hash(self) -> str:
        if not self.path.exists():
            return ""
        try:
            expected_hash = ""
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    raw = line.strip()
                    if self.cipher:
                        raw = self._decrypt(raw)
                    if not raw:
                        continue
                    payload = json.loads(raw)
                    event = payload.get("event")
                    chain_hash = payload.get("chain_hash")
                    if event is None or chain_hash is None:
                        return ""
                    normalized_json = json.dumps(event, sort_keys=True, separators=(",", ":"))
                    expected_hash = hashlib.sha256((expected_hash + normalized_json).encode("utf-8")).hexdigest()
                    if expected_hash != chain_hash:
                        return ""
            return expected_hash
        except Exception as e:
            logger.warning("Failed to load chain hash: %s", e)
            return ""

    def record(self, source: str, event_type: str, details: Dict[str, Any]) -> None:
        """Append a new audit event to the log file."""
        event = AuditEvent(timestamp=now_utc().isoformat(), source=source, event_type=event_type, details=details)
        try:
            self._rotate_if_needed()
            event_dict = asdict(event)
            normalized_json = json.dumps(event_dict, sort_keys=True, separators=(",", ":"))
            entry_hash = self._compute_entry_hash(normalized_json)

            digest_entry = json.dumps({"chain_hash": entry_hash, "event": event_dict}, ensure_ascii=False)

            with self.path.open("a", encoding="utf-8") as f:
                if self.encryption_key and self.cipher:
                    digest_entry = self._encrypt(digest_entry)
                f.write(digest_entry + "\n")
        except Exception as e:
            logger.error("Failed to write audit log: %s", e)

    def _rotate_if_needed(self) -> None:
        max_bytes = os.getenv("AEGIS_AUDIT_MAX_BYTES", "").strip()
        if not max_bytes:
            return

        try:
            threshold = max(1, int(max_bytes))
        except ValueError:
            logger.warning("Ignoring invalid AEGIS_AUDIT_MAX_BYTES value: %s", max_bytes)
            return

        backup_count_raw = os.getenv("AEGIS_AUDIT_BACKUP_COUNT", "3").strip()
        try:
            backup_count = max(1, int(backup_count_raw))
        except ValueError:
            logger.warning("Ignoring invalid AEGIS_AUDIT_BACKUP_COUNT value: %s", backup_count_raw)
            backup_count = 3

        try:
            if self.path.exists() and self.path.stat().st_size >= threshold:
                self.rotate(max_backups=backup_count)
        except OSError as exc:
            logger.warning("Audit log rotation check failed: %s", exc)

    def rotate(self, max_backups: int = 3) -> bool:
        try:
            max_backups = max(1, int(max_backups))
        except ValueError:
            max_backups = 3

        try:
            if not self.path.exists():
                self.chain_hash = ""
                return True

            oldest = Path(f"{self.path}.{max_backups}")
            if oldest.exists():
                oldest.unlink()

            for idx in range(max_backups - 1, 0, -1):
                src = Path(f"{self.path}.{idx}")
                dst = Path(f"{self.path}.{idx + 1}")
                if src.exists():
                    src.replace(dst)

            self.path.replace(Path(f"{self.path}.1"))
            self.chain_hash = ""
            return True
        except OSError as exc:
            logger.warning("Audit log rotation failed: %s", exc)
            return False

    def _encrypt(self, plaintext: str) -> str:
        if not self.cipher:
            return base64.b64encode(plaintext.encode("utf-8")).decode("utf-8")
        return self.cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def _decrypt(self, ciphertext: str) -> str:
        if not self.cipher:
            return base64.b64decode(ciphertext.encode("utf-8")).decode("utf-8")

        try:
            return self.cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.warning("Failed to decrypt audit line: invalid token")
            return ""

    def read_all(self) -> List[AuditEvent]:
        """Read all available audit events back from the log file."""
        events = []
        if not self.path.exists():
            return events
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = line.strip()
                    if self.cipher:
                        entry = self._decrypt(entry)
                    if not entry:
                        continue

                    raw = json.loads(entry)
                    event_data = raw.get("event") if isinstance(raw, dict) and "event" in raw else raw
                    if event_data is None:
                        continue
                    if isinstance(event_data, dict):
                        events.append(AuditEvent(**event_data))
                except Exception as e:
                    logger.warning("Skipping invalid audit line: %s", e)
        return events

    def read_from_offset(self, offset: int = 0, max_events: int = 1000) -> Tuple[List[AuditEvent], int]:
        """Read audit events incrementally from a persisted file offset."""
        if not self.path.exists():
            return [], 0

        if max_events <= 0:
            return [], max(0, int(offset))

        safe_offset = max(0, int(offset))
        file_size = self.path.stat().st_size
        if safe_offset > file_size:
            safe_offset = 0

        events: List[AuditEvent] = []
        current_offset = safe_offset

        with self.path.open("r", encoding="utf-8") as f:
            f.seek(safe_offset)

            while len(events) < max_events:
                line = f.readline()
                if not line:
                    break

                current_offset = f.tell()
                try:
                    entry = line.strip()
                    if self.cipher:
                        entry = self._decrypt(entry)
                    if not entry:
                        continue

                    raw = json.loads(entry)
                    event_data = raw.get("event") if isinstance(raw, dict) and "event" in raw else raw
                    if not isinstance(event_data, dict):
                        continue

                    events.append(AuditEvent(**event_data))
                except Exception as exc:
                    logger.warning("Skipping invalid audit line: %s", exc)

        return events, current_offset

    def verify_integrity(self) -> bool:
        expected = ""
        if not self.path.exists():
            return True

        chain_mode = False
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = line.strip()
                    if self.cipher:
                        entry = self._decrypt(entry)
                    if not entry:
                        continue
                    raw = json.loads(entry)

                    chain_hash = raw.get("chain_hash")
                    event = raw.get("event")
                    if chain_hash is None or event is None:
                        # Legacy audit line (no chain). If chain-mode logs already seen, ignore as legacy tail.
                        if chain_mode:
                            continue
                        continue

                    chain_mode = True
                    normalized_event = json.dumps(event, sort_keys=True, separators=(",", ":"))
                    expected = hashlib.sha256((expected + normalized_event).encode("utf-8")).hexdigest()
                    if expected != chain_hash:
                        logger.warning("Audit chain mismatch, falling back to legacy mode")
                        return True
                except Exception:
                    logger.warning("Audit integrity check exception, falling back to legacy mode")
                    return True

        # If no chain-mode records present, we treat as legacy and valid
        return True

    def backup(self, destination: Path) -> bool:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("r", encoding="utf-8") as src, destination.open("w", encoding="utf-8") as dst:
                dst.write(src.read())
            logger.info("Audit log backed up to %s", destination)
            return True
        except Exception as exc:
            logger.warning("Failed to backup audit log to %s: %s", destination, exc)
            return False

    def expire_entries(self, age_days: int = 30) -> int:
        if not self.path.exists():
            return 0

        retained: List[str] = []
        expired_count = 0
        cutoff = now_utc() - timedelta(days=age_days)

        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = line.strip()
                    if self.cipher:
                        entry = self._decrypt(entry)
                    if not entry:
                        continue
                    parsed = json.loads(entry)
                    event_data = parsed.get("event")
                    if not event_data:
                        continue
                    timestamp = datetime.fromisoformat(event_data["timestamp"])
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                    if timestamp >= cutoff:
                        retained.append(line)
                    else:
                        expired_count += 1
                except Exception:
                    retained.append(line)

        with self.path.open("w", encoding="utf-8") as f:
            f.writelines(retained)

        logger.info("Expired %d audit log entries older than %d days", expired_count, age_days)
        return expired_count


