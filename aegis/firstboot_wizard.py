"""Interactive first-boot wizard for AegisOS setup."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class FirstBootWizard:
    """Guide users through initial AegisOS setup."""

    STATE_FILE_ENV = "AEGIS_FIRSTBOOT_STATE"
    DEFAULT_STATE_PATH = Path("~/.aegis/firstboot_state.json").expanduser()

    def __init__(self, state_path: Optional[Path | str] = None):
        """Initialize wizard with optional custom state path."""
        if state_path:
            self.state_path = Path(state_path)
        else:
            self.state_path = self.DEFAULT_STATE_PATH

        self.state: Dict[str, Any] = self._load_state()
        self.completed = self.state.get("completed", False)
        self.responses: Dict[str, Any] = self.state.get("responses", {})

    def _load_state(self) -> Dict[str, Any]:
        """Load persistent state from disk."""
        if self.state_path.exists():
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Could not load firstboot state: %s", e)
        return {"completed": False, "responses": {}}

    def _save_state(self) -> None:
        """Save state to disk."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state["completed"] = self.completed
        self.state["responses"] = self.responses
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error("Could not save firstboot state: %s", e)

    def should_run(self) -> bool:
        """Check if first-boot wizard should run."""
        return not self.completed

    def run_welcome(self) -> bool:
        """Show welcome screen and get agreement."""
        print("""
╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║               Welcome to AegisOS First Boot Setup              ║
║                                                                ║
║         Your personal AI-native operating system               ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝

This wizard will help you configure AegisOS for your system.

Configuration includes:
  • Selecting an AI model for local inference
  • Setting security policy preferences
  • Enabling optional integrations
  • Creating your personal memory store

All settings can be changed later via the chat interface or API.
""")
        response = input("Ready to begin? (yes/no): ").strip().lower()
        if response not in ("yes", "y"):
            print("Setup cancelled. You can run this wizard again with: aegis-firstboot")
            return False
        return True

    def ask_model_selection(self) -> Optional[str]:
        """Ask user to select or confirm AI model."""
        print("\n" + "=" * 64)
        print("AI Model Selection")
        print("=" * 64)
        print("""
AegisOS runs AI models locally on your hardware.

Available model options:
  1. Lightweight (3-7B params)  - Faster, lower RAM, less accurate
  2. Balanced (7-13B params)    - Good speed/accuracy trade-off
  3. Large (13B+ params)        - Most accurate, requires more resources

Which model class interests you? (1-3, or 'skip' to configure later): """)

        choice = input().strip().lower()
        if choice == "skip":
            self.responses["model_selection"] = "deferred"
            return None

        model_map = {
            "1": "lightweight",
            "2": "balanced",
            "3": "large",
            "lightweight": "lightweight",
            "balanced": "balanced",
            "large": "large",
        }

        selected = model_map.get(choice)
        if not selected:
            print("Invalid choice. Deferring model selection.")
            self.responses["model_selection"] = "deferred"
            return None

        self.responses["model_selection"] = selected
        print(f"✓ Model class '{selected}' selected.")
        return selected

    def ask_policy_profile(self) -> Optional[str]:
        """Ask user to select security policy profile."""
        print("\n" + "=" * 64)
        print("Security Policy Profile")
        print("=" * 64)
        print("""
AegisOS enforces a security policy to protect your system.

Available profiles:
  1. Strict   - Maximum protection; requires approval for most actions
  2. Balanced - Default; actions approved based on trust and risk
  3. Open     - Permissive; agent has broad autonomy

Which profile do you prefer? (1-3, or 'skip'): """)

        choice = input().strip().lower()
        if choice == "skip":
            self.responses["security_profile"] = "balanced"
            print("✓ Using default 'balanced' profile.")
            return "balanced"

        profile_map = {
            "1": "strict",
            "2": "balanced",
            "3": "open",
            "strict": "strict",
            "balanced": "balanced",
            "open": "open",
        }

        selected = profile_map.get(choice)
        if not selected:
            print("Invalid choice. Using 'balanced' profile.")
            selected = "balanced"

        self.responses["security_profile"] = selected
        print(f"✓ Security profile '{selected}' selected.")
        return selected

    def ask_voice_enable(self) -> bool:
        """Ask if user wants voice interface enabled."""
        print("\n" + "=" * 64)
        print("Voice Interface")
        print("=" * 64)
        print("""
AegisOS includes a voice-first interface for hands-free control.

Enable voice interface on boot? (yes/no, or 'skip'): """)

        response = input().strip().lower()
        if response == "skip":
            self.responses["voice_enabled"] = False
            return False

        enabled = response in ("yes", "y")
        self.responses["voice_enabled"] = enabled
        print(f"✓ Voice interface {'enabled' if enabled else 'disabled'}.")
        return enabled

    def ask_memory_integration(self) -> bool:
        """Ask about memory/context integration."""
        print("\n" + "=" * 64)
        print("Memory & Context")
        print("=" * 64)
        print("""
AegisOS can build a personal memory of your preferences, files, and habits
to provide more personalized assistance.

Enable memory integration? (yes/no, or 'skip'): """)

        response = input().strip().lower()
        if response == "skip":
            self.responses["memory_enabled"] = True  # Default on
            return True

        enabled = response in ("yes", "y")
        self.responses["memory_enabled"] = enabled
        print(f"✓ Memory integration {'enabled' if enabled else 'disabled'}.")
        return enabled

    def show_summary(self) -> None:
        """Show summary of choices and next steps."""
        print("\n" + "=" * 64)
        print("Setup Complete!")
        print("=" * 64)
        print("""
🎉 AegisOS is configured and ready to use.

Your configuration:
  Model:           {model}
  Security Policy: {policy}
  Voice Interface: {voice}
  Memory:          {memory}

What's next?
  • Start the chat:  aegis-chat
  • View status:     aegis status
  • Check API docs:  http://localhost:8000/docs
  • Enable services: systemctl --user enable aegis

Questions? Visit the AegisOS docs or ask the agent!
""".format(
            model=self.responses.get("model_selection", "deferred"),
            policy=self.responses.get("security_profile", "balanced"),
            voice="enabled" if self.responses.get("voice_enabled") else "disabled",
            memory="enabled" if self.responses.get("memory_enabled") else "disabled",
        ))

    def run_interactive(self) -> bool:
        """Run full interactive wizard."""
        if not self.should_run():
            print("First-boot setup already completed.")
            return True

        # Show welcome
        if not self.run_welcome():
            return False

        # Ask questions
        self.ask_model_selection()
        self.ask_policy_profile()
        self.ask_voice_enable()
        self.ask_memory_integration()

        # Show summary
        self.show_summary()

        # Mark as complete
        self.completed = True
        self._save_state()

        return True

    def get_responses(self) -> Dict[str, Any]:
        """Get all wizard responses."""
        return self.responses.copy()
