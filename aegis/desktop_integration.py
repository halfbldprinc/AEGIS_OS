from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class DesktopIntegrationPaths:
    autostart_desktop: Path
    launcher_desktop: Path
    nautilus_script: Path
    helper_script: Path
    shell_rc: Path
    widget_launcher_desktop: Path
    widget_autostart_desktop: Path
    widget_script: Path


class DesktopIntegrationManager:
    """Manages desktop-native hooks for launcher, file manager, and terminal usage."""

    def __init__(self, api_base_url: str = "http://127.0.0.1:8000"):
        self.api_base_url = api_base_url.rstrip("/")

    @staticmethod
    def _paths_for_home(home_dir: str | None = None) -> DesktopIntegrationPaths:
        home = Path(home_dir).expanduser() if home_dir else Path.home()
        return DesktopIntegrationPaths(
            autostart_desktop=Path("/etc/xdg/autostart/aegis-text-fallback.desktop"),
            launcher_desktop=home / ".local/share/applications/aegisos-overlay.desktop",
            nautilus_script=home / ".local/share/nautilus/scripts/AegisOS Ask Agent",
            helper_script=home / ".local/bin/aegis-ask",
            shell_rc=home / ".bashrc",
            widget_launcher_desktop=home / ".local/share/applications/aegisos-widget.desktop",
            widget_autostart_desktop=home / ".config/autostart/aegisos-widget.desktop",
            widget_script=home / ".local/bin/aegis-widget",
        )

    def status(self, home_dir: str | None = None) -> Dict[str, Any]:
        paths = self._paths_for_home(home_dir)
        shell_alias = False
        if paths.shell_rc.exists():
            text = paths.shell_rc.read_text(encoding="utf-8", errors="ignore")
            shell_alias = "aegis-ask" in text

        return {
            "autostart_installed": paths.autostart_desktop.exists(),
            "launcher_installed": paths.launcher_desktop.exists(),
            "file_manager_action_installed": paths.nautilus_script.exists(),
            "terminal_alias_installed": shell_alias,
            "helper_script_installed": paths.helper_script.exists(),
            "widget_launcher_installed": paths.widget_launcher_desktop.exists(),
            "widget_autostart_installed": paths.widget_autostart_desktop.exists(),
            "widget_script_installed": paths.widget_script.exists(),
            "paths": {
                "autostart_desktop": str(paths.autostart_desktop),
                "launcher_desktop": str(paths.launcher_desktop),
                "nautilus_script": str(paths.nautilus_script),
                "helper_script": str(paths.helper_script),
                "shell_rc": str(paths.shell_rc),
                "widget_launcher_desktop": str(paths.widget_launcher_desktop),
                "widget_autostart_desktop": str(paths.widget_autostart_desktop),
                "widget_script": str(paths.widget_script),
            },
        }

    def widget_status(self, home_dir: str | None = None) -> Dict[str, Any]:
        paths = self._paths_for_home(home_dir)
        return {
            "widget_launcher_installed": paths.widget_launcher_desktop.exists(),
            "widget_autostart_installed": paths.widget_autostart_desktop.exists(),
            "widget_script_installed": paths.widget_script.exists(),
            "paths": {
                "widget_launcher_desktop": str(paths.widget_launcher_desktop),
                "widget_autostart_desktop": str(paths.widget_autostart_desktop),
                "widget_script": str(paths.widget_script),
            },
        }

    def install_user_hooks(self, home_dir: str | None = None, dry_run: bool = False) -> Dict[str, Any]:
        paths = self._paths_for_home(home_dir)

        helper_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "if [[ $# -lt 1 ]]; then\n"
            "  echo \"Usage: aegis-ask <instruction>\" >&2\n"
            "  exit 1\n"
            "fi\n"
            "instruction=\"$*\"\n"
            "curl -sS -X POST "
            + f"{self.api_base_url}/v1/process-and-execute"
            + " -H 'Content-Type: application/json' "
            + "-d \"{\\\"text\\\": \\\"${instruction//\\\"/\\\\\\\"}\\\"}\"\n"
        )

        launcher_desktop = (
            "[Desktop Entry]\n"
            "Version=1.0\n"
            "Type=Application\n"
            "Name=AegisOS Assistant\n"
            "Comment=Run AegisOS text assistant overlay\n"
            "Exec=python3 -m aegis.cli agent text-fallback\n"
            "Terminal=false\n"
            "Categories=Utility;\n"
        )

        nautilus_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "path=\"${NAUTILUS_SCRIPT_SELECTED_FILE_PATHS%%$'\\n'*}\"\n"
            "if [[ -z \"${path:-}\" ]]; then\n"
            "  exit 0\n"
            "fi\n"
            "aegis-ask \"summarize file ${path}\"\n"
        )

        alias_line = "alias aegis-ask='$HOME/.local/bin/aegis-ask'"

        if dry_run:
            return {
                "status": "planned",
                "files": {
                    "helper_script": str(paths.helper_script),
                    "launcher_desktop": str(paths.launcher_desktop),
                    "nautilus_script": str(paths.nautilus_script),
                    "shell_rc": str(paths.shell_rc),
                },
            }

        paths.helper_script.parent.mkdir(parents=True, exist_ok=True)
        paths.launcher_desktop.parent.mkdir(parents=True, exist_ok=True)
        paths.nautilus_script.parent.mkdir(parents=True, exist_ok=True)
        paths.shell_rc.parent.mkdir(parents=True, exist_ok=True)

        paths.helper_script.write_text(helper_script, encoding="utf-8")
        paths.helper_script.chmod(0o755)

        paths.launcher_desktop.write_text(launcher_desktop, encoding="utf-8")
        paths.nautilus_script.write_text(nautilus_script, encoding="utf-8")
        paths.nautilus_script.chmod(0o755)

        shell_text = ""
        if paths.shell_rc.exists():
            shell_text = paths.shell_rc.read_text(encoding="utf-8", errors="ignore")
        if alias_line not in shell_text:
            with paths.shell_rc.open("a", encoding="utf-8") as f:
                if shell_text and not shell_text.endswith("\n"):
                    f.write("\n")
                f.write(alias_line + "\n")

        return {"status": "installed", "result": self.status(home_dir=home_dir)}

    def install_widget(self, home_dir: str | None = None, dry_run: bool = False, autostart: bool = True) -> Dict[str, Any]:
        paths = self._paths_for_home(home_dir)

        widget_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "exec python3 -m aegis.ui.chat_widget\n"
        )

        widget_desktop = (
            "[Desktop Entry]\n"
            "Version=1.0\n"
            "Type=Application\n"
            "Name=AegisOS Widget\n"
            "Comment=Always-on desktop chat widget\n"
            f"Exec={paths.widget_script}\n"
            "Terminal=false\n"
            "Categories=Utility;\n"
            "X-GNOME-Autostart-enabled=true\n"
        )

        if dry_run:
            return {
                "status": "planned",
                "autostart": autostart,
                "files": {
                    "widget_script": str(paths.widget_script),
                    "widget_launcher_desktop": str(paths.widget_launcher_desktop),
                    "widget_autostart_desktop": str(paths.widget_autostart_desktop),
                },
            }

        paths.widget_script.parent.mkdir(parents=True, exist_ok=True)
        paths.widget_launcher_desktop.parent.mkdir(parents=True, exist_ok=True)
        paths.widget_autostart_desktop.parent.mkdir(parents=True, exist_ok=True)

        paths.widget_script.write_text(widget_script, encoding="utf-8")
        paths.widget_script.chmod(0o755)

        paths.widget_launcher_desktop.write_text(widget_desktop, encoding="utf-8")
        if autostart:
            paths.widget_autostart_desktop.write_text(widget_desktop, encoding="utf-8")
        elif paths.widget_autostart_desktop.exists():
            paths.widget_autostart_desktop.unlink()

        return {"status": "installed", "autostart": autostart, "result": self.widget_status(home_dir=home_dir)}
