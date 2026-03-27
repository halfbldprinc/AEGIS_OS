"""Always-on-top desktop chat widget for AegisOS."""

from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import scrolledtext
from urllib import error, request


class ChatWidgetApp:
    def __init__(self, api_base_url: str = "http://127.0.0.1:8000"):
        self.api_base_url = api_base_url.rstrip("/")
        self.session_id = "desktop-widget"

        self.root = tk.Tk()
        self.root.title("AegisOS")
        self.root.geometry("420x560+20+80")
        self.root.attributes("-topmost", True)

        # Semi-transparent look but keep readability.
        self.root.configure(bg="#131722")

        header = tk.Label(
            self.root,
            text="AegisOS Assistant",
            bg="#1d2433",
            fg="#e8ecf3",
            font=("Helvetica", 12, "bold"),
            pady=8,
        )
        header.pack(fill=tk.X)

        self.chat_log = scrolledtext.ScrolledText(
            self.root,
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg="#0e1320",
            fg="#dfe8f4",
            insertbackground="#dfe8f4",
            font=("Menlo", 11),
        )
        self.chat_log.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        bottom = tk.Frame(self.root, bg="#131722")
        bottom.pack(fill=tk.X, padx=8, pady=(0, 8))

        self.input_var = tk.StringVar()
        self.entry = tk.Entry(
            bottom,
            textvariable=self.input_var,
            bg="#1a2030",
            fg="#f2f6ff",
            insertbackground="#f2f6ff",
            relief=tk.FLAT,
            font=("Helvetica", 11),
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8)
        self.entry.bind("<Return>", lambda _event: self.send_message())

        send_btn = tk.Button(
            bottom,
            text="Send",
            command=self.send_message,
            bg="#2b74ff",
            fg="#ffffff",
            relief=tk.FLAT,
            padx=14,
            pady=8,
        )
        send_btn.pack(side=tk.LEFT, padx=(8, 0))

        self._append("aegis", "Desktop widget online. Ask me anything.")

    def _append(self, role: str, text: str) -> None:
        self.chat_log.configure(state=tk.NORMAL)
        prefix = "You" if role == "user" else "Aegis"
        self.chat_log.insert(tk.END, f"{prefix}: {text}\n\n")
        self.chat_log.configure(state=tk.DISABLED)
        self.chat_log.see(tk.END)

    def send_message(self) -> None:
        message = self.input_var.get().strip()
        if not message:
            return
        self.input_var.set("")
        self._append("user", message)

        thread = threading.Thread(target=self._send_to_api, args=(message,), daemon=True)
        thread.start()

    def _send_to_api(self, message: str) -> None:
        payload = {
            "message": message,
            "session_id": self.session_id,
        }

        req = request.Request(
            f"{self.api_base_url}/v1/chat/message",
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        try:
            with request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
            response_text = str(data.get("agent_response", "No response"))
        except (error.HTTPError, error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            response_text = f"Connection error: {exc}"

        self.root.after(0, lambda: self._append("assistant", response_text))

    def run(self) -> None:
        self.entry.focus_set()
        self.root.mainloop()


def main() -> None:
    app = ChatWidgetApp()
    app.run()


if __name__ == "__main__":
    main()
