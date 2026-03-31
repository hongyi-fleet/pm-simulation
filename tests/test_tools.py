"""Tests for tool surfaces — from test plan section 'Tool Surface Validation'."""

from src.engine.world_state import WorldState
from src.tools.chat import ChatTool
from src.tools.email_tool import EmailTool
from src.tools.tasks import TaskTool
from src.tools.calendar_tool import CalendarTool
from src.tools.documents import DocumentsTool
from src.tools.meetings import MeetingsTool


def make_ws():
    return WorldState(":memory:")


def test_chat_send_and_read():
    ws = make_ws()
    chat = ChatTool(ws)
    result = chat.handle_action("send_chat", {"channel": "general", "message": "hello", "sender": "PM"}, tick=0)
    assert result.success

    result = chat.handle_action("read_chats", {"channel": "general"}, tick=0)
    assert result.success
    assert len(result.data) == 1
    assert result.data[0]["content"] == "hello"


def test_email_invalid_recipient():
    ws = make_ws()
    email = EmailTool(ws, valid_people=["Alex", "Priya"])
    result = email.handle_action("send_email", {"to": "Nobody", "subject": "hi", "body": "test", "sender": "PM"}, tick=0)
    assert not result.success
    assert "Unknown recipient" in result.error


def test_email_valid_send():
    ws = make_ws()
    email = EmailTool(ws, valid_people=["Alex"])
    result = email.handle_action("send_email", {"to": "Alex", "subject": "hi", "body": "test", "sender": "PM"}, tick=0)
    assert result.success


def test_task_create_and_list():
    ws = make_ws()
    tasks = TaskTool(ws)
    result = tasks.handle_action("create_task", {"project": "Billing", "title": "Test task"}, tick=0)
    assert result.success

    result = tasks.handle_action("list_tasks", {"project": "Billing"}, tick=0)
    assert result.success
    assert len(result.data) == 1
    assert result.data[0]["title"] == "Test task"


def test_task_update_nonexistent():
    ws = make_ws()
    tasks = TaskTool(ws)
    result = tasks.handle_action("update_task", {"task_id": 999, "status": "done"}, tick=0)
    assert not result.success
    assert "not found" in result.error


def test_calendar_past_meeting():
    ws = make_ws()
    cal = CalendarTool(ws)
    result = cal.handle_action("schedule_meeting", {"tick": 0, "attendees": ["Alex"], "title": "Test"}, tick=5)
    assert not result.success
    assert "past" in result.error


def test_calendar_future_meeting():
    ws = make_ws()
    cal = CalendarTool(ws)
    result = cal.handle_action("schedule_meeting", {"tick": 10, "attendees": ["Alex"], "title": "Test"}, tick=5)
    assert result.success


def test_documents_create_read():
    ws = make_ws()
    docs = DocumentsTool(ws)
    result = docs.handle_action("create_doc", {"title": "Design Doc", "content": "Hello world", "author": "PM"}, tick=0)
    assert result.success

    result = docs.handle_action("read_doc", {"title": "Design Doc"}, tick=0)
    assert result.success
    assert result.data["content"] == "Hello world"


def test_documents_not_found():
    ws = make_ws()
    docs = DocumentsTool(ws)
    result = docs.handle_action("read_doc", {"title": "Nonexistent"}, tick=0)
    assert not result.success
    assert "not found" in result.error


def test_documents_duplicate():
    ws = make_ws()
    docs = DocumentsTool(ws)
    docs.handle_action("create_doc", {"title": "Doc", "content": "v1"}, tick=0)
    result = docs.handle_action("create_doc", {"title": "Doc", "content": "v2"}, tick=1)
    assert not result.success
    assert "already exists" in result.error


def test_meetings_read_only():
    ws = make_ws()
    meetings = MeetingsTool(ws)
    meetings.generate_transcript("Standup", tick=0, attendees="Alex,Priya", transcript="Alex: things are fine")

    result = meetings.handle_action("list_meetings", {}, tick=1)
    assert result.success
    assert len(result.data) == 1

    result = meetings.handle_action("read_transcript", {"id": 1}, tick=1)
    assert result.success
    assert "Alex: things are fine" in result.data["transcript"]


def test_meetings_not_found():
    ws = make_ws()
    meetings = MeetingsTool(ws)
    result = meetings.handle_action("read_transcript", {"id": 999}, tick=0)
    assert not result.success


def test_tool_schemas():
    """Each tool returns a valid schema dict."""
    ws = make_ws()
    tools = [
        ChatTool(ws), EmailTool(ws), TaskTool(ws),
        CalendarTool(ws), DocumentsTool(ws), MeetingsTool(ws),
    ]
    for tool in tools:
        schema = tool.schema()
        assert isinstance(schema, dict)
        assert len(schema) > 0
        for action_name, action_schema in schema.items():
            assert "description" in action_schema
            assert "parameters" in action_schema
