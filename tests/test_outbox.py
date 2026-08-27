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
