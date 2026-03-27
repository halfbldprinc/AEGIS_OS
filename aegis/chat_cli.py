"""Interactive chat CLI for boot-to-agent experience."""

from __future__ import annotations

import logging
from typing import Optional, Any, Dict

logger = logging.getLogger(__name__)


class ChatSession:
    """Manage a single chat conversation session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: list[Dict[str, str]] = []
        self.active = True

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the session."""
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > 200:  # Trim very old messages
            self.messages = self.messages[-100:]

    def get_history(self) -> list[Dict[str, str]]:
        """Get full message history."""
        return self.messages.copy()

    def clear(self) -> None:
        """Clear session history."""
        self.messages.clear()


class InteractiveChat:
    """Boot-to-agent interactive chat interface."""

    GREETING = """
╔════════════════════════════════════════════════════════════════╗
║                    Welcome to AegisOS AI Shell                 ║
║                                                                ║
║  Your personal OS agent is ready. Type your command or question║
║  Type 'help' for commands, 'exit' or 'quit' to leave.         ║
╚════════════════════════════════════════════════════════════════╝
"""

    HELP_TEXT = """
Available commands:
  help              - Show this help message
  status            - Show system/agent status
  models            - List available AI models
  memory <query>    - Search your memory/docs
  run <command>     - Execute a shell command (with confirmation)
  policy            - Show current security policy
  update            - Check for OS/agent updates
  clear             - Clear chat history
  exit / quit       - Leave the chat

Or just ask me anything! I'm here to help manage your system.
"""

    def __init__(self, daemon_ref: Any = None, llm_runtime: Any = None):
        """Initialize chat interface with optional daemon reference."""
        self.daemon = daemon_ref
        self.llm_runtime = llm_runtime
        self.session: Optional[ChatSession] = None

    def start_session(self, session_id: Optional[str] = None) -> ChatSession:
        """Start a new chat session."""
        session_id = session_id or f"session_{id(self)}"
        self.session = ChatSession(session_id)
        return self.session

    def process_input(self, user_input: str) -> str:
        """Process user input and return response."""
        if not self.session:
            return "Error: No active session. Call start_session() first."

        user_input = user_input.strip()
        if not user_input:
            return ""

        # Add to history
        self.session.add_message("user", user_input)

        # Built-in commands
        if user_input.lower() in ("exit", "quit"):
            self.session.active = False
            return "Goodbye! Your session is saved."

        if user_input.lower() == "help":
            return self.HELP_TEXT

        if user_input.lower() == "clear":
            self.session.clear()
            return "Chat history cleared."

        if user_input.lower() == "status":
            return self._get_status()

        if user_input.lower() == "models":
            return self._list_models()

        if user_input.lower() == "policy":
            return self._get_policy()

        if user_input.lower() == "update":
            return self._check_updates()

        if user_input.lower().startswith("memory "):
            query = user_input[7:].strip()
            return self._search_memory(query)

        if user_input.lower().startswith("run "):
            cmd = user_input[4:].strip()
            return self._run_command(cmd)

        # Default: pass to AI
        response = self._ai_response(user_input)
        self.session.add_message("assistant", response)
        return response

    def _get_status(self) -> str:
        """Get daemon status."""
        if not self.daemon:
            return "Daemon not available."
        try:
            status = self.daemon.get_status()
            mode = status.get("mode", "UNKNOWN")
            return f"Agent Status: {mode}\nReady to assist."
        except Exception as e:
            logger.error("Error getting status: %s", e)
            return "Status unavailable."

    def _list_models(self) -> str:
        """List available models."""
        if not self.daemon:
            return "Model list unavailable (daemon not available)."
        try:
            from .llm.model_manager import ModelManager
            mgr = ModelManager()
            models = mgr.list_models()
            active = mgr.get_active_model()
            if not models:
                return "No models registered."
            lines = ["Available models:"]
            for m in models:
                marker = "✓ " if m.get("active") else "  "
                lines.append(f"{marker}{m.get('name', 'unknown')}")
            return "\n".join(lines)
        except Exception as e:
            logger.error("Error listing models: %s", e)
            return "Could not list models."

    def _get_policy(self) -> str:
        """Get current policy profile."""
        if not self.daemon:
            return "Policy unavailable."
        try:
            policy = self.daemon.orchestrator.policy
            if hasattr(policy, 'get_profile'):
                profile = policy.get_profile()
                return f"Current Policy Profile: {profile.get('profile', 'unknown')}"
            return "Policy not available."
        except Exception as e:
            logger.error("Error getting policy: %s", e)
            return "Could not retrieve policy."

    def _check_updates(self) -> str:
        """Check for updates."""
        try:
            from .update_manager import UpdateManager
            mgr = UpdateManager()
            status = mgr.status()
            pending = status.get("pending_updates", [])
            if not pending:
                return "All components are up to date."
            lines = ["Available updates:"]
            for update in pending:
                component = update.get("component", "unknown")
                version = update.get("available_version", "?")
                lines.append(f"  • {component} → {version}")
            return "\n".join(lines)
        except Exception as e:
            logger.error("Error checking updates: %s", e)
            return "Could not check updates."

    def _search_memory(self, query: str) -> str:
        """Search memory for docs/notes."""
        if not self.daemon:
            return "Memory unavailable."
        try:
            results = self.daemon.memory_store.search(query, top_k=3)
            if not results:
                return f"No results found for '{query}'."
            lines = [f"Found {len(results)} result(s):"]
            for i, r in enumerate(results, 1):
                text = r.get("text", "")[:100]
                lines.append(f"{i}. {text}...")
            return "\n".join(lines)
        except Exception as e:
            logger.error("Error searching memory: %s", e)
            return "Memory search failed."

    def _run_command(self, cmd: str) -> str:
        """Run a shell command (with caution)."""
        # This is a placeholder for safety; real implementation would need
        # explicit daemon support and careful validation
        return f"Command execution not yet available via chat. Use systemd or direct API.\n(Requested: {cmd})"

    def _get_policy(self) -> str:
        """Get current policy info."""
        if not self.daemon:
            return "Policy unavailable."
        try:
            policy = self.daemon.orchestrator.policy
            if hasattr(policy, 'get_profile'):
                profile_info = policy.get_profile()
                return f"Active Policy: {profile_info.get('profile', 'unknown')}\nAutonomy: enabled" if profile_info else "Policy unknown"
            return "Policy system unavailable."
        except Exception as e:
            logger.error("Error getting policy: %s", e)
            return "Could not retrieve policy."

    def _ai_response(self, query: str) -> str:
        """Generate AI response to user query."""
        if not self.llm_runtime:
            return "AI runtime not available. Please check /v1/ai/runtime-health endpoint."

        try:
            messages = [
                {
                    "role": "system",
                    "content": "You are AegisOS, a helpful AI system administrator assistant. Keep responses concise and actionable.",
                },
                {"role": "user", "content": query},
            ]
            response = self.llm_runtime.generate(messages, temperature=0.5, max_tokens=256)
            return response
        except Exception as e:
            logger.error("AI generation failed: %s", e)
            return f"I encountered an issue: {str(e)}. Try checking system status or restarting the LLM runtime."

    @staticmethod
    def print_greeting() -> None:
        """Print welcome message to stdout."""
        print(InteractiveChat.GREETING)

    @staticmethod
    def run_interactive_loop(chat: InteractiveChat) -> None:
        """Run interactive chat loop (for CLI use)."""
        chat.start_session()
        chat.print_greeting()

        try:
            while chat.session and chat.session.active:
                try:
                    user_input = input("you> ")
                    response = chat.process_input(user_input)
                    if response:
                        print(f"aegis> {response}\n")
                except EOFError:
                    print("\nGoodbye!")
                    break
                except KeyboardInterrupt:
                    print("\n(Chat interrupted. Type 'exit' to quit.)")
        except Exception as e:
            logger.exception("Chat loop error: %s", e)
