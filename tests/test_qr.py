from iphone_photo_drop import qr


def test_png_bytes_are_valid_png():
    data = qr.png_bytes("https://192.168.1.10:8443/?t=abc", scale=4)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 100


def test_receiver_url_shape():
    url = qr.receiver_url("192.168.1.10", 8443, "TOKEN123")
    assert url == "https://192.168.1.10:8443/?t=TOKEN123"
