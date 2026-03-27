import shutil
import subprocess
import sys
from typing import Any, Dict, List

from ..result import SkillResult
from ..skill import Skill


class OSControlSkill(Skill):
    name = "os_control"
    tier = 2

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action == "launch":
            return self.launch_app(params.get("app"), params.get("args", []))
        if action == "close":
            return self.close_app(params.get("app"))
        if action == "focus":
            return self.focus_app(params.get("app"))
        if action == "clipboard_set":
            return self.clipboard_set(params.get("text"))
        if action == "clipboard_get":
            return self.clipboard_get()
        if action == "notify":
            return self.notify(params.get("title"), params.get("message"))

        return SkillResult.fail(f"Unsupported action: {action}")

    def get_permissions(self) -> List[str]:
        return ["launch", "close", "focus", "clipboard", "notify"]

    def _command(self, cmd: List[str], check: bool = False) -> SkillResult:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=check)
            return SkillResult.ok({"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode})
        except subprocess.CalledProcessError as e:
            return SkillResult.fail(f"Command failed: {e.stderr.strip()}")
        except FileNotFoundError:
            return SkillResult.fail(f"Command not found: {cmd[0]}")
        except Exception as e:
            return SkillResult.fail(str(e))

    def launch_app(self, app: str, args: List[str]) -> SkillResult:
        if not app:
            return SkillResult.fail("'app' parameter is required")

        if sys.platform == "darwin":
            cmd = ["open", "-a", app] + args
            return self._command(cmd)
        elif sys.platform.startswith("linux"):
            cmd = [app] + args
            return self._command(cmd)
        else:
            return SkillResult.fail("Unsupported OS for launch action")

    def close_app(self, app: str) -> SkillResult:
        if not app:
            return SkillResult.fail("'app' parameter is required")

        if sys.platform == "darwin":
            return self._command(["osascript", "-e", f'tell application "{app}" to quit'])
        elif sys.platform.startswith("linux"):
            return self._command(["pkill", "-x", app])
        else:
            return SkillResult.fail("Unsupported OS for close action")

    def focus_app(self, app: str) -> SkillResult:
        if not app:
            return SkillResult.fail("'app' parameter is required")

        if sys.platform == "darwin":
            return self._command(["osascript", "-e", f'tell application "{app}" to activate'])
        elif sys.platform.startswith("linux"):
            # On Linux, using wmctrl if available
            if shutil.which("wmctrl"):
                return self._command(["wmctrl", "-a", app])
            return SkillResult.fail("wmctrl is required on Linux for focus operation")
        else:
            return SkillResult.fail("Unsupported OS for focus action")

    def clipboard_set(self, text: str) -> SkillResult:
        if text is None:
            return SkillResult.fail("'text' parameter is required")

        if sys.platform == "darwin":
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
            p.communicate(text)
            return SkillResult.ok({"clipboard": text})

        if sys.platform.startswith("linux"):
            if shutil.which("xclip"):
                p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE, text=True)
                p.communicate(text)
                return SkillResult.ok({"clipboard": text})
            if shutil.which("xsel"):
                p = subprocess.Popen(["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE, text=True)
                p.communicate(text)
                return SkillResult.ok({"clipboard": text})
            return SkillResult.fail("xclip or xsel is required for clipboard operations on Linux")

        return SkillResult.fail("Unsupported OS for clipboard operations")

    def clipboard_get(self) -> SkillResult:
        if sys.platform == "darwin":
            result = subprocess.run(["pbpaste"], capture_output=True, text=True)
            return SkillResult.ok({"clipboard": result.stdout})

        if sys.platform.startswith("linux"):
            if shutil.which("xclip"):
                result = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True)
                return SkillResult.ok({"clipboard": result.stdout})
            if shutil.which("xsel"):
                result = subprocess.run(["xsel", "--clipboard", "--output"], capture_output=True, text=True)
                return SkillResult.ok({"clipboard": result.stdout})
            return SkillResult.fail("xclip or xsel is required for clipboard operations on Linux")

        return SkillResult.fail("Unsupported OS for clipboard operations")

    def get_risk(self, action: str) -> str:
        if action in ("launch", "close", "focus", "clipboard_set"):
            return "high"
        if action == "notify":
            return "medium"
        return "low"

    def notify(self, title: str, message: str) -> SkillResult:
        if not title or not message:
            return SkillResult.fail("'title' and 'message' parameters are required")

        if sys.platform == "darwin":
            return self._command(["osascript", "-e", f'display notification "{message}" with title "{title}"'])
        if sys.platform.startswith("linux"):
            if shutil.which("notify-send"):
                return self._command(["notify-send", title, message])
            return SkillResult.fail("notify-send is required for notifications on Linux")

        return SkillResult.fail("Unsupported OS for notifications")
