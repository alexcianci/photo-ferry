"""Filesystem locations, resolved from environment for testability."""
from __future__ import annotations

import os
from pathlib import Path

# Deliberately keeps the pre-rename name. This directory holds the local CA that
# existing installs have already trusted on their phones; renaming it orphans that
# trust and brings the "not private" certificate warning back for every user.
# Do not "fix" this to match the project name.
APP_DIR_NAME = "iPhonePhotoDrop"
DEST_FOLDER_NAME = "iPhone Drop"


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def pictures_dir() -> Path:
    return _home() / "Pictures"


def destination_dir() -> Path:
    return pictures_dir() / DEST_FOLDER_NAME


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else (_home() / "AppData" / "Local")
    return root / APP_DIR_NAME


def cert_path() -> Path:
    return app_data_dir() / "cert.pem"


def key_path() -> Path:
    return app_data_dir() / "key.pem"


def ca_cert_path() -> Path:
    return app_data_dir() / "ca.pem"


def ca_key_path() -> Path:
    return app_data_dir() / "ca-key.pem"


def cert_ip_marker() -> Path:
    return app_data_dir() / "cert-ip.txt"
