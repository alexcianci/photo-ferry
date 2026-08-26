import threading

from photo_ferry.session import Session


def test_check_pin_wrong_then_locked():
    s = Session("tok", "123456", max_pin_attempts=3)
    assert s.check_pin("000000") == "wrong"
    assert s.check_pin("000000") == "wrong"
    assert s.check_pin("000000") == "locked"
    assert s.locked_out is True
    assert s.authed is False


def test_check_pin_correct_marks_authed():
    s = Session("tok", "123456", max_pin_attempts=3)
    assert s.check_pin("123456") == "ok"
    assert s.authed is True


def test_check_pin_already_locked_returns_locked():
    s = Session("tok", "123456", max_pin_attempts=1)
    assert s.check_pin("000000") == "locked"
    assert s.check_pin("123456") == "locked"  # correct PIN ignored once locked
    assert s.authed is False


def test_check_pin_is_atomic_under_concurrency():
    s = Session("tok", "123456", max_pin_attempts=5)
    results = []
    rlock = threading.Lock()

    def attempt():
        r = s.check_pin("000000")  # always wrong (pin is 123456)
        with rlock:
            results.append(r)

    threads = [threading.Thread(target=attempt) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # The security property: no more than max_pin_attempts failures were ever
    # registered, even though 50 requests raced. Without atomicity this exceeds 5.
    assert s.failed_attempts <= 5
    assert results.count("ok") == 0


def test_new_session_has_token_and_pin():
    s = Session.new()
    assert len(s.token) >= 20
    assert s.pin.isdigit() and len(s.pin) == 6
    assert s.authed is False
    assert s.failed_attempts == 0


def test_register_failure_increments_and_reports_lockout():
    s = Session.new(max_pin_attempts=3)
    assert s.register_failure() == 1
    assert s.locked_out is False
    s.register_failure()
    assert s.register_failure() == 3
    assert s.locked_out is True


def test_mark_authed_and_record_received():
    s = Session.new()
    s.mark_authed()
    assert s.authed is True
    s.record_received("a.jpg", 100)
    s.record_received("b.mov", 200)
    assert [r.name for r in s.received] == ["a.jpg", "b.mov"]
    assert s.total_bytes == 300


def test_idle_detection_uses_injected_clock():
    now = [1000.0]
    s = Session.new(idle_timeout_sec=600, clock=lambda: now[0])
    s.touch()
    assert s.is_idle() is False
    now[0] = 1000.0 + 601
    assert s.is_idle() is True
