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
    control_panel_launcher_desktop: Path
    control_panel_script: Path
    launcher_script: Path
    quick_launcher_desktop: Path
    launcher_tray_script: Path
    launcher_toggle_script: Path
    launcher_tray_autostart_desktop: Path
    app_action_script: Path
    package_action_script: Path
    system_action_script: Path


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
            control_panel_launcher_desktop=home / ".local/share/applications/aegisos-control-panel.desktop",
            control_panel_script=home / ".local/bin/aegis-control-panel",
            launcher_script=home / ".local/bin/aegis-launcher",
            quick_launcher_desktop=home / ".local/share/applications/aegisos-launcher.desktop",
            launcher_tray_script=home / ".local/bin/aegis-launcher-tray",
            launcher_toggle_script=home / ".local/bin/aegis-launcher-toggle",
            launcher_tray_autostart_desktop=home / ".config/autostart/aegisos-launcher-tray.desktop",
            app_action_script=home / ".local/bin/aegis-launch-app",
            package_action_script=home / ".local/bin/aegis-install-package",
            system_action_script=home / ".local/bin/aegis-system-action",
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
            "control_panel_launcher_installed": paths.control_panel_launcher_desktop.exists(),
            "control_panel_script_installed": paths.control_panel_script.exists(),
            "launcher_script_installed": paths.launcher_script.exists(),
            "launcher_desktop_entry_installed": paths.quick_launcher_desktop.exists(),
            "launcher_tray_script_installed": paths.launcher_tray_script.exists(),
            "launcher_toggle_script_installed": paths.launcher_toggle_script.exists(),
            "launcher_tray_autostart_installed": paths.launcher_tray_autostart_desktop.exists(),
            "app_action_script_installed": paths.app_action_script.exists(),
            "package_action_script_installed": paths.package_action_script.exists(),
            "system_action_script_installed": paths.system_action_script.exists(),
            "paths": {
                "autostart_desktop": str(paths.autostart_desktop),
                "launcher_desktop": str(paths.launcher_desktop),
                "nautilus_script": str(paths.nautilus_script),
                "helper_script": str(paths.helper_script),
                "shell_rc": str(paths.shell_rc),
                "widget_launcher_desktop": str(paths.widget_launcher_desktop),
                "widget_autostart_desktop": str(paths.widget_autostart_desktop),
                "widget_script": str(paths.widget_script),
                "control_panel_launcher_desktop": str(paths.control_panel_launcher_desktop),
                "control_panel_script": str(paths.control_panel_script),
                "launcher_script": str(paths.launcher_script),
                "launcher_desktop": str(paths.quick_launcher_desktop),
                "launcher_tray_script": str(paths.launcher_tray_script),
                "launcher_toggle_script": str(paths.launcher_toggle_script),
                "launcher_tray_autostart_desktop": str(paths.launcher_tray_autostart_desktop),
                "app_action_script": str(paths.app_action_script),
                "package_action_script": str(paths.package_action_script),
                "system_action_script": str(paths.system_action_script),
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

    def control_panel_status(self, home_dir: str | None = None) -> Dict[str, Any]:
        paths = self._paths_for_home(home_dir)
        return {
            "control_panel_launcher_installed": paths.control_panel_launcher_desktop.exists(),
            "control_panel_script_installed": paths.control_panel_script.exists(),
            "launcher_script_installed": paths.launcher_script.exists(),
            "launcher_desktop_entry_installed": paths.quick_launcher_desktop.exists(),
            "launcher_tray_script_installed": paths.launcher_tray_script.exists(),
            "launcher_toggle_script_installed": paths.launcher_toggle_script.exists(),
            "launcher_tray_autostart_installed": paths.launcher_tray_autostart_desktop.exists(),
            "app_action_script_installed": paths.app_action_script.exists(),
            "package_action_script_installed": paths.package_action_script.exists(),
            "system_action_script_installed": paths.system_action_script.exists(),
            "paths": {
                "control_panel_launcher_desktop": str(paths.control_panel_launcher_desktop),
                "control_panel_script": str(paths.control_panel_script),
                "launcher_script": str(paths.launcher_script),
                "launcher_desktop": str(paths.quick_launcher_desktop),
                "launcher_tray_script": str(paths.launcher_tray_script),
                "launcher_toggle_script": str(paths.launcher_toggle_script),
                "launcher_tray_autostart_desktop": str(paths.launcher_tray_autostart_desktop),
                "app_action_script": str(paths.app_action_script),
                "package_action_script": str(paths.package_action_script),
                "system_action_script": str(paths.system_action_script),
            },
        }

    def install_control_panel(self, home_dir: str | None = None, dry_run: bool = False) -> Dict[str, Any]:
        paths = self._paths_for_home(home_dir)

        control_panel_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "exec python3 -m aegis.ui.control_panel\n"
        )

        launcher_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "exec python3 -m aegis.ui.launcher \"$@\"\n"
        )

        launcher_tray_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "exec python3 -m aegis.ui.launcher --tray \"$@\"\n"
        )

        launcher_toggle_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "exec python3 -m aegis.ui.launcher --toggle \"$@\"\n"
        )

        app_action_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "if [[ $# -lt 1 ]]; then\n"
            "  echo \"Usage: aegis-launch-app <application name>\" >&2\n"
            "  exit 1\n"
            "fi\n"
            "target=\"$*\"\n"
            "instruction=\"launch application ${target}\"\n"
            "escaped=${instruction//\"/\\\\\"}\n"
            "curl -sS -X POST "
            + f"{self.api_base_url}/v1/process-and-execute"
            + " -H 'Content-Type: application/json' "
            + "-d \"{\\\"text\\\":\\\"${escaped}\\\",\\\"allow_failure\\\":false}\"\n"
        )

        package_action_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "if [[ $# -lt 1 ]]; then\n"
            "  echo \"Usage: aegis-install-package <package name>\" >&2\n"
            "  exit 1\n"
            "fi\n"
            "target=\"$*\"\n"
            "instruction=\"install package ${target}\"\n"
            "escaped=${instruction//\"/\\\\\"}\n"
            "curl -sS -X POST "
            + f"{self.api_base_url}/v1/process-and-execute"
            + " -H 'Content-Type: application/json' "
            + "-d \"{\\\"text\\\":\\\"${escaped}\\\",\\\"allow_failure\\\":false}\"\n"
        )

        system_action_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "if [[ $# -lt 1 ]]; then\n"
            "  echo \"Usage: aegis-system-action <action phrase>\" >&2\n"
            "  exit 1\n"
            "fi\n"
            "target=\"$*\"\n"
            "instruction=\"perform system action ${target}\"\n"
            "escaped=${instruction//\"/\\\\\"}\n"
            "curl -sS -X POST "
            + f"{self.api_base_url}/v1/process-and-execute"
            + " -H 'Content-Type: application/json' "
            + "-d \"{\\\"text\\\":\\\"${escaped}\\\",\\\"allow_failure\\\":false}\"\n"
        )

        control_panel_desktop = (
            "[Desktop Entry]\n"
            "Version=1.0\n"
            "Type=Application\n"
            "Name=AegisOS Control Panel\n"
            "Comment=Open the AegisOS control panel dashboard\n"
            f"Exec={paths.control_panel_script}\n"
            "Terminal=false\n"
            "Categories=Utility;System;\n"
        )

        launcher_desktop = (
            "[Desktop Entry]\n"
            "Version=1.0\n"
            "Type=Application\n"
            "Name=AegisOS Launcher\n"
            "Comment=Quick natural-language command prompt for AegisOS\n"
            f"Exec={paths.launcher_script}\n"
            "Terminal=false\n"
            "Categories=Utility;System;\n"
        )

        launcher_tray_autostart_desktop = (
            "[Desktop Entry]\n"
            "Version=1.0\n"
            "Type=Application\n"
            "Name=AegisOS Launcher Tray\n"
            "Comment=Persistent background launcher for global hotkey toggling\n"
            f"Exec={paths.launcher_tray_script}\n"
            "Terminal=false\n"
            "Categories=Utility;System;\n"
            "X-GNOME-Autostart-enabled=true\n"
        )

        if dry_run:
            return {
                "status": "planned",
                "files": {
                    "control_panel_script": str(paths.control_panel_script),
                    "control_panel_launcher_desktop": str(paths.control_panel_launcher_desktop),
                    "launcher_script": str(paths.launcher_script),
                    "launcher_desktop": str(paths.quick_launcher_desktop),
                    "launcher_tray_script": str(paths.launcher_tray_script),
                    "launcher_toggle_script": str(paths.launcher_toggle_script),
                    "launcher_tray_autostart_desktop": str(paths.launcher_tray_autostart_desktop),
                    "app_action_script": str(paths.app_action_script),
                    "package_action_script": str(paths.package_action_script),
                    "system_action_script": str(paths.system_action_script),
                },
            }

        paths.control_panel_script.parent.mkdir(parents=True, exist_ok=True)
        paths.control_panel_launcher_desktop.parent.mkdir(parents=True, exist_ok=True)
        paths.launcher_script.parent.mkdir(parents=True, exist_ok=True)
        paths.quick_launcher_desktop.parent.mkdir(parents=True, exist_ok=True)
        paths.launcher_tray_script.parent.mkdir(parents=True, exist_ok=True)
        paths.launcher_toggle_script.parent.mkdir(parents=True, exist_ok=True)
        paths.launcher_tray_autostart_desktop.parent.mkdir(parents=True, exist_ok=True)
        paths.app_action_script.parent.mkdir(parents=True, exist_ok=True)
        paths.package_action_script.parent.mkdir(parents=True, exist_ok=True)
        paths.system_action_script.parent.mkdir(parents=True, exist_ok=True)

        paths.control_panel_script.write_text(control_panel_script, encoding="utf-8")
        paths.control_panel_script.chmod(0o755)
        paths.control_panel_launcher_desktop.write_text(control_panel_desktop, encoding="utf-8")

        paths.launcher_script.write_text(launcher_script, encoding="utf-8")
        paths.launcher_script.chmod(0o755)
        paths.quick_launcher_desktop.write_text(launcher_desktop, encoding="utf-8")
        paths.launcher_tray_script.write_text(launcher_tray_script, encoding="utf-8")
        paths.launcher_tray_script.chmod(0o755)
        paths.launcher_toggle_script.write_text(launcher_toggle_script, encoding="utf-8")
        paths.launcher_toggle_script.chmod(0o755)
        paths.launcher_tray_autostart_desktop.write_text(launcher_tray_autostart_desktop, encoding="utf-8")

        paths.app_action_script.write_text(app_action_script, encoding="utf-8")
        paths.app_action_script.chmod(0o755)
        paths.package_action_script.write_text(package_action_script, encoding="utf-8")
        paths.package_action_script.chmod(0o755)
        paths.system_action_script.write_text(system_action_script, encoding="utf-8")
        paths.system_action_script.chmod(0o755)

        return {"status": "installed", "result": self.control_panel_status(home_dir=home_dir)}
