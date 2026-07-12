"""Filesystem locations, resolved from environment for testability."""
from __future__ import annotations

import os
from pathlib import Path

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
