from aegis.daemon import AegisDaemon
from aegis.state import SystemState
from aegis.storage import InMemoryStateStorage
from aegis.voice.stt import STTEngine
from aegis.voice.tts import TTSEngine
from aegis.voice.wakeword import WakeWordDetector
from aegis.orchestrator import Orchestrator, Plan
from aegis.skills.os_control_skill import OSControlSkill


class DummySTT(STTEngine):
    def __init__(self, transcript: str):
        self.transcript = transcript

    def transcribe(self, audio_path: str, model_path: str | None = None) -> str:
        return self.transcript


class DummyTTS(TTSEngine):
    def __init__(self):
        self.spoken = []

    def speak(self, text: str, voice: str | None = None) -> None:
        self.spoken.append(text)


def create_test_daemon():
    in_memory_state = SystemState(storage=InMemoryStateStorage())
    return AegisDaemon(state=in_memory_state)


def test_observation_to_shadow_transition():
    daemon = create_test_daemon()
    daemon.state.set("mode", AegisDaemon.OBSERVATION_MODE)
    daemon.state.set("day", 6)

    daemon.run_cycle()  # day 7
    assert daemon.state.get("mode") == AegisDaemon.ACTIVE_SHADOW_MODE


def test_complete_onboarding_enables_shadow():
    daemon = create_test_daemon()
    daemon.state.set("mode", AegisDaemon.OBSERVATION_MODE)
    daemon.complete_onboarding(True)
    assert daemon.state.get("mode") == AegisDaemon.ACTIVE_SHADOW_MODE


def test_enable_autonomy_sets_active_mode():
    daemon = create_test_daemon()
    daemon.enable_autonomy()
    assert daemon.state.get("mode") == AegisDaemon.ACTIVE_MODE


def test_daemon_shutdown_closes_conversation_manager():
    daemon = create_test_daemon()
    daemon.shutdown()

    assert daemon.conversation_manager._closed is True


def test_daemon_skill_subscription_and_tier_upgrade():
    daemon = create_test_daemon()
    subscriber_events = []

    def callback(skill_name, metadata):
        subscriber_events.append((skill_name, metadata))

    daemon.register_skill_subscriber("test", callback)
    daemon.upgrade_skill_tier("echo", new_tier=3)

    assert daemon.orchestrator.get_skill("echo").tier == 3
    assert subscriber_events == [("echo", {"tier": 3})]


def test_voice_text_flow_with_wakeword_executes_plan():
    daemon = create_test_daemon()

    result = daemon.process_voice_text("aegis hello from voice")
    assert result["plan_status"] == "SUCCEEDED"
    assert result["steps"][0]["skill"] == "echo"
    assert result["steps"][0]["result"] == {"echo": "hello from voice"}


def test_voice_audio_flow_requires_wakeword_for_execution():
    tts = DummyTTS()
    daemon = AegisDaemon(
        state=SystemState(storage=InMemoryStateStorage()),
        stt_engine=DummySTT("hello there"),
        tts_engine=tts,
        wakeword_detector=WakeWordDetector(wake_phrase="aegis"),
    )

    result = daemon.process_voice_audio("/tmp/dummy.wav")
    assert result["wakeword"] is False
    assert result["transcript"] == "hello there"
    assert tts.spoken == []


def test_voice_audio_flow_speaks_when_wakeword_detected():
    tts = DummyTTS()
    daemon = AegisDaemon(
        state=SystemState(storage=InMemoryStateStorage()),
        stt_engine=DummySTT("aegis hello world"),
        tts_engine=tts,
        wakeword_detector=WakeWordDetector(wake_phrase="aegis"),
    )

    result = daemon.process_voice_audio("/tmp/dummy.wav")
    assert result["wakeword"] is True
    assert result["response"]["plan_status"] == "SUCCEEDED"
    assert tts.spoken


def test_voice_monitoring_lifecycle():
    daemon = create_test_daemon()
    daemon.start_voice_monitoring(wakeword_required=False, poll_interval=0.01)
    assert getattr(daemon, "_voice_monitor_thread", None) is not None
    assert daemon._voice_monitor_thread.is_alive()
    daemon.stop_voice_monitoring()
    assert daemon._voice_monitor_thread.is_alive() is False


def test_high_risk_step_blocked_when_unconfirmed():
    orchestrator = Orchestrator()
    orchestrator.register_skill(OSControlSkill())

    plan = Plan()
    step = plan.add_step("os_control", "close", {"app": "TextEdit"})
    step.requires_confirmation = True

    executed = orchestrator.execute_plan(plan, allow_failure=False)
    assert executed.status == "FAILED"
    assert executed.steps[0].status == "DENIED"

