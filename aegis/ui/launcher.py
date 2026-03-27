"""Quick launcher prompt for submitting natural-language commands to AegisOS."""

from __future__ import annotations

import argparse
import json
import os
import socket
import threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from typing import Optional

from .api_client import AegisApiClient, ApiError


DEFAULT_TRAY_SOCKET = str(Path.home() / ".aegis" / "ui" / "launcher-tray.sock")


class LauncherApp:
    def __init__(self, api_base_url: str = "http://127.0.0.1:8000", tray_mode: bool = False, socket_path: str = DEFAULT_TRAY_SOCKET):
        self.client = AegisApiClient(api_base_url=api_base_url)
        self.tray_mode = tray_mode
        self.socket_path = os.path.expanduser(socket_path)
        self._server_thread: threading.Thread | None = None
        self._server_socket: socket.socket | None = None
        self._running = False

        self.root = tk.Tk()
        self.root.title("AEGIS Launcher")
        self.root.geometry("620x150+120+120")
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#111a2b")

        self.value = tk.StringVar()
        self.status = tk.StringVar(value="Enter a natural-language command and press Enter")

        title = tk.Label(
            self.root,
            text="AEGIS Global Launcher",
            font=("Helvetica", 13, "bold"),
            bg="#111a2b",
            fg="#f3f7ff",
        )
        title.pack(anchor="w", padx=12, pady=(10, 6))

        row = tk.Frame(self.root, bg="#111a2b")
        row.pack(fill=tk.X, padx=12)

        entry = tk.Entry(
            row,
            textvariable=self.value,
            bg="#0d1421",
            fg="#f3f7ff",
            insertbackground="#f3f7ff",
            relief=tk.FLAT,
            font=("Helvetica", 11),
        )
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=9)
        entry.bind("<Return>", lambda _event: self.submit())

        submit = tk.Button(row, text="Send", command=self.submit, bg="#1f6feb", fg="#ffffff", relief=tk.FLAT)
        submit.pack(side=tk.LEFT, padx=(8, 0))

        status = tk.Label(self.root, textvariable=self.status, bg="#111a2b", fg="#9fb2d7", anchor="w")
        status.pack(fill=tk.X, padx=12, pady=(8, 4))

        if self.tray_mode:
            hint = tk.Label(
                self.root,
                text="Tray mode: run aegis-launcher-toggle from your hotkey to show or hide this launcher.",
                bg="#111a2b",
                fg="#88a6d6",
                anchor="w",
            )
            hint.pack(fill=tk.X, padx=12, pady=(0, 10))

        entry.focus_set()

        self.root.protocol("WM_DELETE_WINDOW", self._handle_close)
        if self.tray_mode:
            self._start_toggle_server()
            self.root.withdraw()

    def submit(self) -> None:
        text = self.value.get().strip()
        if not text:
            return

        try:
            payload = self.client.post("/v1/process-and-execute", {"text": text, "allow_failure": False})
        except ApiError as exc:
            messagebox.showerror("AEGIS Launcher", str(exc))
            self.status.set(str(exc))
            return

        self.status.set(f"Submitted: {text}")
        self.value.set("")

        if payload.get("requires_approval"):
            messagebox.showinfo("AEGIS Launcher", "Command queued and waiting for approval in Control Panel.")
            return

        messagebox.showinfo("AEGIS Launcher", json.dumps(payload, indent=2, sort_keys=True))

    def _handle_close(self) -> None:
        if self.tray_mode:
            self.root.withdraw()
            self.status.set("Launcher hidden. Use your global hotkey to show again.")
            return
        self._shutdown_server()
        self.root.destroy()

    def _toggle_visibility(self) -> None:
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.status.set("Launcher ready")
        else:
            self.root.withdraw()

    def _start_toggle_server(self) -> None:
        sock_path = Path(self.socket_path)
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        if sock_path.exists():
            try:
                sock_path.unlink()
            except OSError:
                pass

        self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket.bind(str(sock_path))
        self._server_socket.listen(5)
        self._running = True

        def _serve() -> None:
            while self._running:
                try:
                    conn, _ = self._server_socket.accept()
                except OSError:
                    break
                with conn:
                    try:
                        command = conn.recv(128).decode("utf-8", errors="ignore").strip().lower()
                    except OSError:
                        continue

                    if command == "toggle":
                        self.root.after(0, self._toggle_visibility)
                    elif command == "show":
                        self.root.after(0, self._show)
                    elif command == "hide":
                        self.root.after(0, self.root.withdraw)
                    elif command == "quit":
                        self.root.after(0, self._quit)

        self._server_thread = threading.Thread(target=_serve, daemon=True)
        self._server_thread.start()

    def _show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _quit(self) -> None:
        self._shutdown_server()
        self.root.destroy()

    def _shutdown_server(self) -> None:
        self._running = False
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None
        sock_path = Path(self.socket_path)
        if sock_path.exists():
            try:
                sock_path.unlink()
            except OSError:
                pass

    @staticmethod
    def send_control(command: str, socket_path: str = DEFAULT_TRAY_SOCKET) -> bool:
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(os.path.expanduser(socket_path))
            client.sendall(command.encode("utf-8"))
            client.close()
            return True
        except OSError:
            return False

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self._shutdown_server()


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="AEGIS quick launcher")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="Base URL of AEGIS API")
    parser.add_argument("--tray", action="store_true", help="Run persistent launcher tray mode")
    parser.add_argument("--toggle", action="store_true", help="Toggle existing tray launcher visibility")
    parser.add_argument("--show", action="store_true", help="Show existing tray launcher")
    parser.add_argument("--hide", action="store_true", help="Hide existing tray launcher")
    parser.add_argument("--quit", action="store_true", help="Stop existing tray launcher")
    parser.add_argument("--socket", default=DEFAULT_TRAY_SOCKET, help="Unix socket path for tray launcher control")
    args = parser.parse_args(argv)

    if args.toggle or args.show or args.hide or args.quit:
        command = "toggle"
        if args.show:
            command = "show"
        elif args.hide:
            command = "hide"
        elif args.quit:
            command = "quit"

        ok = LauncherApp.send_control(command=command, socket_path=args.socket)
        if not ok and args.toggle:
            app = LauncherApp(api_base_url=args.api, tray_mode=True, socket_path=args.socket)
            app._show()
            app.run()
        return

    app = LauncherApp(api_base_url=args.api, tray_mode=args.tray, socket_path=args.socket)
    if not args.tray:
        app._show()
    app.run()


if __name__ == "__main__":
    main()
