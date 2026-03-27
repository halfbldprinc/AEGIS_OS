from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional

from .utils.time import now_utc


@dataclass
class TrustScores:
    confirmed: int = 0
    rejected: int = 0
    errors_last_30d: int = 0
    consecutive_rejections: int = 0
    suspended_until: Optional[datetime] = None
    permanently_locked: bool = False


class TrustLedger:
    """Tracks per-category trust status and unlock logic."""

    UNLOCK_CONFIRMED = 50
    UNLOCK_REJECTION_RATE = 0.05
    UNLOCK_MAX_ERRORS_30D = 5

    TEMP_SUSPENSION_HOURS = 24
    PERMANENT_REJECTION_THRESHOLD = 3

    def __init__(self):
        self.records: Dict[str, TrustScores] = {}

    def get_scores(self, category: str) -> TrustScores:
        return self.records.setdefault(category, TrustScores())

    def record_outcome(self, category: str, confirmed: bool, error: bool = False) -> None:
        score = self.get_scores(category)

        if score.permanently_locked:
            return

        if confirmed:
            score.confirmed += 1
            score.consecutive_rejections = 0
        else:
            score.rejected += 1
            score.consecutive_rejections += 1
            if score.consecutive_rejections >= self.PERMANENT_REJECTION_THRESHOLD:
                score.permanently_locked = True
            else:
                score.suspended_until = now_utc() + timedelta(hours=self.TEMP_SUSPENSION_HOURS)

        if error:
            score.errors_last_30d += 1

    def is_unlocked(self, category: str) -> bool:
        s = self.get_scores(category)

        if s.permanently_locked:
            return False

        if s.suspended_until and now_utc() < s.suspended_until:
            return False

        if s.confirmed < self.UNLOCK_CONFIRMED:
            return False

        if s.rejected / max(s.confirmed, 1) > self.UNLOCK_REJECTION_RATE:
            return False

        if s.errors_last_30d >= self.UNLOCK_MAX_ERRORS_30D:
            return False

        return True

    def check_unlock_criteria(self, category: str) -> bool:
        return self.is_unlocked(category)

    def reset_category(self, category: str) -> None:
        self.records[category] = TrustScores()

    def unlock_category(self, category: str) -> None:
        score = self.get_scores(category)
        score.permanently_locked = False
        score.suspended_until = None
        score.consecutive_rejections = 0

    def export(self) -> Dict[str, TrustScores]:
        return dict(self.records)
