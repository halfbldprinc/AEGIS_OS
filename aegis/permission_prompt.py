import os
import shutil
import subprocess
from typing import Any, Dict, Optional


class LocalPermissionPrompt:
    """Best-effort local permission UI for first-run sensitive actions."""

    def __init__(self) -> None:
        self.mode = os.getenv("AEGIS_PERMISSION_PROMPT_MODE", "auto").strip().lower()

    def _zenity_prompt(self, request: Dict[str, Any]) -> Optional[bool]:
        zenity = shutil.which("zenity")
        if not zenity or not os.getenv("DISPLAY"):
            return None

        text = (
            "AegisOS permission request\n\n"
            f"Skill: {request.get('skill')}\n"
            f"Action: {request.get('action')}\n"
            "\nAllow this action and remember for future executions?"
        )
        completed = subprocess.run(
            [zenity, "--question", "--title=AegisOS Permission", f"--text={text}"],
            check=False,
        )
        return completed.returncode == 0

    def _tty_prompt(self, request: Dict[str, Any]) -> Optional[bool]:
        if not os.isatty(0):
            return None

        prompt = (
            "AegisOS permission request\n"
            f"Skill: {request.get('skill')}\n"
            f"Action: {request.get('action')}\n"
            "Allow and remember?"
        )

        whiptail = shutil.which("whiptail")
        if whiptail:
            completed = subprocess.run(
                [whiptail, "--title", "AegisOS Permission", "--yesno", prompt, "14", "72"],
                check=False,
            )
            return completed.returncode == 0

        dialog = shutil.which("dialog")
        if dialog:
            completed = subprocess.run(
                [dialog, "--title", "AegisOS Permission", "--yesno", prompt, "14", "72"],
                check=False,
            )
            return completed.returncode == 0

        # Fallback plain prompt.
        raw = input(f"{prompt} [y/N]: ").strip().lower()
        return raw in {"y", "yes"}

    def request(self, request: Dict[str, Any]) -> Optional[bool]:
        if self.mode in {"off", "disabled", "0", "false", "no"}:
            return None

        if self.mode in {"zenity", "gui"}:
            return self._zenity_prompt(request)

        if self.mode in {"tty", "cli"}:
            return self._tty_prompt(request)

        # auto mode
        gui_result = self._zenity_prompt(request)
        if gui_result is not None:
            return gui_result

        return self._tty_prompt(request)
