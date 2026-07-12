from pathlib import Path
from iphone_photo_drop import config, paths


def test_default_config_values():
    cfg = config.default_config()
    assert cfg.port == 8443
    assert cfg.idle_timeout_sec == 600
    assert cfg.max_pin_attempts == 5
    assert cfg.max_file_bytes == 2 * 1024**3
    assert cfg.max_session_bytes == 20 * 1024**3
    assert cfg.subnet_prefix == 24


def test_paths_are_under_home_and_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    assert paths.pictures_dir() == tmp_path / "home" / "Pictures"
    assert paths.destination_dir() == tmp_path / "home" / "Pictures" / "iPhone Drop"
    assert paths.app_data_dir() == tmp_path / "appdata" / "iPhonePhotoDrop"
