import socket

from iphone_photo_drop import net


def test_is_private_ip():
    assert net.is_private_ip("192.168.1.5") is True
    assert net.is_private_ip("10.0.0.9") is True
    assert net.is_private_ip("172.16.4.4") is True
    assert net.is_private_ip("127.0.0.1") is True
    assert net.is_private_ip("8.8.8.8") is False


def test_client_in_subnet_prefix_24():
    assert net.client_in_subnet("192.168.1.50", "192.168.1.10", 24) is True
    assert net.client_in_subnet("192.168.2.50", "192.168.1.10", 24) is False


def test_client_in_subnet_allows_loopback_when_server_is_loopback():
    assert net.client_in_subnet("127.0.0.1", "127.0.0.1", 24) is True


def test_detect_lan_ip_returns_private_address():
    ip = net.detect_lan_ip()
    assert net.is_private_ip(ip)


def test_port_in_use_detects_open_socket():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        assert net.port_in_use("127.0.0.1", port) is True
    assert net.port_in_use("127.0.0.1", port) is False
