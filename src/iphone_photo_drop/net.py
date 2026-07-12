"""LAN address detection and subnet/port checks. No outbound packets are sent."""
from __future__ import annotations

import ipaddress
import socket


def is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


def detect_lan_ip() -> str:
    """Return the primary IPv4 address of this host without sending traffic.

    Connecting a UDP socket only selects a source interface; no packet is sent.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        s.close()
    if not is_private_ip(ip):
        raise RuntimeError(f"no private LAN address found (got {ip!r})")
    return ip


def client_in_subnet(client_ip: str, server_ip: str, prefix: int = 24) -> bool:
    try:
        server = ipaddress.ip_address(server_ip)
        client = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    if server.is_loopback:
        return client.is_loopback
    network = ipaddress.ip_network(f"{server_ip}/{prefix}", strict=False)
    return client in network


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0
