"""Tkinter control window: shows QR + PIN, lists received files, Stop button."""
from __future__ import annotations

import base64
import threading
import tkinter as tk
from tkinter import ttk

from . import qr
from .server import ReceiverServer


class ReceiverWindow:
    POLL_MS = 500

    def __init__(self, server: ReceiverServer, url: str, pin: str) -> None:
        self.server = server
        self.url = url
        self.pin = pin
        self._server_thread: threading.Thread | None = None
        self._seen = 0

        self.root = tk.Tk()
        self.root.title("iPhone Photo Drop")
        self.root.protocol("WM_DELETE_WINDOW", self.stop)

        png = qr.png_bytes(url, scale=6)
        self._qr_img = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))

        ttk.Label(self.root, text="Scan with your iPhone camera",
                  font=("Segoe UI", 12)).pack(pady=(12, 4))
        ttk.Label(self.root, image=self._qr_img).pack(padx=16)
        ttk.Label(self.root, text=f"PIN: {pin}",
                  font=("Consolas", 22, "bold")).pack(pady=6)
        ttk.Label(self.root, text=url, foreground="#666").pack()
        self.status = ttk.Label(self.root, text="Waiting for uploads...")
        self.status.pack(pady=6)

        self.listbox = tk.Listbox(self.root, height=8, width=48)
        self.listbox.pack(padx=16, pady=8, fill="both", expand=True)

        ttk.Button(self.root, text="Stop", command=self.stop).pack(pady=(0, 12))

    def run(self) -> None:
        self._server_thread = threading.Thread(target=self.server.serve_forever,
                                                daemon=True)
        self._server_thread.start()
        self.root.after(self.POLL_MS, self._poll)
        self.root.mainloop()

    def _poll(self) -> None:
        received = self.server.session.received
        for item in received[self._seen:]:
            self.listbox.insert("end", f"{item.name}  ({item.size:,} bytes)")
        if len(received) != self._seen:
            self._seen = len(received)
            self.status.config(text=f"{self._seen} file(s) received")
        if self.server.session.locked_out:
            self.status.config(text="Locked out (too many wrong PINs). Stopping...")
            self.root.after(800, self.stop)
            return
        if self.server.session.is_idle():
            self.status.config(text="Idle timeout. Stopping...")
            self.root.after(400, self.stop)
            return
        self.root.after(self.POLL_MS, self._poll)

    def stop(self) -> None:
        try:
            self.server.shutdown()
            self.server.server_close()
        finally:
            try:
                self.root.destroy()
            except tk.TclError:
                pass
