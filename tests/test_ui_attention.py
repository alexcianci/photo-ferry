"""The idle timer measures human attention, and PC-side gestures are attention.

WHY THIS FILE EXISTS
--------------------
`Session._last_activity` was moved only by request handlers, so the ten-minute timeout
ran from launch no matter what the user did in the window. Measured twice on 2026-08-27:
the app launched, nothing was done, and it stopped itself at 607 s both times. The
reported case is ten minutes spent inside the file dialog choosing what to send -- and a
native file dialog runs a nested Tk event loop, so `after` callbacks keep firing and
`_poll` can call `stop()` with the dialog still open on screen.

That is why the touch in `add_files` has to happen BEFORE the dialog opens. A touch in
`offer()` alone does not fix the finding: `offer()` is not reached until the dialog
returns, and on a cancel it is never reached at all.

This is the same defect the project already fixed once in the other direction --
`test_server.py::test_outbox_fetch_touches_the_session_mid_stream` exists because
touching only before the first byte let the idle timer kill a long upload. Task 8's send
panel introduced a second long PC-side interaction and the principle was not extended to
it.

WHAT THIS DOES NOT CHECK
------------------------
No Tk root is created. Both methods are called unbound against a stand-in carrying only
the attributes they use, so this exercises the real bodies in `ui.py` without a display.
What that cannot see is the WIRING: that the drop zone's `<Button-1>` binding really
reaches `add_files`, and that the two listboxes are really bound to `_attention`. Those
bindings are asserted nowhere and would need a real window. `_attention` itself is
covered here; the bind() calls that route clicks into it are not.
"""
import types

from photo_ferry import ui
from photo_ferry.outbox import Outbox
from photo_ferry.session import Session

_LONG_AGO = 10_000  # seconds, well past any timeout under test


class _FakeListbox:
    def __init__(self):
        self.rows = []

    def insert(self, _where, text):
        self.rows.append(text)

    def see(self, _where):
        pass


class _FakeLabel:
    def __init__(self):
        self.kwargs = {}

    def config(self, **kw):
        self.kwargs.update(kw)


def _stand_in(session):
    win = types.SimpleNamespace(
        server=types.SimpleNamespace(session=session),
        outbox=Outbox(),
        outbox_list=_FakeListbox(),
        send_hint=_FakeLabel(),
        max_batch_files=25,
        FILE_TYPES=ui.ReceiverWindow.FILE_TYPES,
    )
    # Bind the real method to the stand-in, so the code under test calls the real seam
    # rather than a fake of it.
    win._attention = lambda *a: ui.ReceiverWindow._attention(win, *a)
    return win


def test_offer_touches_the_session():
    """Registering files is a human at the keyboard, whatever the network is doing."""
    session = Session.new(idle_timeout_sec=600)
    win = _stand_in(session)
    session._last_activity -= _LONG_AGO
    # Precondition, asserted rather than assumed: without it a bug that made is_idle()
    # always False would leave this test green while checking nothing.
    assert session.is_idle() is True, "the stand-in session was not made idle first"

    ui.ReceiverWindow.offer(win, [])

    assert session.is_idle() is False, (
        "offer() left the session idle. The send panel can be worked for as long as the "
        "user likes and the idle timer will still stop the listener out from under them."
    )


def test_choosing_files_touches_the_session_before_the_dialog_opens(monkeypatch):
    """The load-bearing half. A modal file dialog does not pause `_poll`.

    Cancelling is the sharpest case: `offer()` never runs, so if the touch lives only
    there, ten minutes of choosing ends with a dead app and nothing registered.
    """
    session = Session.new(idle_timeout_sec=600)
    win = _stand_in(session)

    order = []
    real_touch = session.touch
    monkeypatch.setattr(session, "touch",
                        lambda: (order.append("touch"), real_touch())[1])

    def _fake_dialog(**_kwargs):
        order.append("dialog")
        return ()  # the user cancelled after a long look

    monkeypatch.setattr(ui.filedialog, "askopenfilenames", _fake_dialog)

    ui.ReceiverWindow.add_files(win)

    assert order == ["touch", "dialog"], (
        f"expected the session touched before the dialog opened, saw {order}.\n"
        "A touch after the dialog returns is too late: the dialog runs a nested event "
        "loop, _poll keeps firing, and stop() can land while it is still open."
    )


def test_a_gesture_on_its_own_touches_the_session():
    """`_attention` is the seam every clickable control routes through."""
    session = Session.new(idle_timeout_sec=600)
    win = _stand_in(session)
    session._last_activity -= _LONG_AGO
    assert session.is_idle() is True

    ui.ReceiverWindow._attention(win)

    assert session.is_idle() is False
