"""Deterministic fallback planner rules used when LLM planning fails."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from ..orchestrator.core import Plan


@dataclass
class RuleFallbackPlanner:
    """Rule-based fallback planner for common skill-routing intents."""

    def build_plan(self, user_input: str, available_skills: set[str]) -> Optional[Plan]:
        text = (user_input or "").strip()
        lower = text.lower()
        if not text:
            return None

        plan = Plan()

        if "web_search" in available_skills:
            query = self.extract_search_query(text)
            if query:
                plan.add_step(skill_name="web_search", action="search", params={"query": query, "limit": 5})
                return plan

        maybe_url = self.extract_url(text)
        if maybe_url and "browser" in available_skills:
            if lower.startswith("open ") or " open " in f" {lower} ":
                plan.add_step(skill_name="browser", action="open_url", params={"url": maybe_url})
                return plan
            if any(token in lower for token in ("summarize", "read", "fetch", "extract text")):
                plan.add_step(skill_name="browser", action="fetch_text", params={"url": maybe_url, "max_chars": 4000})
                return plan
            if "extract links" in lower or "list links" in lower:
                plan.add_step(skill_name="browser", action="extract_links", params={"url": maybe_url, "limit": 20})
                return plan

        if "reminder" in available_skills:
            parsed = self.parse_reminder(lower)
            if parsed is not None:
                action, params = parsed
                plan.add_step(skill_name="reminder", action=action, params=params)
                return plan

        if "package_manager" in available_skills:
            parsed = self.parse_package_action(lower)
            if parsed is not None:
                action, params = parsed
                plan.add_step(skill_name="package_manager", action=action, params=params)
                return plan

        if "calendar" in available_skills:
            parsed = self.parse_calendar(lower)
            if parsed is not None:
                action, params = parsed
                plan.add_step(skill_name="calendar", action=action, params=params)
                return plan

        if "email" in available_skills:
            parsed = self.parse_email(text)
            if parsed is not None:
                action, params = parsed
                plan.add_step(skill_name="email", action=action, params=params)
                return plan

        if "echo" in available_skills:
            plan.add_step(skill_name="echo", action="echo", params={"message": text})
            return plan

        return None

    @staticmethod
    def extract_search_query(text: str) -> Optional[str]:
        lower = text.lower().strip()
        patterns = [
            r"^search web for\s+(.+)$",
            r"^search for\s+(.+)$",
            r"^look up\s+(.+)$",
            r"^find info on\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, lower)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def extract_url(text: str) -> Optional[str]:
        match = re.search(r"https?://\S+", text)
        if not match:
            return None

        candidate = match.group(0).rstrip(".,)")
        parsed = urlparse(candidate)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return candidate
        return None

    @staticmethod
    def parse_reminder(lower: str) -> Optional[tuple[str, Dict[str, Any]]]:
        if lower in ("list reminders", "show reminders"):
            return "list", {}

        due_match = re.match(r"^remind me to\s+(.+?)\s+in\s+(\d+)\s+(minute|minutes|hour|hours|day|days)$", lower)
        if due_match:
            title = due_match.group(1).strip()
            amount = int(due_match.group(2))
            unit = due_match.group(3)
            factor = 60
            if unit.startswith("hour"):
                factor = 3600
            elif unit.startswith("day"):
                factor = 86400
            due_at = time.time() + (amount * factor)
            return "add", {"title": title, "due_at": due_at}

        return None

    @staticmethod
    def parse_calendar(lower: str) -> Optional[tuple[str, Dict[str, Any]]]:
        if lower in ("list calendar events", "show calendar", "what's on my calendar", "whats on my calendar"):
            return "list_events", {}

        match = re.match(r"^schedule\s+(.+?)\s+in\s+(\d+)\s+minutes\s+for\s+(\d+)\s+minutes$", lower)
        if match:
            title = match.group(1).strip()
            starts_in_min = int(match.group(2))
            duration_min = int(match.group(3))
            start_at = time.time() + starts_in_min * 60
            end_at = start_at + duration_min * 60
            return "add_event", {"title": title, "start_at": start_at, "end_at": end_at}

        return None

    @staticmethod
    def parse_email(text: str) -> Optional[tuple[str, Dict[str, Any]]]:
        lower = text.lower()
        draft_match = re.match(
            r"^draft email to\s+([^\s]+)\s+subject\s+(.+?)\s+body\s+(.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if draft_match:
            to_addr = draft_match.group(1).strip()
            subject = draft_match.group(2).strip()
            body = draft_match.group(3).strip()
            return "draft", {
                "from": "local@aegis",
                "to": to_addr,
                "subject": subject,
                "body": body,
            }

        if lower in ("list drafts", "show drafts"):
            return None

        return None

    @staticmethod
    def parse_package_action(lower: str) -> Optional[tuple[str, Dict[str, Any]]]:
        install_match = re.match(r"^(install|add)\s+([a-z0-9][a-z0-9+._-]{0,63})$", lower)
        if install_match:
            return "install", {"package": install_match.group(2), "confirmed": False}

        remove_match = re.match(r"^(remove|uninstall)\s+([a-z0-9][a-z0-9+._-]{0,63})$", lower)
        if remove_match:
            return "remove", {"package": remove_match.group(2), "confirmed": False}

        search_match = re.match(r"^(search package|find package)\s+([a-z0-9][a-z0-9+._-]{0,63})$", lower)
        if search_match:
            return "search", {"package": search_match.group(2), "limit": 10}

        if lower in ("list installed packages", "show installed packages"):
            return "list_installed", {"limit": 100}

        return None
