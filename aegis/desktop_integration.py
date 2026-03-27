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
            "paths": {
                "autostart_desktop": str(paths.autostart_desktop),
                "launcher_desktop": str(paths.launcher_desktop),
                "nautilus_script": str(paths.nautilus_script),
                "helper_script": str(paths.helper_script),
                "shell_rc": str(paths.shell_rc),
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
