import json
import logging
from typing import Any, Dict, List, Optional

from .memory import MemoryStore
from .personalization import PersonalizationEngine
from .orchestrator.core import Plan
from .orchestrator import Orchestrator
from .llm.runtime import LLMRuntime, LLMUnavailableError
from .llm.grammar import build_plan_grammar
from .planning.rule_fallback import RuleFallbackPlanner

logger = logging.getLogger(__name__)


class Planner:
    def __init__(
        self,
        llm_runtime: Optional[LLMRuntime] = None,
        orchestrator: Optional[Orchestrator] = None,
        memory_store: Optional[MemoryStore] = None,
        personalization: Optional[PersonalizationEngine] = None,
        conversation_manager=None,
        prompt_template: str | None = None,
    ):
        self.llm_runtime = llm_runtime or LLMRuntime()
        self.orchestrator = orchestrator or Orchestrator()
        self.memory_store = memory_store or MemoryStore()
        self.personalization = personalization or PersonalizationEngine()
        self.conversation_manager = conversation_manager

        self.prompt_template = prompt_template or (
            "You are a planner that converts user requests to an orchestrator plan.\n"
            "Response must be valid JSON with a 'steps' array where each step has 'skill', 'action', and optional 'params'."
        )
        self.rule_fallback = RuleFallbackPlanner()

        self.short_circuit_keywords = ["status", "time", "date", "weather", "search", "open"]
        self.high_risk_actions = {
            "file": {"write", "append", "delete", "move", "copy"},
            "shell": {"run"},
            "email": {"send"},
            "settings": {"volume", "brightness", "dnd", "network"},
            "os_control": {"launch", "close", "focus", "clipboard_set"},
        }

    def plan(self, user_input: str, conversation_history: Optional[List[Dict[str, Any]]] = None, system_state: Optional[Dict[str, Any]] = None) -> Plan:
        conversation_history = list(conversation_history or [])

        if self._should_short_circuit(user_input):
            sc_plan = self._short_circuit_plan(user_input)
            if sc_plan is not None and sc_plan.steps:
                return sc_plan

        available_skills = [skill.name for skill in self.orchestrator.skills.values()]
        grammar = build_plan_grammar(available_skills)

        if self.conversation_manager:
            history_turns = self.conversation_manager.get_session_history(self.conversation_manager.get_session_id() if hasattr(self.conversation_manager, 'get_session_id') else 'default')
            for turn in history_turns[-5:]:
                conversation_history.append({"role": "assistant", "content": turn.plan_result.get("text", "")})
                conversation_history.append({"role": "user", "content": turn.user_input})

        if self.memory_store is not None:
            memory_hits = self.memory_store.search(user_input, top_k=3)
            for hit in memory_hits:
                conversation_history.append({"role": "system", "content": f"Memory context: {hit['text']}"})

        system_prompt = {
            "role": "system",
            "content": self.prompt_template + " " + self.personalization.inject_system_style(),
        }

        messages = [system_prompt] + conversation_history + [{"role": "user", "content": user_input}]

        try:
            plan_text = self.llm_runtime.generate(messages, temperature=0.2, max_tokens=512, grammar=grammar)
            plan_data = json.loads(plan_text)

            plan = Plan()
            if isinstance(plan_data, dict) and plan_data.get("steps"):
                for step in plan_data["steps"]:
                    skill = step.get("skill")
                    action = step.get("action")
                    params = step.get("params", {}) or {}
                    if skill and action and skill in self.orchestrator.skills:
                        ps = plan.add_step(skill_name=skill, action=action, params=params)
                        ps.requires_confirmation = self._is_high_risk_step(skill, action)

            if not plan.steps or not self._validate_plan(plan):
                raise ValueError("No valid plan steps generated")

            return plan

        except (LLMUnavailableError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Planner fell back to default LLMSkill plan due to: %s", exc)

            rules_plan = self._plan_from_rules(user_input)
            if rules_plan is not None:
                return rules_plan

            fallback_plan = Plan()
            fallback_plan.add_step(skill_name="llm", action="reason", params={"messages": messages})
            return fallback_plan
        except Exception:
            logger.exception("Planner fell back to default LLMSkill plan due to unexpected error")

            rules_plan = self._plan_from_rules(user_input)
            if rules_plan is not None:
                return rules_plan

            fallback_plan = Plan()
            fallback_plan.add_step(skill_name="llm", action="reason", params={"messages": messages})
            return fallback_plan

    def _should_short_circuit(self, user_input: str) -> bool:
        lowered = (user_input or "").lower()
        return any(keyword in lowered for keyword in self.short_circuit_keywords)

    def _short_circuit_plan(self, user_input: str) -> Optional[Plan]:
        lower = user_input.lower().strip()
        if lower.startswith("what is") or lower.startswith("who is") or lower.startswith("define") or lower.startswith("search"):
            plan = Plan()
            if "web_search" in self.orchestrator.skills:
                plan.add_step(skill_name="web_search", action="search", params={"query": user_input, "limit": 3})
                return plan
        if "open " in lower and "browser" not in lower and ("http://" in user_input or "https://" in user_input):
            plan = Plan()
            if "browser" in self.orchestrator.skills:
                url = self._extract_url(user_input) or user_input
                plan.add_step(skill_name="browser", action="open_url", params={"url": url})
                return plan
        return None

    def _validate_plan(self, plan: Plan) -> bool:
        if not plan.steps:
            return False

        for step in plan.steps:
            if not step.skill_name or not step.action:
                return False
            if step.skill_name not in self.orchestrator.skills:
                return False
        return True

    def _is_high_risk_step(self, skill_name: str, action: str) -> bool:
        return action in self.high_risk_actions.get(skill_name, set())

    def _plan_from_rules(self, user_input: str) -> Optional[Plan]:
        return self.rule_fallback.build_plan(user_input, set(self.orchestrator.skills.keys()))

    def _extract_search_query(self, text: str) -> Optional[str]:
        return self.rule_fallback.extract_search_query(text)

    def _extract_url(self, text: str) -> Optional[str]:
        return self.rule_fallback.extract_url(text)

    def _parse_reminder(self, lower: str) -> Optional[tuple[str, Dict[str, Any]]]:
        return self.rule_fallback.parse_reminder(lower)

    def _parse_calendar(self, lower: str) -> Optional[tuple[str, Dict[str, Any]]]:
        return self.rule_fallback.parse_calendar(lower)

    def _parse_email(self, text: str) -> Optional[tuple[str, Dict[str, Any]]]:
        return self.rule_fallback.parse_email(text)

    def simulate(self, user_input: str) -> Dict[str, Any]:
        plan = self.plan(user_input)
        return self.orchestrator.simulate_plan(plan)
