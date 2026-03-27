import time

from aegis.skills.reminder_skill import ReminderSkill
from aegis.skills.calendar_skill import CalendarSkill
from aegis.skills.email_skill import EmailSkill


def test_reminder_skill_cycle(tmp_path):
    skill = ReminderSkill(db_path=str(tmp_path / "reminders.db"))
    due = time.time() + 60

    created = skill.execute("add", {"title": "Test reminder", "due_at": due})
    assert created.success
    rid = created.data["id"]

    listed = skill.execute("list", {})
    assert listed.success
    assert any(x["id"] == rid for x in listed.data["reminders"])

    done = skill.execute("complete", {"id": rid})
    assert done.success

    deleted = skill.execute("delete", {"id": rid})
    assert deleted.success


def test_calendar_skill_cycle(tmp_path):
    skill = CalendarSkill(db_path=str(tmp_path / "calendar.db"))
    start = time.time() + 3600
    end = start + 1800

    created = skill.execute("add_event", {"title": "Meeting", "start_at": start, "end_at": end, "notes": "Sync"})
    assert created.success
    eid = created.data["id"]

    listed = skill.execute("list_events", {})
    assert listed.success
    assert any(e["id"] == eid for e in listed.data["events"])

    updated = skill.execute("update_event", {"id": eid, "notes": "Updated"})
    assert updated.success

    cancelled = skill.execute("cancel_event", {"id": eid})
    assert cancelled.success


def test_email_skill_draft_and_approval_gate():
    skill = EmailSkill()

    draft = skill.execute(
        "draft",
        {"from": "a@example.com", "to": "b@example.com", "subject": "Hi", "body": "Body"},
    )
    assert draft.success
    assert "Subject: Hi" in draft.data["draft"]

    blocked = skill.execute(
        "send",
        {
            "from": "a@example.com",
            "to": "b@example.com",
            "subject": "Hi",
            "body": "Body",
            "smtp_host": "localhost",
            "approved": False,
        },
    )
    assert not blocked.success
    assert "explicit approval" in (blocked.error or "")
