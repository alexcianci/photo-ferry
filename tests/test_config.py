from photo_ferry import config, paths


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


def test_socket_timeouts_have_safe_defaults():
    cfg = config.default_config()
    assert cfg.handshake_timeout_sec == 10.0
    assert cfg.request_timeout_sec == 30.0
    assert cfg.transfer_timeout_sec == 300.0
    # The loose transfer deadline must stay under the session idle timeout, or an
    # abandoned transfer outlives the policy the UI is showing the user.
    assert cfg.transfer_timeout_sec < cfg.idle_timeout_sec


def test_batch_limits_have_safe_defaults():
    cfg = config.default_config()
    assert cfg.max_batch_bytes == 300 * 1024 * 1024
    assert cfg.max_batch_files == 25
