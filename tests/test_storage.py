import io

import pytest

from iphone_photo_drop import storage


def test_save_stream_writes_file(tmp_path):
    src = io.BytesIO(b"hello-bytes")
    out = storage.save_stream(src, len(b"hello-bytes"), tmp_path, "photo.jpg",
                              max_file_bytes=1024, chunk_bytes=4)
    assert out.read_bytes() == b"hello-bytes"
    assert out.name == "photo.jpg"


def test_save_stream_dedupes_name(tmp_path):
    (tmp_path / "photo.jpg").write_bytes(b"existing")
    src = io.BytesIO(b"new")
    out = storage.save_stream(src, 3, tmp_path, "photo.jpg", max_file_bytes=1024, chunk_bytes=4)
    assert out.name == "photo (1).jpg"
    assert out.read_bytes() == b"new"


def test_save_stream_rejects_oversize_and_leaves_no_residue(tmp_path):
    src = io.BytesIO(b"x" * 100)
    with pytest.raises(ValueError):
        storage.save_stream(src, 100, tmp_path, "big.mp4", max_file_bytes=10, chunk_bytes=4)
    assert list(tmp_path.iterdir()) == []


def test_save_stream_rejects_bad_filename(tmp_path):
    src = io.BytesIO(b"x")
    with pytest.raises(ValueError):
        storage.save_stream(src, 1, tmp_path, "evil.exe", max_file_bytes=10, chunk_bytes=4)
    assert list(tmp_path.iterdir()) == []


def test_save_stream_no_residue_when_rename_fails(tmp_path, monkeypatch):
    import iphone_photo_drop.storage as storage_mod

    def boom(*a, **k):
        raise OSError("rename failed")

    monkeypatch.setattr(storage_mod.os, "replace", boom)
    src = io.BytesIO(b"data")
    with pytest.raises(OSError):
        storage.save_stream(src, 4, tmp_path, "photo.jpg", max_file_bytes=1024, chunk_bytes=4)
    assert list(tmp_path.iterdir()) == []
