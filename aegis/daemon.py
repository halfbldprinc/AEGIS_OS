import logging
import threading
import time
from pathlib import Path
from typing import Dict, Any, List

from .orchestrator import Orchestrator, Plan
from .skills.echo_skill import EchoSkill
from .skills.llm_skill import LLMSkill
from .skills.file_skill import FileSkill
from .skills.shell_skill import ShellSkill
from .skills.os_control_skill import OSControlSkill
from .skills.settings_skill import SettingsSkill
from .skills.package_manager_skill import PackageManagerSkill
from .skills.web_search_skill import WebSearchSkill
from .skills.http_skill import HttpSkill
from .skills.batch_file_skill import BatchFileSkill
from .skills.json_transform_skill import JsonTransformSkill
from .skills.browser_skill import BrowserSkill
from .skills.email_skill import EmailSkill
from .skills.reminder_skill import ReminderSkill
from .skills.calendar_skill import CalendarSkill
from .planner import Planner
from .llm.runtime import LLMRuntime
from .state import SystemState
from .trust_ledger import TrustLedger
from .resource_scheduler import ResourceScheduler
from .audit import AuditLog
from .telemetry import TelemetryManager
from .utils.time import now_utc
from .voice.session import VoiceSessionManager
from .voice.stt import STTEngine
from .voice.tts import TTSEngine
from .voice.wakeword import WakeWordDetector
from .conversation_manager import ConversationManager
from .permission_prompt import LocalPermissionPrompt

logger = logging.getLogger(__name__)

class AegisDaemon:
    """High level process manager for AegisOS components."""

    OBSERVATION_MODE = "OBSERVATION_MODE"
    ACTIVE_SHADOW_MODE = "ACTIVE_SHADOW_MODE"
    ACTIVE_MODE = "ACTIVE_MODE"
    OBSERVATION_DAYS = 7

    def __init__(
        self,
        state: SystemState | None = None,
        trust_ledger: TrustLedger | None = None,
        orchestrator: Orchestrator | None = None,
        audit_log: AuditLog | None = None,
        stt_engine: STTEngine | None = None,
        tts_engine: TTSEngine | None = None,
        wakeword_detector: WakeWordDetector | None = None,
    ):
        self.state = state or SystemState()
        self.trust_ledger = trust_ledger or TrustLedger()
        self.orchestrator = orchestrator or Orchestrator(self.trust_ledger)
        self.orchestrator.load_skill_plugins()
        self.resource_scheduler = ResourceScheduler()
        self.audit_log = audit_log or AuditLog()
        self.telemetry_manager = TelemetryManager()
        self.subscribers: Dict[str, Any] = {}
        self.telemetry: Dict[str, Any] = {
            "cycle_latencies_ms": [],
            "p95_cycle_latency_ms": 0,
        }
        self.plan_store: Dict[str, Plan] = {}
        self.input_queue: List[str] = []
        self.voice_session_id = "default"

        self.llm_runtime = LLMRuntime()
        self.planner = Planner(llm_runtime=self.llm_runtime, orchestrator=self.orchestrator)
        db_dir = Path.home() / ".aegis" / "data"
        db_dir.mkdir(parents=True, exist_ok=True)
        self.conversation_manager = ConversationManager(db_path=str(db_dir / "conversations.db"))
        self.voice_session = VoiceSessionManager(
            stt=stt_engine or STTEngine(),
            tts=tts_engine or TTSEngine(),
            wakeword=wakeword_detector or WakeWordDetector(),
            process_text=self.process_voice_text,
        )
        self.permission_prompt = LocalPermissionPrompt()

        self._register_default_skills()

    def register_skill_subscriber(self, name: str, callback: Any) -> None:
        self.subscribers[name] = callback

    def unregister_skill_subscriber(self, name: str) -> None:
        self.subscribers.pop(name, None)

    def notify_skill_subscribers(self, skill_name: str, metadata: Dict[str, Any]) -> None:
        for callback in list(self.subscribers.values()):
            try:
                callback(skill_name, metadata)
            except Exception:
                logger.exception("Skill subscriber callback failed for %s", skill_name)
                continue

    def upgrade_skill_tier(self, skill_name: str, new_tier: int) -> None:
        skill = self.orchestrator.get_skill(skill_name)
        skill.tier = new_tier
        self.orchestrator.registry.register(skill_name, new_tier, skill.get_permissions())
        self.notify_skill_subscribers(skill_name, {"tier": new_tier})

    def _register_default_skills(self) -> None:
        self.orchestrator.register_skill(EchoSkill())
        self.orchestrator.register_skill(LLMSkill(llm_runtime=self.llm_runtime))
        self.orchestrator.register_skill(FileSkill())
        self.orchestrator.register_skill(ShellSkill())
        self.orchestrator.register_skill(OSControlSkill())
        self.orchestrator.register_skill(SettingsSkill())
        self.orchestrator.register_skill(PackageManagerSkill())
        self.orchestrator.register_skill(WebSearchSkill())
        self.orchestrator.register_skill(HttpSkill())
        self.orchestrator.register_skill(BatchFileSkill())
        self.orchestrator.register_skill(JsonTransformSkill())
        self.orchestrator.register_skill(BrowserSkill())
        self.orchestrator.register_skill(EmailSkill())
        self.orchestrator.register_skill(ReminderSkill())
        self.orchestrator.register_skill(CalendarSkill())

    def start(self) -> None:
        logger.info("Starting Aegis daemon in %s", self.state.get("mode"))

    def shutdown(self) -> None:
        logger.info("Shutting down Aegis daemon")
        try:
            self.stop_voice_monitoring()
        except Exception:
            logger.exception("Failed stopping voice monitoring during shutdown")
        try:
            self.conversation_manager.close()
        except Exception:
            logger.exception("Failed closing conversation manager during shutdown")

    def _collect_observation(self) -> None:
        day = self.state.increment("day", 1)
        logger.info("Observation mode day %d", day)

    def _spawn_shadow_job(self) -> None:
        plan = Plan()
        plan.add_step(skill_name="echo", action="echo", params={"message": "shadow-test"})
        executed = self.orchestrator.execute_plan(plan, allow_failure=True)
        logger.debug("Shadow plan status=%s", executed.status)

    def create_plan_from_instruction(self, instruction: str) -> Plan:
        plan = self.planner.plan(instruction, [], dict(self.state._state))
        self.plan_store[plan.id] = plan
        self.audit_log.record("daemon", "plan_created", {"plan_id": plan.id, "instruction": instruction})
        return plan

    def _strip_wake_phrase(self, transcript: str) -> str:
        phrase = self.voice_session.wakeword.wake_phrase.lower().strip()
        lowered = transcript.lower().strip()
        if lowered.startswith(phrase):
            return transcript[len(phrase):].lstrip(" ,:.-")
        return transcript

    def _is_high_risk_step(self, skill_name: str, action: str) -> bool:
        risky_actions = {
            "file": {"write", "append", "delete", "move", "copy"},
            "shell": {"run"},
            "package_manager": {"install", "remove", "upgrade"},
            "email": {"send"},
            "settings": {"volume", "brightness", "dnd", "network"},
            "os_control": {"launch", "close", "focus", "clipboard_set"},
        }
        return action in risky_actions.get(skill_name, set())

    def _summarize_plan_result(self, plan: Plan) -> str:
        if plan.status != "SUCCEEDED":
            return "I could not complete that request."

        if not plan.steps:
            return "Completed."

        step = plan.steps[-1]
        if not step.result or not step.result.success:
            return "The task failed during execution."

        data = step.result.data or {}
        if step.skill_name == "echo":
            return str(data.get("echo", "Done"))
        if step.skill_name == "web_search":
            count = len(data.get("results", []))
            return f"Found {count} search results."
        if step.skill_name == "reminder" and step.action == "add":
            return f"Reminder set: {data.get('title', 'task')}"
        if step.skill_name == "calendar" and step.action == "add_event":
            return f"Event scheduled: {data.get('title', 'event')}"
        if step.skill_name == "email" and step.action == "draft":
            return "Email draft is ready."
        return "Done."

    def process_voice_text(self, transcript: str) -> Dict[str, Any]:
        if not self.voice_session.wakeword.detect(transcript):
            return {"text": "I heard the wake word, but no command followed."}

        cleaned = self._strip_wake_phrase(transcript)
        if not cleaned:
            return {"text": "I heard the wake word, but no command followed."}

        plan = self.create_plan_from_instruction(cleaned)

        for step in plan.steps:
            if self._is_high_risk_step(step.skill_name, step.action):
                self.audit_log.record(
                    "daemon",
                    "voice_requires_approval",
                    {"plan_id": plan.id, "skill": step.skill_name, "action": step.action},
                )
                return {
                    "text": "This request requires explicit approval before execution.",
                    "plan_id": plan.id,
                    "requires_approval": True,
                }

        executed = self.orchestrator.execute_plan(plan, allow_failure=False)
        self.plan_store[executed.id] = executed
        turn_id = self.conversation_manager.record_turn(
            session_id=self.voice_session_id,
            user_input=cleaned,
            plan_result={
                "plan_id": executed.id,
                "status": executed.status,
                "steps": [
                    {
                        "id": s.id,
                        "skill": s.skill_name,
                        "action": s.action,
                        "status": s.status,
                        "result": s.result.data if s.result else None,
                    }
                    for s in executed.steps
                ],
            },
            plan_status=executed.status,
        )
        spoken = self._summarize_plan_result(executed)
        self.audit_log.record("daemon", "voice_plan_executed", {"plan_id": executed.id, "status": executed.status})

        return {
            "text": spoken,
            "plan_id": executed.id,
            "turn_id": turn_id,
            "plan_status": executed.status,
            "steps": [
                {
                    "id": s.id,
                    "skill": s.skill_name,
                    "action": s.action,
                    "status": s.status,
                    "result": s.result.data if s.result else None,
                }
                for s in executed.steps
            ],
        }

    def process_voice_audio(self, audio_path: str) -> Dict[str, Any]:
        return self.voice_session.handle_audio(audio_path)

    def start_voice_monitoring(self, wakeword_required: bool = True, poll_interval: float = 1.0) -> None:
        if getattr(self, "_voice_monitor_thread", None) and self._voice_monitor_thread.is_alive():
            return

        self._voice_monitor_stop = False
        self.voice_session.reset_interrupt()

        def on_voice_event(event: Dict[str, Any]) -> None:
            try:
                self.audit_log.record(
                    "daemon",
                    "voice_stream_event",
                    {
                        "wakeword": bool(event.get("wakeword", False)),
                        "has_response": bool(event.get("response")),
                    },
                )
            except Exception:
                logger.exception("Failed to record voice stream event")

        def monitor_loop():
            try:
                self.voice_session.stream_loop(
                    audio_source=self.voice_session.listen,
                    wakeword_required=wakeword_required,
                    poll_interval=poll_interval,
                    on_result=on_voice_event,
                )
            except Exception:
                logger.exception("Voice monitor loop terminated unexpectedly")

        self._voice_monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._voice_monitor_thread.start()

    def stop_voice_monitoring(self) -> None:
        self._voice_monitor_stop = True
        self.voice_session.interrupt()
        if getattr(self, "_voice_monitor_thread", None):
            self._voice_monitor_thread.join(timeout=1)

    def get_plan(self, plan_id: str) -> Plan | None:
        return self.plan_store.get(plan_id)

    def enqueue_input(self, text: str) -> None:
        self.input_queue.append(text)

    def has_pending_input(self) -> bool:
        return len(self.input_queue) > 0

    def get_pending_input(self) -> str:
        return self.input_queue.pop(0)

    def confirm_plan_step(self, plan_id: str, step_id: str, approved: bool) -> Plan:
        plan = self.get_plan(plan_id)
        if plan is None:
            raise KeyError(f"Plan not found: {plan_id}")

        step = next((s for s in plan.steps if s.id == step_id), None)
        if step is None:
            raise KeyError(f"Step not found: {step_id}")

        if not approved:
            step.status = "DENIED"
            step.result = None
            self.audit_log.record("daemon", "plan_step_denied", {"plan_id": plan_id, "step_id": step_id})
            plan.mark_failed()
            return plan

        # Grant this exact capability after explicit approval so later executions
        # of the same task do not prompt again.
        self.orchestrator.guardian.grant(step.skill_name, step.action)
        step.params["confirmed"] = True
        self.audit_log.record("daemon", "plan_step_approved", {"plan_id": plan_id, "step_id": step_id})
        executed_plan = self.orchestrator.execute_plan(plan, allow_failure=False)
        self.plan_store[plan.id] = executed_plan
        return executed_plan

    def _permission_request_from_plan(self, plan: Plan) -> Dict[str, Any] | None:
        for step in plan.steps:
            if step.status != "DENIED" or step.result is None:
                continue
            error = step.result.error or ""
            if "denied by guardian" not in error:
                continue
            return {
                "plan_id": plan.id,
                "step_id": step.id,
                "skill": step.skill_name,
                "action": step.action,
                "reason": error,
                "requires_approval": True,
            }
        return None

    def execute_plan_by_id(self, plan_id: str, allow_failure: bool = False) -> Dict[str, Any]:
        plan = self.get_plan(plan_id)
        if plan is None:
            raise KeyError(f"Plan not found: {plan_id}")

        executed = self.orchestrator.execute_plan(plan, allow_failure=allow_failure)
        self.plan_store[plan.id] = executed

        permission_request = self._permission_request_from_plan(executed)
        if permission_request:
            # If local UI is available, ask immediately and persist approval.
            local_decision = self.permission_prompt.request(permission_request)
            if local_decision is True:
                confirmed_plan = self.confirm_plan_step(plan_id=executed.id, step_id=permission_request["step_id"], approved=True)
                return {
                    "plan_id": confirmed_plan.id,
                    "status": confirmed_plan.status,
                    "requires_approval": False,
                    "approved_via_local_ui": True,
                    "steps": [
                        {
                            "id": s.id,
                            "skill": s.skill_name,
                            "action": s.action,
                            "status": s.status,
                            "result": s.result.data if s.result else None,
                            "error": s.result.error if s.result else None,
                        }
                        for s in confirmed_plan.steps
                    ],
                }

            if local_decision is False:
                _ = self.confirm_plan_step(plan_id=executed.id, step_id=permission_request["step_id"], approved=False)

            return {
                "plan_id": executed.id,
                "status": executed.status,
                "requires_approval": True,
                "approval": permission_request,
                "steps": [
                    {
                        "id": s.id,
                        "skill": s.skill_name,
                        "action": s.action,
                        "status": s.status,
                        "result": s.result.data if s.result else None,
                        "error": s.result.error if s.result else None,
                    }
                    for s in executed.steps
                ],
            }

        return {
            "plan_id": executed.id,
            "status": executed.status,
            "requires_approval": False,
            "steps": [
                {
                    "id": s.id,
                    "skill": s.skill_name,
                    "action": s.action,
                    "status": s.status,
                    "result": s.result.data if s.result else None,
                    "error": s.result.error if s.result else None,
                }
                for s in executed.steps
            ],
        }

    def run_cycle(self) -> None:
        mode = self.state.get("mode", self.OBSERVATION_MODE)
        self.audit_log.record("daemon", "cycle_started", {"mode": mode})

        start_ms = now_utc().timestamp() * 1000
        resource_decision = self.resource_scheduler.schedule_yield()
        elapsed_ms = now_utc().timestamp() * 1000 - start_ms

        self.telemetry["cycle_latencies_ms"].append(elapsed_ms)
        sorted_latencies = sorted(self.telemetry["cycle_latencies_ms"])
        p95 = sorted_latencies[int(len(sorted_latencies) * 0.95) - 1] if sorted_latencies else 0
        self.telemetry["p95_cycle_latency_ms"] = p95

        self.telemetry_manager.record_metric("daemon_cycle_latency_p95_ms", p95)
        self.telemetry_manager.record_metric("daemon_cycle_last_ms", elapsed_ms)

        self.audit_log.record("daemon", "resource_decision", resource_decision)
        if resource_decision.get("throttle"):
            logger.warning("Resource pressure detected, throttling non-critical operations")
            self.state.set("throttled", True)
        else:
            self.state.set("throttled", False)

        if mode == self.OBSERVATION_MODE:
            self._collect_observation()
            if self.state.get("day", 1) >= self.OBSERVATION_DAYS:
                logger.info("Observation complete, switching to onboarding (shadow) mode")
                self.state.set("mode", self.ACTIVE_SHADOW_MODE)
                self.audit_log.record("daemon", "mode_transition", {"from": self.OBSERVATION_MODE, "to": self.ACTIVE_SHADOW_MODE})

        elif mode == self.ACTIVE_SHADOW_MODE:
            logger.info("Active shadow mode: executing safe plan")
            self._spawn_shadow_job()

        elif mode == self.ACTIVE_MODE:
            logger.info("Active mode: processing input queue")
            if self.has_pending_input():
                user_input = self.get_pending_input()
                plan = self.planner.plan(user_input, [], self.state._state)
                executed_plan = self.orchestrator.execute_plan(plan)
                self.plan_store[executed_plan.id] = executed_plan
                self.audit_log.record("daemon", "input_executed", {"input": user_input, "plan_id": executed_plan.id})
            else:
                self._spawn_shadow_job()

        else:
            logger.warning("Unknown mode %s, resetting to observation", mode)
            self.state.set("mode", self.OBSERVATION_MODE)
            self.audit_log.record("daemon", "mode_transition", {"from": mode, "to": self.OBSERVATION_MODE})

    def run_soak_test(self, cycles: int = 100, sleep_s: float = 0.0) -> Dict[str, Any]:
        failures = 0
        started = now_utc()

        for _ in range(max(1, cycles)):
            try:
                self.run_cycle()
            except Exception as exc:
                failures += 1
                self.audit_log.record("daemon", "soak_cycle_failed", {"error": str(exc)})
            if sleep_s > 0:
                time.sleep(sleep_s)

        finished = now_utc()
        result = {
            "cycles": max(1, cycles),
            "failures": failures,
            "success_rate": (max(1, cycles) - failures) / max(1, cycles),
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
        }
        self.audit_log.record("daemon", "soak_test_completed", result)
        return result

    def run_chaos_scenario(self, scenario: str) -> Dict[str, Any]:
        supported = {"llm_restart", "voice_interrupt"}
        if scenario not in supported:
            return {"scenario": scenario, "status": "unsupported"}

        if scenario == "llm_restart":
            try:
                self.llm_runtime.stop()
                self.audit_log.record("daemon", "chaos_llm_stopped", {})
                # Start is best-effort because local runtime may not be installed in all environments.
                try:
                    self.llm_runtime.start()
                    status = "recovered"
                except Exception as exc:
                    status = "degraded"
                    self.audit_log.record("daemon", "chaos_llm_restart_failed", {"error": str(exc)})
                return {"scenario": scenario, "status": status}
            except Exception as exc:
                return {"scenario": scenario, "status": "failed", "error": str(exc)}

        if scenario == "voice_interrupt":
            try:
                self.start_voice_monitoring(wakeword_required=False, poll_interval=0.01)
                self.stop_voice_monitoring()
                return {"scenario": scenario, "status": "recovered"}
            except Exception as exc:
                return {"scenario": scenario, "status": "failed", "error": str(exc)}

        return {"scenario": scenario, "status": "unsupported"}

    def complete_onboarding(self, approved: bool) -> None:
        if approved:
            logger.info("Onboarding approved -> switching to %s", self.ACTIVE_SHADOW_MODE)
            self.state.set("mode", self.ACTIVE_SHADOW_MODE)
            self.audit_log.record("daemon", "onboarding_complete", {"approved": True})
        else:
            logger.info("Onboarding rejected / reset -> resetting observation timeline")
            self.state.set("day", 1)
            self.state.set("mode", self.OBSERVATION_MODE)
            self.audit_log.record("daemon", "onboarding_complete", {"approved": False})

    def enable_autonomy(self) -> None:
        logger.info("Autonomy enabled -> switching to %s", self.ACTIVE_MODE)
        self.state.set("mode", self.ACTIVE_MODE)

    def get_status(self) -> Dict[str, Any]:
        return {
            "mode": self.state.get("mode"),
            "day": self.state.get("day"),
            "trust": self.trust_ledger.export(),
        }

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            "cycle_latencies_ms": list(self.telemetry.get("cycle_latencies_ms", [])),
            "p95_cycle_latency_ms": self.telemetry.get("p95_cycle_latency_ms", 0),
            "resource_scheduler": self.resource_scheduler.get_metrics(),
            "skill_action_sli": self.orchestrator.get_skill_action_telemetry(),
        }
