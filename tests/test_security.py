import pytest

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


def test_sanitize_strips_path_components():
    assert security.sanitize_filename("../../etc/passwd.jpg") == "passwd.jpg"
    assert security.sanitize_filename(r"..\..\windows\evil.png") == "evil.png"
    assert security.sanitize_filename("/abs/path/pic.jpeg") == "pic.jpeg"


def test_sanitize_strips_control_chars_and_leading_dots():
    assert security.sanitize_filename("na\x00me\t.png") == "name.png"
    assert security.sanitize_filename("...hidden.mov") == "hidden.mov"


def test_sanitize_rejects_empty_or_extensionless():
    with pytest.raises(ValueError):
        security.sanitize_filename("")
    with pytest.raises(ValueError):
        security.sanitize_filename("../../")
    with pytest.raises(ValueError):
        security.sanitize_filename("noext")


def test_sanitize_rejects_disallowed_extension():
    with pytest.raises(ValueError):
        security.sanitize_filename("payload.exe")
    with pytest.raises(ValueError):
        security.sanitize_filename("script.js")


def test_sanitize_caps_length_but_keeps_extension():
    long_name = "a" * 300 + ".jpg"
    out = security.sanitize_filename(long_name)
    assert out.endswith(".jpg")
    assert len(out) <= 200


def test_is_allowed_media_by_extension():
    assert security.is_allowed_media("photo.HEIC", "") is True
    assert security.is_allowed_media("clip.mov", "video/quicktime") is True
    assert security.is_allowed_media("photo.jpg", "application/octet-stream") is True


def test_is_allowed_media_rejects_bad_type_or_ext():
    assert security.is_allowed_media("photo.jpg", "text/html") is False
    assert security.is_allowed_media("payload.exe", "") is False
