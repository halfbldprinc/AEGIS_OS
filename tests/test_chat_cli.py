"""Tests for interactive chat CLI."""

from aegis.chat_cli import InteractiveChat, ChatSession


def test_chat_session_creation():
    session = ChatSession("test-session-1")
    assert session.session_id == "test-session-1"
    assert session.active is True
    assert len(session.messages) == 0


def test_chat_session_add_messages():
    session = ChatSession("test-session-2")
    session.add_message("user", "hello")
    session.add_message("assistant", "hi there")
    
    assert len(session.messages) == 2
    assert session.messages[0]["role"] == "user"
    assert session.messages[0]["content"] == "hello"
    assert session.messages[1]["role"] == "assistant"


def test_chat_session_clear():
    session = ChatSession("test-session-3")
    session.add_message("user", "test")
    session.clear()
    assert len(session.messages) == 0


def test_interactive_chat_init():
    chat = InteractiveChat()
    assert chat.daemon is None
    assert chat.llm_runtime is None
    assert chat.session is None


def test_interactive_chat_start_session():
    chat = InteractiveChat()
    session = chat.start_session("my-session")
    assert session is not None
    assert session.session_id == "my-session"
    assert chat.session == session


def test_interactive_chat_session_exit():
    chat = InteractiveChat()
    chat.start_session()
    response = chat.process_input("exit")
    assert response == "Goodbye! Your session is saved."
    assert chat.session.active is False


def test_interactive_chat_help_command():
    chat = InteractiveChat()
    chat.start_session()
    response = chat.process_input("help")
    assert "Available commands" in response
    assert "status" in response


def test_interactive_chat_clear_history():
    chat = InteractiveChat()
    chat.start_session()
    chat.process_input("hello")
    chat.process_input("help")
    assert len(chat.session.messages) > 0
    
    response = chat.process_input("clear")
    assert response == "Chat history cleared."
    assert len(chat.session.messages) == 0


def test_interactive_chat_status_no_daemon():
    chat = InteractiveChat()
    chat.start_session()
    response = chat.process_input("status")
    assert "Daemon not available" in response


def test_interactive_chat_empty_input():
    chat = InteractiveChat()
    chat.start_session()
    response = chat.process_input("")
    assert response == ""


def test_interactive_chat_quit():
    chat = InteractiveChat()
    chat.start_session()
    response = chat.process_input("quit")
    assert response == "Goodbye! Your session is saved."
    assert chat.session.active is False


def test_interactive_chat_runtime_unavailable():
    chat = InteractiveChat()
    chat.start_session()
    response = chat.process_input("what is aegis?")
    assert "AI runtime not available" in response
