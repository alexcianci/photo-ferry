import threading

import pytest

from photo_ferry.outbox import Outbox


def _make(tmp_path, name, data=b"IMGDATA"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_add_returns_entries_with_opaque_ids(tmp_path):
    box = Outbox()
    added = box.add([_make(tmp_path, "a.jpg"), _make(tmp_path, "b.mp4")])
    assert [e.name for e in added] == ["a.jpg", "b.mp4"]
    assert all(len(e.id) >= 16 for e in added)
    assert added[0].id != added[1].id
    assert added[0].size == 7


def test_ids_never_contain_path_characters(tmp_path):
    box = Outbox()
    entry = box.add([_make(tmp_path, "a.jpg")])[0]
    assert "/" not in entry.id and "\\" not in entry.id and "." not in entry.id


def test_get_returns_none_for_unknown_id(tmp_path):
    box = Outbox()
    box.add([_make(tmp_path, "a.jpg")])
    assert box.get("nope") is None
    assert box.get("../../etc/passwd") is None


def test_non_media_files_are_refused(tmp_path):
    box = Outbox()
    assert box.add([_make(tmp_path, "evil.exe")]) == []
    assert box.list() == []


def test_missing_paths_are_skipped(tmp_path):
    box = Outbox()
    assert box.add([tmp_path / "ghost.jpg"]) == []


def test_list_preserves_insertion_order_and_remove_works(tmp_path):
    box = Outbox()
    a, b = box.add([_make(tmp_path, "a.jpg"), _make(tmp_path, "b.jpg")])
    assert [e.id for e in box.list()] == [a.id, b.id]
    box.remove(a.id)
    assert [e.id for e in box.list()] == [b.id]
    box.clear()
    assert box.list() == []


def test_concurrent_add_and_read_is_safe(tmp_path):
    box = Outbox()
    paths = [_make(tmp_path, f"f{i}.jpg") for i in range(40)]
    errors = []

    def writer():
        try:
            for p in paths:
                box.add([p])
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    def reader():
        try:
            for _ in range(200):
                box.list()
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(box.list()) == 40


def test_ctype_is_normalized_before_it_is_stored(tmp_path, monkeypatch):
    """The stored ctype must be the value the allowlist validated, not the raw one.

    `is_allowed_media` compares a normalized string, so keeping the raw form let a type
    carrying a stray CRLF pass validation and then split the Content-Type header. Anything
    that survives normalization is one of the allowlist literals, so it is single-line by
    construction; anything that does not normalize to one is refused outright.
    """
    import photo_ferry.outbox as outbox_mod

    def poison(value):
        monkeypatch.setattr(outbox_mod, "guess_ctype", lambda name: value)

    poison("image/jpeg\r\n")
    entry = Outbox().add([_make(tmp_path, "a.jpg")])[0]
    assert entry.ctype == "image/jpeg"

    poison("  IMAGE/JPEG  ")
    assert Outbox().add([_make(tmp_path, "b.jpg")])[0].ctype == "image/jpeg"

    # A CRLF that does not vanish under normalization is a header injection attempt,
    # not a sloppy registry value, and must not produce an entry at all.
    for evil in ("image/jpeg\r\nX-Evil: 1", "image/\r\njpeg", "image/jpeg\nX-Evil: 1"):
        poison(evil)
        assert Outbox().add([_make(tmp_path, "c.jpg")]) == []


def test_stored_ctype_can_never_contain_a_newline(tmp_path, monkeypatch):
    """The invariant the header depends on, asserted directly rather than inferred."""
    import photo_ferry.outbox as outbox_mod

    for value in ("video/mp4", "VIDEO/MP4;codecs=x", "\r\nvideo/mp4", "video/mp4\r\n",
                  "application/octet-stream", "image/jpeg\r\nX-Evil: 1", "nonsense/type"):
        monkeypatch.setattr(outbox_mod, "guess_ctype", lambda name, v=value: v)
        for entry in Outbox().add([_make(tmp_path, "d.mp4")]):
            assert "\r" not in entry.ctype and "\n" not in entry.ctype
