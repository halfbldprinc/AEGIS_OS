"""AegisOS Control Panel desktop app."""

from __future__ import annotations

import json
import os
import subprocess
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .api_client import AegisApiClient, ApiError


class ControlPanelApp:
    def __init__(self, api_base_url: str = "http://127.0.0.1:8000"):
        self.client = AegisApiClient(api_base_url=api_base_url)
        self.activity_offset = 0
        self.pending_rows: List[Dict[str, Any]] = []
        self.pending_row_map: Dict[str, Dict[str, Any]] = {}
        self.pending_update_rows: List[Dict[str, Any]] = []
        self.config_path = Path.home() / ".aegis" / "ui" / "control_panel.json"
        self.ui_config = self._load_ui_config()

        self.root = tk.Tk()
        self.root.title("AEGIS Control Panel")
        self.root.geometry("1120x760+50+50")
        self.root.configure(bg="#0f1724")

        self.status_var = tk.StringVar(value="Connecting...")
        self.command_var = tk.StringVar()
        self.component_var = tk.StringVar(value="agent")

        self._build_layout()
        self._bind_shortcuts()
        self._maybe_run_first_boot_wizard()

    def _load_ui_config(self) -> Dict[str, Any]:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
        return {"first_run_complete": False, "hotkey_configured": False, "desktop_environment": None}

    def _save_ui_config(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self.ui_config, indent=2, sort_keys=True), encoding="utf-8")

    def _detect_desktop_environment(self) -> str:
        current = os.getenv("XDG_CURRENT_DESKTOP", "")
        session = os.getenv("DESKTOP_SESSION", "")
        probe = f"{current}:{session}".lower()
        if "gnome" in probe:
            return "gnome"
        if "kde" in probe or "plasma" in probe:
            return "kde"
        return "unknown"

    def _maybe_run_first_boot_wizard(self) -> None:
        if self.ui_config.get("first_run_complete"):
            return

        self.root.after(300, self._run_first_boot_wizard)

    def _run_first_boot_wizard(self) -> None:
        env = self._detect_desktop_environment()
        self.ui_config["desktop_environment"] = env
        self._save_ui_config()

        wizard = tk.Toplevel(self.root)
        wizard.title("AEGIS First-Run Setup")
        wizard.geometry("720x300+120+120")
        wizard.configure(bg="#0f1724")
        wizard.transient(self.root)
        wizard.grab_set()

        title = tk.Label(
            wizard,
            text="Configure Global Launcher Hotkey",
            bg="#0f1724",
            fg="#f3f7ff",
            font=("Helvetica", 14, "bold"),
        )
        title.pack(anchor="w", padx=16, pady=(16, 6))

        support_text = "Supported desktop detected: " + env.upper() if env in {"gnome", "kde"} else "Desktop auto-setup not supported"
        body = tk.Label(
            wizard,
            text=(
                support_text
                + "\n\nThis setup will:\n"
                "1) install control-panel and launcher scripts\n"
                "2) start persistent launcher tray mode\n"
                "3) configure global hotkey Ctrl+Alt+Space to toggle launcher"
            ),
            justify=tk.LEFT,
            anchor="w",
            bg="#0f1724",
            fg="#c2d3f1",
            font=("Helvetica", 11),
        )
        body.pack(fill=tk.X, padx=16, pady=(0, 12))

        result_var = tk.StringVar(value="Ready")
        result = tk.Label(wizard, textvariable=result_var, bg="#0f1724", fg="#8fb0df", anchor="w")
        result.pack(fill=tk.X, padx=16)

        button_row = tk.Frame(wizard, bg="#0f1724")
        button_row.pack(fill=tk.X, padx=16, pady=16)

        def _finish() -> None:
            self.ui_config["first_run_complete"] = True
            self._save_ui_config()
            wizard.destroy()

        def _run_auto_setup() -> None:
            self.install_desktop_hooks(show_dialogs=False)
            tray_ok = self._start_launcher_tray()
            hotkey_ok, detail = self._configure_global_hotkey(env=env)
            self.ui_config["hotkey_configured"] = bool(hotkey_ok)
            self._save_ui_config()
            result_var.set(f"Auto-setup complete. tray={tray_ok} hotkey={hotkey_ok} ({detail})")

        auto_btn = tk.Button(button_row, text="Run Auto Setup", command=_run_auto_setup, bg="#1f6feb", fg="#ffffff", relief=tk.FLAT)
        auto_btn.pack(side=tk.LEFT)

        skip_btn = tk.Button(button_row, text="Skip", command=_finish)
        skip_btn.pack(side=tk.RIGHT)

        done_btn = tk.Button(button_row, text="Finish", command=_finish)
        done_btn.pack(side=tk.RIGHT, padx=(0, 8))

    def _start_launcher_tray(self) -> bool:
        cmd = ["python3", "-m", "aegis.ui.launcher", "--tray", "--api", self.client.api_base_url]
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except OSError:
            return False

    def _configure_global_hotkey(self, env: str) -> Tuple[bool, str]:
        toggle_script = str(Path.home() / ".local" / "bin" / "aegis-launcher-toggle")
        command = f"{toggle_script}"
        if env == "gnome":
            return self._configure_gnome_hotkey(command=command)
        if env == "kde":
            return self._configure_kde_hotkey(command=command)
        return False, "desktop-not-supported"

    def _configure_gnome_hotkey(self, command: str) -> Tuple[bool, str]:
        key = "org.gnome.settings-daemon.plugins.media-keys"
        custom = f"{key}.custom-keybinding"
        base = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
        binding_path = f"{base}/aegis-launcher/"
        try:
            existing = subprocess.check_output(["gsettings", "get", key, "custom-keybindings"], text=True).strip()
            if existing in {"@as []", "[]"}:
                updated = f"['{binding_path}']"
            elif binding_path in existing:
                updated = existing
            else:
                trimmed = existing.rstrip("]")
                if trimmed.endswith("["):
                    updated = f"['{binding_path}']"
                else:
                    updated = f"{trimmed}, '{binding_path}']"

            subprocess.check_call(["gsettings", "set", key, "custom-keybindings", updated])
            subprocess.check_call(["gsettings", "set", f"{custom}:{binding_path}", "name", "AEGIS Launcher Toggle"])
            subprocess.check_call(["gsettings", "set", f"{custom}:{binding_path}", "command", command])
            subprocess.check_call(["gsettings", "set", f"{custom}:{binding_path}", "binding", "<Primary><Alt>space"])
            return True, "gnome-configured"
        except (OSError, subprocess.CalledProcessError):
            return False, "gnome-config-failed"

    def _configure_kde_hotkey(self, command: str) -> Tuple[bool, str]:
        kwrite = "kwriteconfig6"
        try:
            subprocess.check_call(["which", kwrite], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            kwrite = "kwriteconfig5"

        try:
            subprocess.check_call(
                [kwrite, "--file", "kglobalshortcutsrc", "--group", "AEGISLauncher", "--key", "_k_friendly_name", "AEGIS Launcher"]
            )
            subprocess.check_call(
                [
                    kwrite,
                    "--file",
                    "kglobalshortcutsrc",
                    "--group",
                    "AEGISLauncher",
                    "--key",
                    "toggleLauncher",
                    f"Ctrl+Alt+Space,Ctrl+Alt+Space,{command}",
                ]
            )
            subprocess.run(["qdbus", "org.kde.KWin", "/KWin", "reconfigure"], check=False)
            return True, "kde-configured"
        except (OSError, subprocess.CalledProcessError):
            return False, "kde-config-failed"

    def _build_layout(self) -> None:
        top = tk.Frame(self.root, bg="#0f1724")
        top.pack(fill=tk.X, padx=10, pady=10)

        title = tk.Label(
            top,
            text="AEGIS Control Panel",
            font=("Helvetica", 16, "bold"),
            bg="#0f1724",
            fg="#f3f7ff",
        )
        title.pack(side=tk.LEFT)

        refresh_btn = tk.Button(top, text="Refresh", command=self.refresh_all, bg="#1f6feb", fg="#ffffff", relief=tk.FLAT)
        refresh_btn.pack(side=tk.RIGHT, padx=(8, 0))

        install_hooks_btn = tk.Button(
            top,
            text="Install Desktop Hooks",
            command=self.install_desktop_hooks,
            bg="#2a3345",
            fg="#e8eefc",
            relief=tk.FLAT,
        )
        install_hooks_btn.pack(side=tk.RIGHT)

        status = tk.Label(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            bg="#0f1724",
            fg="#9fb2d7",
            font=("Helvetica", 10),
        )
        status.pack(fill=tk.X, padx=12)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._build_overview_tab()
        self._build_approvals_tab()
        self._build_updates_tab()
        self._build_activity_tab()
        self._build_launcher_tab()

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-Shift-space>", lambda _event: self.focus_command_entry())

    def _build_overview_tab(self) -> None:
        tab = tk.Frame(self.notebook, bg="#111a2b")
        self.notebook.add(tab, text="Overview")

        self.overview_text = scrolledtext.ScrolledText(
            tab,
            bg="#0d1421",
            fg="#dce8ff",
            insertbackground="#dce8ff",
            wrap=tk.WORD,
            font=("Menlo", 10),
        )
        self.overview_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def _build_approvals_tab(self) -> None:
        tab = tk.Frame(self.notebook, bg="#111a2b")
        self.notebook.add(tab, text="Pending Approvals")

        cols = ("plan_id", "step_id", "skill", "action", "status")
        self.approvals_tree = ttk.Treeview(tab, columns=cols, show="headings", height=12)
        for col in cols:
            self.approvals_tree.heading(col, text=col)
            self.approvals_tree.column(col, width=180 if col in {"plan_id", "step_id"} else 140, anchor="w")
        self.approvals_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 4))

        controls = tk.Frame(tab, bg="#111a2b")
        controls.pack(fill=tk.X, padx=10, pady=(4, 10))

        once_btn = tk.Button(controls, text="Approve Once", command=lambda: self.decide_pending("once"))
        always_btn = tk.Button(controls, text="Always Allow", command=lambda: self.decide_pending("always"))
        deny_btn = tk.Button(controls, text="Deny", command=lambda: self.decide_pending("deny"))
        refresh_btn = tk.Button(controls, text="Refresh", command=self.refresh_pending_approvals)

        once_btn.pack(side=tk.LEFT)
        always_btn.pack(side=tk.LEFT, padx=(8, 0))
        deny_btn.pack(side=tk.LEFT, padx=(8, 0))
        refresh_btn.pack(side=tk.RIGHT)

    def _build_updates_tab(self) -> None:
        tab = tk.Frame(self.notebook, bg="#111a2b")
        self.notebook.add(tab, text="Updates")

        current_frame = tk.LabelFrame(tab, text="Current Versions", bg="#111a2b", fg="#f3f7ff")
        current_frame.pack(fill=tk.X, padx=10, pady=10)
        self.current_versions_label = tk.Label(current_frame, text="", anchor="w", justify=tk.LEFT, bg="#111a2b", fg="#dce8ff")
        self.current_versions_label.pack(fill=tk.X, padx=8, pady=8)

        pending_frame = tk.LabelFrame(tab, text="Pending Updates", bg="#111a2b", fg="#f3f7ff")
        pending_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        cols = ("component", "available_version", "channel", "notes")
        self.updates_tree = ttk.Treeview(pending_frame, columns=cols, show="headings", height=10)
        for col in cols:
            self.updates_tree.heading(col, text=col)
            width = 180 if col in {"component", "available_version", "channel"} else 420
            self.updates_tree.column(col, width=width, anchor="w")
        self.updates_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        controls = tk.Frame(tab, bg="#111a2b")
        controls.pack(fill=tk.X, padx=10, pady=(0, 10))

        tk.Label(controls, text="Component", bg="#111a2b", fg="#dce8ff").pack(side=tk.LEFT)
        self.component_combo = ttk.Combobox(controls, textvariable=self.component_var, values=["os", "agent", "model"], width=12)
        self.component_combo.pack(side=tk.LEFT, padx=(6, 12))

        apply_btn = tk.Button(controls, text="Apply Selected", command=self.apply_selected_update)
        rollback_btn = tk.Button(controls, text="Rollback Component", command=self.rollback_component)
        refresh_btn = tk.Button(controls, text="Refresh", command=self.refresh_updates)

        apply_btn.pack(side=tk.LEFT)
        rollback_btn.pack(side=tk.LEFT, padx=(8, 0))
        refresh_btn.pack(side=tk.RIGHT)

    def _build_activity_tab(self) -> None:
        tab = tk.Frame(self.notebook, bg="#111a2b")
        self.notebook.add(tab, text="Live Activity")

        self.activity_text = scrolledtext.ScrolledText(
            tab,
            bg="#0d1421",
            fg="#dce8ff",
            insertbackground="#dce8ff",
            wrap=tk.WORD,
            font=("Menlo", 10),
        )
        self.activity_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        clear_btn = tk.Button(tab, text="Clear", command=self.clear_activity)
        clear_btn.pack(anchor="e", padx=10, pady=(0, 10))

    def _build_launcher_tab(self) -> None:
        tab = tk.Frame(self.notebook, bg="#111a2b")
        self.notebook.add(tab, text="Launcher")

        hint = tk.Label(
            tab,
            text="Use Ctrl+Shift+Space to focus launcher input, then press Enter to submit.",
            bg="#111a2b",
            fg="#9fb2d7",
            anchor="w",
        )
        hint.pack(fill=tk.X, padx=10, pady=(10, 6))

        row = tk.Frame(tab, bg="#111a2b")
        row.pack(fill=tk.X, padx=10)

        self.command_entry = tk.Entry(
            row,
            textvariable=self.command_var,
            bg="#0d1421",
            fg="#f3f7ff",
            insertbackground="#f3f7ff",
            relief=tk.FLAT,
            font=("Helvetica", 11),
        )
        self.command_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8)
        self.command_entry.bind("<Return>", lambda _event: self.submit_command())

        submit_btn = tk.Button(row, text="Submit", command=self.submit_command, bg="#1f6feb", fg="#ffffff", relief=tk.FLAT)
        submit_btn.pack(side=tk.LEFT, padx=(8, 0))

        shortcuts = tk.Frame(tab, bg="#111a2b")
        shortcuts.pack(fill=tk.X, padx=10, pady=10)

        tk.Button(shortcuts, text="Launch App", command=lambda: self.prefill_command("launch application firefox")).pack(side=tk.LEFT)
        tk.Button(shortcuts, text="Install Package", command=lambda: self.prefill_command("install package htop")).pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(shortcuts, text="System Action", command=lambda: self.prefill_command("system status aegis-agent")).pack(side=tk.LEFT, padx=(8, 0))

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def focus_command_entry(self) -> None:
        self.notebook.select(4)
        self.command_entry.focus_set()
        self.command_entry.icursor(tk.END)

    def prefill_command(self, text: str) -> None:
        self.command_var.set(text)
        self.focus_command_entry()

    def _safe_request(self, func, on_error: str) -> Dict[str, Any] | None:
        try:
            return func()
        except ApiError as exc:
            self.set_status(f"{on_error}: {exc}")
            messagebox.showerror("AEGIS API Error", str(exc))
            return None

    def refresh_all(self) -> None:
        self.refresh_overview()
        self.refresh_pending_approvals()
        self.refresh_updates()
        self.poll_activity()

    def refresh_overview(self) -> None:
        payload = self._safe_request(lambda: self.client.get("/v1/control-center/overview"), "Overview refresh failed")
        if payload is None:
            return

        formatted = json.dumps(payload, indent=2, sort_keys=True)
        self.overview_text.delete("1.0", tk.END)
        self.overview_text.insert(tk.END, formatted)
        self.set_status("Overview updated")

    def refresh_pending_approvals(self) -> None:
        payload = self._safe_request(lambda: self.client.get("/v1/permissions/pending"), "Approval refresh failed")
        if payload is None:
            return

        self.pending_rows = payload.get("pending", [])
        self.pending_row_map.clear()

        for item in self.approvals_tree.get_children(""):
            self.approvals_tree.delete(item)

        for idx, row in enumerate(self.pending_rows):
            plan_id = str(row.get("plan_id", ""))
            step_id = str(row.get("step_id", ""))
            skill = str(row.get("skill", ""))
            action = str(row.get("action", ""))
            status = str(row.get("status", ""))
            item_id = f"row-{idx}"
            self.pending_row_map[item_id] = row
            self.approvals_tree.insert("", tk.END, iid=item_id, values=(plan_id, step_id, skill, action, status))

        self.set_status(f"Loaded {len(self.pending_rows)} pending approvals")

    def _selected_pending_identifiers(self) -> Tuple[str, str] | None:
        selected = self.approvals_tree.selection()
        if not selected:
            return None
        row = self.pending_row_map.get(selected[0], {})
        plan_id = str(row.get("plan_id", ""))
        step_id = str(row.get("step_id", ""))
        if not plan_id or not step_id:
            return None
        return plan_id, step_id

    def decide_pending(self, decision: str) -> None:
        selected = self._selected_pending_identifiers()
        if selected is None:
            messagebox.showwarning("Pending Approvals", "Select an approval row first.")
            return

        plan_id, step_id = selected
        payload = self._safe_request(
            lambda: self.client.post(
                "/v1/permissions/decide",
                {"plan_id": plan_id, "step_id": step_id, "decision": decision},
            ),
            "Permission decision failed",
        )
        if payload is None:
            return

        self.set_status(f"Decision '{decision}' applied to {plan_id}:{step_id}")
        self._append_activity_line(f"permission {decision} for {plan_id}:{step_id} -> {payload.get('status', 'unknown')}")
        self.refresh_pending_approvals()

    def refresh_updates(self) -> None:
        payload = self._safe_request(lambda: self.client.get("/v1/update/status"), "Update refresh failed")
        if payload is None:
            return

        current = payload.get("current", {})
        lines = [f"{component}: {version}" for component, version in sorted(current.items())]
        self.current_versions_label.configure(text="\n".join(lines) if lines else "No current versions reported")

        for item in self.updates_tree.get_children(""):
            self.updates_tree.delete(item)

        self.pending_update_rows = payload.get("pending_updates", [])
        components = set(current.keys())
        for row in self.pending_update_rows:
            components.add(str(row.get("component", "")))
            self.updates_tree.insert(
                "",
                tk.END,
                values=(
                    row.get("component", ""),
                    row.get("available_version", ""),
                    row.get("channel", ""),
                    row.get("notes", ""),
                ),
            )

        if components:
            ordered = [c for c in ["os", "agent", "model"] if c in components]
            ordered.extend(sorted(components - set(ordered)))
            self.component_combo.configure(values=ordered)
            if not self.component_var.get() or self.component_var.get() not in ordered:
                self.component_var.set(ordered[0])

        self.set_status("Update state refreshed")

    def apply_selected_update(self) -> None:
        selected = self.updates_tree.selection()
        if not selected:
            messagebox.showwarning("Updates", "Select a pending update row first.")
            return

        values = self.updates_tree.item(selected[0]).get("values", [])
        if len(values) < 2:
            messagebox.showwarning("Updates", "Selected row is invalid.")
            return

        component = str(values[0])
        version = str(values[1])
        payload = self._safe_request(
            lambda: self.client.post(
                "/v1/update/apply",
                {"component": component, "version": version, "source": "control-panel"},
            ),
            "Apply update failed",
        )
        if payload is None:
            return

        self.set_status(f"Applied update {component} -> {version}")
        self._append_activity_line(f"update applied: {component} -> {version}")
        self.refresh_updates()

    def rollback_component(self) -> None:
        component = self.component_var.get().strip()
        if not component:
            messagebox.showwarning("Rollback", "Choose a component first.")
            return

        payload = self._safe_request(
            lambda: self.client.post("/v1/update/rollback", {"component": component}),
            "Rollback failed",
        )
        if payload is None:
            return

        self.set_status(f"Rollback completed for component '{component}'")
        self._append_activity_line(f"update rollback: {component}")
        self.refresh_updates()

    def _append_activity_line(self, line: str) -> None:
        self.activity_text.insert(tk.END, f"{line}\n")
        self.activity_text.see(tk.END)

    def poll_activity(self) -> None:
        payload = self._safe_request(
            lambda: self.client.get("/v1/activity/feed", params={"offset": self.activity_offset, "limit": 200}),
            "Activity feed refresh failed",
        )
        if payload is None:
            self.root.after(3000, self.poll_activity)
            return

        events = payload.get("events", [])
        self.activity_offset = int(payload.get("next_offset", self.activity_offset))

        for event in events:
            timestamp = event.get("timestamp", "")
            source = event.get("source", "")
            event_type = event.get("event_type", "")
            details = event.get("details", {})
            rendered = f"{timestamp} | {source} | {event_type} | {json.dumps(details, sort_keys=True)}"
            self._append_activity_line(rendered)

        self.root.after(2500, self.poll_activity)

    def clear_activity(self) -> None:
        self.activity_text.delete("1.0", tk.END)

    def submit_command(self) -> None:
        text = self.command_var.get().strip()
        if not text:
            return

        payload = self._safe_request(
            lambda: self.client.post("/v1/process-and-execute", {"text": text, "allow_failure": False}),
            "Command execution failed",
        )
        if payload is None:
            return

        self._append_activity_line(f"launcher command: {text}")
        self._append_activity_line(f"launcher result: {json.dumps(payload, sort_keys=True)}")
        self.command_var.set("")
        self.set_status("Launcher command submitted")
        self.refresh_pending_approvals()
        self.refresh_overview()

    def install_desktop_hooks(self, show_dialogs: bool = True) -> None:
        payload = self._safe_request(
            lambda: self.client.post("/v1/desktop/control-panel/install", {"home_dir": None, "dry_run": False}),
            "Desktop hook installation failed",
        )
        if payload is None:
            return
        self.set_status("Desktop control-panel and launcher hooks installed")
        self._append_activity_line(f"desktop hooks install result: {json.dumps(payload, sort_keys=True)}")
        if show_dialogs:
            messagebox.showinfo("AEGIS", "Desktop hooks installed successfully.")

    def run(self) -> None:
        self.refresh_all()
        self.command_entry.focus_set()
        self.root.mainloop()


def main() -> None:
    app = ControlPanelApp()
    app.run()


if __name__ == "__main__":
    main()
