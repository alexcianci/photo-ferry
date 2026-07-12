from iphone_photo_drop import security


def test_generate_token_is_high_entropy_and_unique():
    a = security.generate_token()
    b = security.generate_token()
    assert a != b
    assert len(a) >= 20  # token_urlsafe(16) -> ~22 chars, 128 bits


def test_generate_pin_is_six_digits():
    pin = security.generate_pin()
    assert len(pin) == 6
    assert pin.isdigit()


def test_verify_token_constant_time_match():
    assert security.verify_token("abc", "abc") is True
    assert security.verify_token("abc", "abcd") is False
    assert security.verify_token("abc", None) is False
    assert security.verify_token("abc", "") is False


def test_verify_pin_match():
    assert security.verify_pin("012345", "012345") is True
    assert security.verify_pin("012345", "543210") is False
    assert security.verify_pin("012345", None) is False
