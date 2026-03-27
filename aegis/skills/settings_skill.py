import shutil
import re
import subprocess
import sys
from typing import Any, Dict, List

from ..result import SkillResult
from ..skill import Skill


class SettingsSkill(Skill):
    name = "settings"
    tier = 2

    def __init__(self):
        self._last_snapshot: Dict[str, Any] | None = None

    def execute(self, action: str, params: Dict[str, Any]) -> SkillResult:
        if action == "snapshot":
            return self.snapshot()
        if action == "revert":
            return self.revert()
        if action == "volume":
            return self.set_volume(params.get("level"))
        if action == "brightness":
            return self.set_brightness(params.get("level"))
        if action == "dnd":
            return self.set_dnd(params.get("enabled"))
        if action == "network":
            return self.set_network(params.get("enabled"))

        return SkillResult.fail(f"Unsupported action: {action}")

    def get_permissions(self) -> List[str]:
        return ["settings"]

    def snapshot(self) -> SkillResult:
        snapshot = {
            "volume": self.get_volume_level(),
            "brightness": self.get_brightness_level(),
            "network": self.get_network_state(),
            "dnd": self.get_dnd_state(),
        }
        self._last_snapshot = snapshot
        return SkillResult.ok({"snapshot": snapshot})

    def revert(self) -> SkillResult:
        if not self._last_snapshot:
            return SkillResult.fail("No snapshot available for revert")

        errors: List[str] = []
        snap = self._last_snapshot

        if snap.get("volume") is not None:
            r = self.set_volume(snap["volume"])
            if not r.success:
                errors.append(f"volume: {r.error}")

        if snap.get("brightness") is not None:
            r = self.set_brightness(snap["brightness"])
            if not r.success:
                errors.append(f"brightness: {r.error}")

        if snap.get("network") is not None:
            r = self.set_network(snap["network"])
            if not r.success:
                errors.append(f"network: {r.error}")

        if snap.get("dnd") is not None:
            r = self.set_dnd(snap["dnd"])
            if not r.success:
                errors.append(f"dnd: {r.error}")

        if errors:
            return SkillResult.fail("Revert failed: " + "; ".join(errors))

        return SkillResult.ok({"reverted": True, "snapshot": snap})

    def get_volume_level(self) -> Any:
        if sys.platform == "darwin":
            result = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                try:
                    return int(result.stdout.strip())
                except ValueError:
                    return None
            return None

        if sys.platform.startswith("linux") and shutil.which("pactl"):
            result = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                match = re.search(r"(\d+)%", result.stdout)
                if match:
                    return int(match.group(1))
        return None

    def get_brightness_level(self) -> Any:
        if sys.platform == "darwin" and shutil.which("brightness"):
            result = subprocess.run(["brightness", "-l"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                match = re.search(r"brightness\s+([0-9.]+)", result.stdout)
                if match:
                    return int(float(match.group(1)) * 100)

        if sys.platform.startswith("linux") and shutil.which("xbacklight"):
            result = subprocess.run(["xbacklight", "-get"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                try:
                    return int(float(result.stdout.strip()))
                except ValueError:
                    return None
        return None

    def get_network_state(self) -> Any:
        if sys.platform == "darwin" and shutil.which("networksetup"):
            result = subprocess.run(["networksetup", "-getnetworkserviceenabled", "Wi-Fi"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                val = result.stdout.strip().lower()
                return "enabled" in val

        if sys.platform.startswith("linux") and shutil.which("nmcli"):
            result = subprocess.run(["nmcli", "radio", "wifi"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                val = result.stdout.strip().lower()
                return val == "enabled"
        return None

    def get_dnd_state(self) -> Any:
        if sys.platform.startswith("linux") and shutil.which("gsettings"):
            result = subprocess.run(["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                val = result.stdout.strip().lower()
                return val == "true"
        # macOS dnd state querying varies by version and is not consistently exposed via stable CLI.
        return None

    def set_volume(self, level: Any) -> SkillResult:
        if level is None:
            return SkillResult.fail("'level' parameter is required")
        try:
            level = int(level)
            level = max(0, min(level, 100))
        except ValueError:
            return SkillResult.fail("Volume level must be an integer")

        if sys.platform == "darwin":
            cmd = ["osascript", "-e", f'set volume output volume {level}' ]
            return self._run_cmd(cmd)

        if sys.platform.startswith("linux"):
            if not shutil.which("pactl"):
                return SkillResult.fail("pactl not installed")
            return self._run_cmd(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"]) 

        return SkillResult.fail("Unsupported OS for volume settings")

    def set_brightness(self, level: Any) -> SkillResult:
        if level is None:
            return SkillResult.fail("'level' parameter is required")
        try:
            level = int(level)
            level = max(0, min(level, 100))
        except ValueError:
            return SkillResult.fail("Brightness level must be an integer")

        if sys.platform == "darwin":
            if not shutil.which("brightness"):
                return SkillResult.fail("brightness tool is required on macOS")
            return self._run_cmd(["brightness", f"{level / 100:.2f}"])

        if sys.platform.startswith("linux"):
            if not shutil.which("xbacklight"):
                return SkillResult.fail("xbacklight not installed")
            return self._run_cmd(["xbacklight", "-set", str(level)])

        return SkillResult.fail("Unsupported OS for brightness settings")

    def set_dnd(self, enabled: Any) -> SkillResult:
        if enabled is None:
            return SkillResult.fail("'enabled' parameter is required")

        enabled_flag = str(enabled).lower() in ("true", "1", "yes", "on")

        if sys.platform == "darwin":
            val = "true" if enabled_flag else "false"
            return self._run_cmd(["osascript", "-e", f'set dnd enabled to {val}' ])

        if sys.platform.startswith("linux"):
            if not shutil.which("gsettings"):
                return SkillResult.fail("gsettings not installed")
            val = "true" if enabled_flag else "false"
            return self._run_cmd(["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", val])

        return SkillResult.fail("Unsupported OS for DND settings")

    def set_network(self, enabled: Any) -> SkillResult:
        if enabled is None:
            return SkillResult.fail("'enabled' parameter is required")

        enabled_flag = str(enabled).lower() in ("true", "1", "yes", "on")

        if sys.platform == "darwin":
            if not shutil.which("networksetup"):
                return SkillResult.fail("networksetup not installed")
            cmd = ["networksetup", "-setnetworkserviceenabled", "Wi-Fi", "on" if enabled_flag else "off"]
            return self._run_cmd(cmd)

        if sys.platform.startswith("linux"):
            if not shutil.which("nmcli"):
                return SkillResult.fail("nmcli not installed")
            state = "on" if enabled_flag else "off"
            return self._run_cmd(["nmcli", "radio", "wifi", state])

        return SkillResult.fail("Unsupported OS for network settings")

    def _run_cmd(self, cmd: List[str]) -> SkillResult:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return SkillResult.fail(result.stderr.strip() or "Command failed")
            return SkillResult.ok({"stdout": result.stdout.strip(), "command": " ".join(cmd)})
        except Exception as exc:
            return SkillResult.fail(str(exc))
