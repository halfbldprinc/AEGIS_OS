import smtplib
from email.message import EmailMessage
from typing import Any, Dict, List

from ..result import SkillResult
from ..skill import Skill


class EmailSkill(Skill):
    name = "email"
    tier = 2

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action == "draft":
            return self.draft(params)
        if action == "send":
            return self.send(params)
        return SkillResult.fail(f"Unsupported action: {action}")

    def get_permissions(self) -> List[str]:
        return ["email_send"]

    def draft(self, params: Dict[str, Any]) -> SkillResult:
        try:
            msg = self._build_message(params)
            return SkillResult.ok({"draft": msg.as_string()})
        except ValueError as exc:
            return SkillResult.fail(str(exc))

    def send(self, params: Dict[str, Any]) -> SkillResult:
        approved = bool(params.get("approved", False))
        if not approved:
            return SkillResult.fail("Send requires explicit approval")

        host = params.get("smtp_host")
        port = int(params.get("smtp_port", 587))
        username = params.get("smtp_username")
        password = params.get("smtp_password")
        use_tls = bool(params.get("smtp_tls", True))

        if not host:
            return SkillResult.fail("'smtp_host' parameter is required")

        try:
            msg = self._build_message(params)
        except ValueError as exc:
            return SkillResult.fail(str(exc))

        try:
            if use_tls:
                with smtplib.SMTP(host, port, timeout=20) as smtp:
                    smtp.starttls()
                    if username:
                        smtp.login(username, password or "")
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=20) as smtp:
                    if username:
                        smtp.login(username, password or "")
                    smtp.send_message(msg)
        except Exception as exc:
            return SkillResult.fail(f"SMTP send failed: {exc}")

        return SkillResult.ok({"sent": True, "to": msg["To"], "subject": msg["Subject"]})

    def _build_message(self, params: Dict[str, Any]) -> EmailMessage:
        sender = params.get("from")
        to_addr = params.get("to")
        subject = params.get("subject")
        body = params.get("body")

        if not sender:
            raise ValueError("'from' parameter is required")
        if not to_addr:
            raise ValueError("'to' parameter is required")
        if not subject:
            raise ValueError("'subject' parameter is required")
        if body is None:
            raise ValueError("'body' parameter is required")

        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(str(body))
        return msg
