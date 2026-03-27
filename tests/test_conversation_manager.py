"""Tests for conversation manager and feedback integration."""

import time
from fastapi.testclient import TestClient

from aegis.api import app
from aegis.daemon import AegisDaemon
from aegis.conversation_manager import ConversationManager, ConversationTurn


client = TestClient(app)


def test_conversation_turn_creation():
    """Test that ConversationTurn dataclass properly stores turn data."""
    turn = ConversationTurn(
        turn_id="test-123",
        session_id="session-456",
        user_input="hello world",
        plan_result={"status": "success", "steps": 1},
        plan_status="completed",
        user_satisfaction=None,
        created_at=time.time(),
    )
    
    assert turn.turn_id == "test-123"
    assert turn.session_id == "session-456"
    assert turn.user_input == "hello world"
    assert turn.user_satisfaction is None


def test_conversation_manager_record_turn():
    """Test recording a conversation turn."""
    manager = ConversationManager(db_path=":memory:")
    
    turn_id = manager.record_turn(
        session_id="session-1",
        user_input="remind me tomorrow",
        plan_result={"status": "success", "skill": "reminder"},
        plan_status="completed"
    )
    
    assert turn_id is not None
    assert len(turn_id) > 0
    print(f"✓ Recorded turn: {turn_id}")


def test_conversation_manager_rate_turn():
    """Test rating a conversation turn."""
    manager = ConversationManager(db_path=":memory:")
    
    turn_id = manager.record_turn(
        session_id="session-1",
        user_input="search web",
        plan_result={"status": "success"},
        plan_status="completed"
    )
    
    # Rate valid (1-5)
    success = manager.rate_turn(turn_id, satisfaction=5)
    assert success is True
    
    # Rate invalid (<1)
    success = manager.rate_turn(turn_id, satisfaction=0)
    assert success is False
    
    # Rate invalid (>5)
    success = manager.rate_turn(turn_id, satisfaction=6)
    assert success is False

    # Rate unknown turn id
    success = manager.rate_turn("does-not-exist", satisfaction=5)
    assert success is False
    
    print("✓ Turn rating works correctly")


def test_conversation_manager_get_session_history():
    """Test retrieving session history."""
    manager = ConversationManager(db_path=":memory:")
    
    session_id = "session-multi"
    
    # Record 3 turns
    turn_ids = []
    for i in range(3):
        tid = manager.record_turn(
            session_id=session_id,
            user_input=f"command {i}",
            plan_result={"index": i},
            plan_status="completed"
        )
        turn_ids.append(tid)
    
    # Retrieve history
    history = manager.get_session_history(session_id)
    
    assert len(history) == 3
    assert all(isinstance(t, ConversationTurn) for t in history)
    assert history[0].user_input == "command 0"
    assert history[1].user_input == "command 1"
    assert history[2].user_input == "command 2"
    
    print(f"✓ Retrieved {len(history)} turns from session history")


def test_conversation_manager_satisfaction_stats():
    """Test satisfaction statistics computation."""
    manager = ConversationManager(db_path=":memory:")
    
    # Record turns with ratings
    ratings = [5, 4, 5, 3, 5]  # avg = 4.4
    for idx, rating in enumerate(ratings):
        tid = manager.record_turn(
            session_id="session-stats",
            user_input=f"input {idx}",
            plan_result={},
            plan_status="completed"
        )
        manager.rate_turn(tid, satisfaction=rating)
    
    # Get stats
    stats = manager.get_satisfaction_stats(session_id="session-stats")
    
    assert stats["total_rated"] == 5
    assert 4.3 < stats["average_satisfaction"] < 4.5  # ~4.4
    assert stats["distribution"][5] == 3
    assert stats["distribution"][4] == 1
    assert stats["distribution"][3] == 1
    
    print(f"✓ Satisfaction avg: {stats['average_satisfaction']:.1f}/{5}")


def test_conversation_manager_global_stats():
    """Test global satisfaction stats across all sessions."""
    manager = ConversationManager(db_path=":memory:")
    
    # Add turns to multiple sessions
    for session in ["sess-a", "sess-b"]:
        for i in range(2):
            tid = manager.record_turn(
                session_id=session,
                user_input=f"input {i}",
                plan_result={},
                plan_status="completed"
            )
            manager.rate_turn(tid, satisfaction=4)
    
    # Get global stats (no session_id filter)
    stats = manager.get_satisfaction_stats()
    
    assert stats["total_rated"] == 4
    assert stats["average_satisfaction"] == 4.0
    
    print(f"✓ Global stats: {stats['total_rated']} rated turns")


def test_daemon_conversation_integration():
    """Test that daemon records conversations during voice execution."""
    app.state.daemon = AegisDaemon()
    daemon_ref = app.state.daemon
    daemon_ref.conversation_manager = ConversationManager(db_path=":memory:")

    session_id = daemon_ref.voice_session_id
    
    # Execute a voice command
    result = daemon_ref.process_voice_text("aegis echo hello world")
    
    # Verify it recorded the turn
    history = daemon_ref.conversation_manager.get_session_history(session_id)
    assert len(history) > 0
    
    last_turn = history[-1]
    assert "echo" in last_turn.user_input.lower() or "hello" in last_turn.user_input
    assert last_turn.plan_status == "SUCCEEDED"
    
    print(f"✓ Daemon recorded {len(history)} conversation turns")


def test_api_rate_endpoint():
    """Test the API endpoint for rating conversation turns."""
    app.state.daemon = AegisDaemon()
    daemon_ref = app.state.daemon
    daemon_ref.conversation_manager = ConversationManager(db_path=":memory:")

    # Record a turn first
    tid = daemon_ref.conversation_manager.record_turn(
        session_id="api-test",
        user_input="test input",
        plan_result={},
        plan_status="completed"
    )
    
    # Rate via API
    response = client.post(
        "/v1/feedback/rate",
        json={"turn_id": tid, "satisfaction": 5}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["satisfaction"] == 5
    
    print("✓ API feedback endpoint works")


def test_api_history_endpoint():
    """Test the API endpoint for retrieving conversation history."""
    app.state.daemon = AegisDaemon()
    daemon_ref = app.state.daemon
    daemon_ref.conversation_manager = ConversationManager(db_path=":memory:")

    session_id = "api-history-test"
    
    # Record 2 turns
    for i in range(2):
        daemon_ref.conversation_manager.record_turn(
            session_id=session_id,
            user_input=f"turn {i}",
            plan_result={},
            plan_status="completed"
        )
    
    # Query via API
    response = client.get(
        "/v1/conversation/history",
        params={"session_id": session_id}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["total_turns"] == 2
    assert data["session_id"] == session_id
    assert len(data["turns"]) == 2
    
    print(f"✓ API history endpoint returned {len(data['turns'])} turns")


def test_api_stats_endpoint():
    """Test the API endpoint for satisfaction statistics."""
    app.state.daemon = AegisDaemon()
    daemon_ref = app.state.daemon
    daemon_ref.conversation_manager = ConversationManager(db_path=":memory:")

    session_id = "api-stats-test"
    
    # Record rated turns
    for rating in [5, 4, 5]:
        tid = daemon_ref.conversation_manager.record_turn(
            session_id=session_id,
            user_input="input",
            plan_result={},
            plan_status="completed"
        )
        daemon_ref.conversation_manager.rate_turn(tid, satisfaction=rating)
    
    # Query via API
    response = client.get(
        "/v1/conversation/stats",
        params={"session_id": session_id}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["total_rated"] == 3
    assert data["session_id"] == session_id
    assert 4.6 < data["average_satisfaction"] < 4.8  # avg = 14/3 ≈ 4.67
    
    print(f"✓ API stats endpoint returned satisfaction {data['average_satisfaction']:.2f}")


def test_conversation_manager_empty_history():
    """Test retrieving history for non-existent session."""
    manager = ConversationManager(db_path=":memory:")
    
    history = manager.get_session_history("nonexistent")
    assert history == []
    
    stats = manager.get_satisfaction_stats("nonexistent")
    assert stats["total_rated"] == 0
    assert stats["average_satisfaction"] == 0.0
    
    print("✓ Empty session handling works")


def test_conversation_manager_list_sessions():
    manager = ConversationManager(db_path=":memory:")
    manager.record_turn("s1", "a", {}, "ok")
    manager.record_turn("s2", "b", {}, "ok")
    manager.record_turn("s1", "c", {}, "ok")

    sessions = manager.list_sessions()
    assert set(sessions) == {"s1", "s2"}


if __name__ == "__main__":
    print("Running conversation manager tests...\n")
    
    # Run unit tests
    test_conversation_turn_creation()
    test_conversation_manager_record_turn()
    test_conversation_manager_rate_turn()
    test_conversation_manager_get_session_history()
    test_conversation_manager_satisfaction_stats()
    test_conversation_manager_global_stats()
    test_conversation_manager_empty_history()
    
    print("\n✓ All conversation manager unit tests passed")
