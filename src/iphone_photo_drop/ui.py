"""Desktop control window: shows the QR + pairing code, lists received files, Stop.

A calm, dark control surface matching the phone page: tinted near-black neutrals,
one green accent, a white card behind the QR so it stays scannable.
"""
from __future__ import annotations

import base64
import threading
import tkinter as tk
from tkinter import font as tkfont

from . import net, qr
from .server import ReceiverServer

# Palette: exact sRGB conversions of the phone page's OKLCH tokens, so the desktop
# window and the mobile page render the same colors.
BG = "#0b110d"
SURFACE = "#141b17"
TEXT = "#eff3f0"
MUTED = "#99a19b"
HAIRLINE = "#2e3530"
ACCENT = "#61da92"
ON_ACCENT = "#0a1a10"
DANGER = "#ef6661"


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    units = ["KB", "MB", "GB", "TB"]
    f = float(n)
    i = -1
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.1f} {units[i]}" if f < 10 else f"{round(f)} {units[i]}"


class ReceiverWindow:
    POLL_MS = 400

    def __init__(self, server: ReceiverServer, url: str, pin: str) -> None:
        self.server = server
        self.url = url
        self.pin = pin
        self._seen = 0
        self._firewall_ok: bool | None = None  # set by a background probe

        self.root = tk.Tk()
        self.root.title("Photo Drop")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.stop)
        self._set_window_icon()

        pad = 26
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(padx=pad, pady=(20, 22))

        f_chip = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        f_h1 = tkfont.Font(family="Segoe UI Semibold", size=17)
        f_sub = tkfont.Font(family="Segoe UI", size=10)
        f_label = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        f_pin = tkfont.Font(family="Consolas", size=30, weight="bold")
        f_status = tkfont.Font(family="Segoe UI", size=10)
        f_list = tkfont.Font(family="Consolas", size=10)

        tk.Label(wrap, text="●  LOCAL & ENCRYPTED", font=f_chip, fg=MUTED, bg=BG).pack(anchor="w")
        tk.Label(wrap, text="Scan to connect", font=f_h1, fg=TEXT, bg=BG).pack(anchor="w", pady=(12, 2))
        tk.Label(wrap, text="Point your iPhone camera at the code.", font=f_sub,
                 fg=MUTED, bg=BG).pack(anchor="w", pady=(0, 16))

        # QR on a white card so it always scans, regardless of theme.
        png = qr.png_bytes(url, scale=6)
        self._qr_img = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
        card = tk.Frame(wrap, bg="#ffffff")
        card.pack()
        tk.Label(card, image=self._qr_img, bg="#ffffff", bd=0).pack(padx=12, pady=12)

        tk.Label(wrap, text="PAIRING CODE", font=f_label, fg=MUTED, bg=BG).pack(anchor="center", pady=(18, 2))
        spaced = "  ".join(pin)
        tk.Label(wrap, text=spaced, font=f_pin, fg=ACCENT, bg=BG).pack(anchor="center")

        self.status = tk.Label(wrap, text="Waiting for photos…", font=f_status, fg=MUTED, bg=BG)
        self.status.pack(anchor="center", pady=(14, 10))

        # Received-files list.
        list_wrap = tk.Frame(wrap, bg=HAIRLINE, bd=0)
        list_wrap.pack(fill="x")
        self.listbox = tk.Listbox(
            list_wrap, height=6, width=40, font=f_list, bd=0, highlightthickness=0,
            bg=SURFACE, fg=TEXT, selectbackground=SURFACE, selectforeground=ACCENT,
            activestyle="none",
        )
        self.listbox.pack(fill="x", padx=1, pady=1)

        self.stop_btn = tk.Button(
            wrap, text="Stop receiving", font=f_status, command=self.stop,
            fg=MUTED, bg=BG, activebackground=SURFACE, activeforeground=TEXT,
            bd=1, relief="solid", highlightbackground=HAIRLINE, cursor="hand2",
            padx=14, pady=7,
        )
        self.stop_btn.pack(pady=(14, 0), fill="x")

    def _set_window_icon(self) -> None:
        # Brand the title bar / taskbar with the app icon. Cosmetic, so never let a
        # missing asset block launch.
        try:
            from importlib import resources
            data = (resources.files("iphone_photo_drop")
                    .joinpath("static/app-icon.png").read_bytes())
            self._app_icon = tk.PhotoImage(data=base64.b64encode(data).decode("ascii"))
            self.root.iconphoto(True, self._app_icon)
        except Exception:
            pass

    def run(self) -> None:
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        threading.Thread(target=self._probe_firewall, daemon=True).start()
        self.root.after(self.POLL_MS, self._poll)
        self.root.mainloop()

    def _probe_firewall(self) -> None:
        # Off the UI thread so the window paints instantly; result read by _poll.
        self._firewall_ok = net.firewall_rule_present()

    def _poll(self) -> None:
        received = self.server.session.received
        for item in received[self._seen:]:
            self.listbox.insert("end", f"  ✓  {item.name}   {human_size(item.size)}")
            self.listbox.see("end")
        session = self.server.session

        if session.locked_out:
            self.status.config(text="Too many wrong codes. Stopping…", fg=DANGER)
            self.root.after(800, self.stop)
            return
        if session.is_idle():
            self.status.config(text="Idle. Stopping…", fg=MUTED)
            self.root.after(400, self.stop)
            return

        if len(received) != self._seen:
            self._seen = len(received)
            word = "photo" if self._seen == 1 else "photos"
            self.status.config(text=f"{self._seen} {word} received", fg=ACCENT)
        elif self._firewall_ok is False and self._seen == 0:
            self.status.config(
                text="⚠  Firewall rule missing — re-run setup so your phone can connect",
                fg=DANGER,
            )

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
