"""Desktop control window: shows the QR + pairing code, lists received files, Stop.

Transit signage, matching the phone page: a deep navy ground, one bright water-blue accent
used only as a fill, wide-tracked uppercase labels, and a white card behind the QR so
it stays scannable regardless of the surrounding theme.
"""
from __future__ import annotations

import base64
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from tkinter import font as tkfont

from . import net, qr
from .outbox import Outbox
from .server import ReceiverServer

# Transit-signage palette. Deliberately no bundled typeface, no webfont and no Google
# Fonts: the signage feel comes from weight, size and letterspacing on the system stack
# already in use. Every pairing below is asserted in tests/test_palette.py, and the
# comments record the measured ratios that constrain usage.
BG = "#17324D"          # base background
SURFACE = "#203B55"     # elevated surfaces
HAIRLINE = "#35506A"    # DECORATIVE DIVIDERS ONLY - 1.57:1 on BG, never a boundary
OUTLINE = "#7396B8"     # interactive boundaries - 4.24:1 on BG, 3.73:1 on SURFACE
TEXT = "#F7F4ED"        # primary - 11.95:1 on BG, 10.51:1 on SURFACE
TEXT_2 = "#C5CCD1"      # secondary - 8.08 / 7.11; the only muted tone allowed on SURFACE
MUTED = "#8E9AA3"       # tertiary - 4.56 on BG but 4.02 on SURFACE, so BG only here. The
                        # page also allows it on its recessed track (5.66), which the Tk
                        # window has no counterpart for.
# 2026-08-29: lightened from #4B9CD3 at the operator's call, and that crossed a line
# the palette used to hold. The accent was deliberately kept UNDER 4.5:1 so that using
# it as body text was IMPOSSIBLE rather than merely discouraged. At 7.24:1 it is now
# legal as text anywhere, so the rule below is POLICY, held by review and by the comment
# at each site -- it is no longer enforced by measurement. Every comment in this file
# that reasons "accent is illegal here" was rewritten with it; if one says that again,
# it predates this change. See tests/test_palette.py::test_accent_is_legal_where_it_is_used.
ACCENT = "#9DC6E0"      # buttons, focus rings, highlights - NEVER body or label text
ACCENT_PRESS = "#86B4D2"
ON_ACCENT = "#17324D"   # navy on blue, 7.24:1 - clears the normal-text floor
DANGER = "#FF8A7A"      # the brief supplies no error tone; 5.73 on BG, 5.04 on SURFACE

# Button label type was load-bearing for contrast until 2026-08-29 and is now design
# intent. ON_ACCENT on ACCENT is 7.24:1, and 5.92:1 on ACCENT_PRESS, so both clear the
# 4.5 normal-text floor at any size. 14pt bold, and the phone page's 19px at weight 700,
# are still asserted in tests/test_palette.py -- they hold the look now rather than the
# legality. Shrinking the label no longer makes it illegal, it just stops it reading as
# a button.
BUTTON_FONT_PT = 14
BUTTON_FONT_WEIGHT = "bold"


def tracked(text: str) -> str:
    """Tk cannot set letter-spacing, so widen tracking by inserting gaps. The pairing
    code display already does this; signage labels reuse it."""
    return " ".join(text)


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
    FILE_TYPES = [
        ("Photos and videos",
         "*.heic *.heif *.jpg *.jpeg *.png *.gif *.webp *.mov *.mp4 *.m4v"),
    ]

    def __init__(self, server: ReceiverServer, url: str, pin: str,
                 outbox: Outbox, max_batch_files: int) -> None:
        self.server = server
        self.url = url
        self.pin = pin
        # Must be the same Outbox instance the server serves from, or the panel fills a
        # registry nothing reads and the phone sees an empty manifest.
        self.outbox = outbox
        # Canonical value lives in Config.max_batch_files; never re-spell it here.
        self.max_batch_files = max_batch_files
        self._seen = 0
        self._firewall_ok: bool | None = None  # set by a background probe

        self.root = tk.Tk()
        self.root.title("Photo Ferry")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.stop)
        self._set_window_icon()

        pad = 26
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(padx=pad, pady=(20, 22))

        f_chip = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        f_h1 = tkfont.Font(family="Segoe UI Semibold", size=19)
        f_sub = tkfont.Font(family="Segoe UI", size=10)
        f_label = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        f_pin = tkfont.Font(family="Consolas", size=30, weight="bold")
        f_status = tkfont.Font(family="Segoe UI", size=10)
        f_list = tkfont.Font(family="Consolas", size=10)
        # The one control that has to read as a button. Spelled from the constants and
        # never from literals, because tests/test_palette.py asserts on the constants:
        # inlining 14/"bold" here would leave the assertion checking nothing this window
        # actually renders.
        f_button = tkfont.Font(family="Segoe UI", size=BUTTON_FONT_PT,
                               weight=BUTTON_FONT_WEIGHT)

        # tracked() covers the words only. Passing the whole string would space the
        # bullet and the two gaps after it as well, giving a five-space gutter before
        # the first letter.
        tk.Label(wrap, text="●  " + tracked("LOCAL & ENCRYPTED"), font=f_chip,
                 fg=MUTED, bg=BG).pack(anchor="w")
        tk.Label(wrap, text="Scan to connect", font=f_h1, fg=TEXT, bg=BG).pack(anchor="w", pady=(12, 2))
        tk.Label(wrap, text="Point your iPhone camera at the code.", font=f_sub,
                 fg=MUTED, bg=BG).pack(anchor="w", pady=(0, 16))

        # QR on a white card so it always scans, regardless of theme.
        png = qr.png_bytes(url, scale=6)
        self._qr_img = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
        card = tk.Frame(wrap, bg="#ffffff")
        card.pack()
        tk.Label(card, image=self._qr_img, bg="#ffffff", bd=0).pack(padx=12, pady=12)

        tk.Label(wrap, text=tracked("PAIRING CODE"), font=f_label, fg=MUTED, bg=BG).pack(anchor="center", pady=(18, 2))
        # Wider tracking than tracked() gives, and left alone on purpose: six digits read
        # one at a time need more air than a word does.
        spaced = "  ".join(pin)
        # The one place accent carries glyphs. 7.24:1 on BG clears the 4.5 normal-text
        # floor outright, so unlike before the lightening this no longer depends on the
        # 30pt bold to be legal. The size stays because six digits read one at a time
        # want the air, not because contrast needs it.
        tk.Label(wrap, text=spaced, font=f_pin, fg=ACCENT, bg=BG).pack(anchor="center")

        self.status = tk.Label(wrap, text="Waiting for photos…", font=f_status, fg=MUTED, bg=BG)
        self.status.pack(anchor="center", pady=(14, 10))

        # Received-files list. This 1px frame is the listbox's border, and a listbox is an
        # interactive component, so it takes OUTLINE (4.24:1 on BG) and not HAIRLINE.
        # HAIRLINE is 1.57:1 and fails the 3:1 non-text floor everywhere; it is legal only
        # on the plain divider further down.
        list_wrap = tk.Frame(wrap, bg=OUTLINE, bd=0)
        list_wrap.pack(fill="x")
        self.listbox = tk.Listbox(
            list_wrap, height=6, width=40, font=f_list, bd=0, highlightthickness=0,
            # selectforeground was ACCENT, which made the selected row body text. At
            # today's 6.37:1 on SURFACE that would be legal, and it stays TEXT anyway:
            # accent-as-body-text is the palette's policy line, and it outlived the
            # measurement that used to enforce it. TEXT is 10.51:1 and the selection
            # still reads, because selectbackground differs from the row fill.
            bg=SURFACE, fg=TEXT, selectbackground=SURFACE, selectforeground=TEXT,
            activestyle="none",
        )
        self.listbox.pack(fill="x", padx=1, pady=1)
        # Clicking a row is attention too. add="+" so this rides ALONGSIDE the class
        # binding that does the selecting instead of displacing it, and the handler
        # returns None, so the default behaviour still runs afterwards.
        self.listbox.bind("<Button-1>", self._attention, add="+")

        # The border is a wrapping Frame, not an option on the Button, because
        # `highlightbackground` is INERT on tk.Button here. Measured by reading the
        # rendered pixels back through GDI: with bd=1, relief="solid" and
        # highlightbackground=OUTLINE the outermost row and column come back #000000 --
        # no #7396B8 pixel anywhere on the widget -- and at highlightthickness=2 the
        # Button reserves the 2px and paints none of it. The identical option on the
        # tk.Frame below does paint #7396B8, so the option works on Frame and does
        # nothing on Button on this platform.
        #
        # That matters because the fallback Tk draws instead is the relief="solid"
        # border in pure black: 1.60:1 on BG, marginally WORSE than the 1.57:1 HAIRLINE
        # it looked like it was replacing. The button's fill is BG, identical to the
        # page behind it, so this border is the only thing identifying it as a control.
        # Same wrapper pattern as the listbox above, and for the same reason.
        stop_wrap = tk.Frame(wrap, bg=OUTLINE, bd=0)
        stop_wrap.pack(pady=(14, 0), fill="x")
        self.stop_btn = tk.Button(
            stop_wrap, text="Stop receiving", font=f_status, command=self.stop,
            fg=MUTED, bg=BG, activebackground=SURFACE, activeforeground=TEXT,
            bd=0, relief="flat", highlightthickness=0, cursor="hand2",
            padx=14, pady=7,
        )
        self.stop_btn.pack(fill="x", padx=1, pady=1)
        # Deliberately NOT wired to _attention, and the omission is not an oversight.
        # Its command tears down the server and destroys the root, so nothing ever reads
        # _last_activity again; a touch here could not change an outcome. Every other
        # clickable control in this window routes through _attention.

        # Decorative rule between the two halves of the window, and the only place
        # HAIRLINE is legal: it separates nothing interactive and carries no state.
        tk.Frame(wrap, bg=HAIRLINE, height=1).pack(fill="x", pady=(18, 14))
        tk.Label(wrap, text=tracked("SEND TO IPHONE"), font=f_label, fg=MUTED, bg=BG).pack(anchor="w")

        self.send_hint = tk.Label(
            wrap, text="Add photos, then open “Get from PC” on your phone.",
            font=f_sub, fg=MUTED, bg=BG, wraplength=300, justify="left",
        )
        self.send_hint.pack(anchor="w", pady=(4, 10))

        self.outbox_list = tk.Listbox(
            wrap, height=4, width=40, font=f_list, bd=0, highlightthickness=0,
            # Same reason as the received list above: accent may not be row text.
            bg=SURFACE, fg=TEXT, selectbackground=SURFACE, selectforeground=TEXT,
            activestyle="none",
        )
        self.outbox_list.pack(fill="x")
        self.outbox_list.bind("<Button-1>", self._attention, add="+")

        # Styled as a drop zone even though nothing can be dropped on it yet: it reads as
        # the place files go, and it is already the right shape if DnD returns later.
        # OUTLINE, not HAIRLINE: the whole frame is clickable, so its edge is an
        # interactive boundary and owes the 3:1 non-text floor.
        self.drop_zone = tk.Frame(
            wrap, bg=SURFACE, highlightbackground=OUTLINE, highlightthickness=1,
            cursor="hand2",
        )
        self.drop_zone.pack(fill="x", pady=(10, 0))
        # A glyph used as an icon, not as text, so the 3:1 non-text floor applies and
        # 6.37:1 on SURFACE clears it. The phone page's check icon and spinner keep the
        # accent for the same reason.
        tk.Label(self.drop_zone, text="+", font=tkfont.Font(family="Segoe UI", size=20),
                 fg=ACCENT, bg=SURFACE).pack(pady=(14, 0))
        # The picker's action label: the one filled control on this window, so it wears
        # the accent as a fill with the navy label on top. That pairing is 7.24:1 and
        # clears the normal-text floor, so f_button (14pt bold) is now about weight in
        # the layout rather than about staying legal.
        tk.Label(self.drop_zone, text="Choose photos or videos", font=f_button,
                 fg=ON_ACCENT, bg=ACCENT).pack(pady=(10, 0), ipadx=14, ipady=8)
        # TEXT_2, not MUTED: this label sits on SURFACE, where MUTED is 4.02:1 and fails
        # the normal-text floor. MUTED is legal on BG only.
        tk.Label(self.drop_zone, text="They stay on this PC until your phone asks for them",
                 font=f_sub, fg=TEXT_2, bg=SURFACE, wraplength=280).pack(pady=(8, 14))
        for widget in (self.drop_zone, *self.drop_zone.winfo_children()):
            widget.bind("<Button-1>", lambda _e: self.add_files())

    def _attention(self, _event=None) -> None:
        """A human is using this window, so the session is not idle.

        The idle timeout's purpose is unchanged: nothing may listen unattended, and ten
        minutes of genuinely unattended time still stops the listener. What changed is
        the evidence it accepts. Until now the only thing that moved the timer was an
        HTTP request from the phone -- a sound proxy for attention while the sole
        PC-side act was looking at a QR code, and a broken one once Task 8 made the
        desktop half a place where real work happens. A user choosing which photos to
        send is present by definition; the timer simply could not see them.

        Takes an unused event argument so it can be handed straight to bind().
        """
        self.server.session.touch()

    def add_files(self) -> None:
        # BEFORE the dialog opens, and that ordering is the whole fix. A native file
        # dialog runs a NESTED Tk event loop, so `after` callbacks keep firing while it
        # is up and _poll can call stop() with the picker still on screen -- which is the
        # reported case, ten minutes spent choosing. Touching on return is too late, and
        # on a cancel never happens at all, which is why offer() alone does not close it.
        self._attention()
        paths = filedialog.askopenfilenames(
            title="Add photos or videos", filetypes=self.FILE_TYPES,
        )
        if paths:
            self.offer(paths)

    def offer(self, paths) -> None:
        """The single intake seam for outgoing files: register paths and refresh the
        list, silently skipping non-media and repeats.

        Every way of adding files goes through here: today only the picker, and if
        drag-and-drop returns it becomes a second caller and changes nothing else.

        Add-only by design. Outbox.remove()/clear() do not revoke an in-flight stream --
        after clear() an already-open response still delivered the whole file -- so no
        remove/clear control is offered rather than one that does not stop the transfer.

        Skipping an already-offered path does NOT breach that constraint, and is the
        reason the dedupe lives here rather than in Outbox: it revokes nothing and can
        never orphan an in-flight stream, because the entry it declines to create does
        not exist yet. It is the opposite of remove(). Do not "fix" it back.

        Without it, re-picking the same range -- add ten photos, notice you missed one,
        reopen the picker and shift-select the same range again -- registers a second
        and third id for one file: three manifest rows, three copies in the camera roll.
        With no remove control, the only remedy would be killing the session, which
        means a new PIN and a re-scanned QR. Compared on the resolved form Outbox
        stores, so the comparison sees the same identity the registry does.
        """
        # Every intake path lands here, including any future drag-and-drop caller that
        # never opens the picker, so the seam touches on its own account rather than
        # relying on add_files having done it.
        self._attention()
        known = {entry.path for entry in self.outbox.list()}
        fresh = []
        for raw in paths:
            try:
                resolved = Path(raw).resolve()
            except OSError:
                # A disconnected share can raise here. Drop the pick rather than pass it
                # on: Outbox.add resolves the very same path itself, so it would raise
                # the identical OSError out of the file-picker callback and take the
                # panel down. An unresolvable path could never have registered anyway.
                continue
            if resolved in known:
                continue
            # Also dedupes within this one call, for a selection holding the same file
            # twice. Non-media is still left to Outbox.add to skip silently.
            known.add(resolved)
            fresh.append(raw)
        added = self.outbox.add(fresh)
        for entry in added:
            self.outbox_list.insert("end", f"  {entry.name}   {human_size(entry.size)}")
        self.outbox_list.see("end")
        total = len(self.outbox.list())
        # Strictly greater, not >=, on purpose: max_batch_files is one whole batch, so
        # exactly 25 items still travel as a single group and need no warning. 26 is the
        # first count iOS has to split, which is where the grouping hint belongs.
        if total > self.max_batch_files:
            # Promoted from MUTED to TEXT rather than to ACCENT. Accent on BG is now
            # 7.24:1, so an accent hint would be legal on contrast alone -- and it is
            # still refused, because accent is not body text. That is now a rule someone
            # has to keep rather than one the numbers keep. Primary still reads as "this
            # line changed", at 11.95:1.
            self.send_hint.config(
                text=f"{total} items. iOS saves one batch at a time — "
                     "your phone will show these in groups.",
                fg=TEXT,
            )

    def _set_window_icon(self) -> None:
        # Brand the title bar / taskbar with the app icon. Cosmetic, so never let a
        # missing asset block launch.
        try:
            from importlib import resources
            data = (resources.files("photo_ferry")
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
            # TEXT, not ACCENT, for the same reason as the send hint: accent is not
            # body text, now by policy rather than by measurement. The palette has no
            # success tone,
            # so the signal is the jump from MUTED to primary rather than a hue change.
            self.status.config(text=f"{self._seen} {word} received", fg=TEXT)
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
