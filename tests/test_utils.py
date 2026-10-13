from app.core.utils import (
    coerce_bool,
    ensure_dir,
    env_bool,
    filename_timestamp,
    redact_url,
    safe_float,
    safe_int,
    utc_now_iso,
    valid_camera_name,
)


def test_coerce_bool():
    assert coerce_bool("true") is True
    assert coerce_bool("false") is False
    assert coerce_bool("0") is False
    assert coerce_bool("si") is True
    assert coerce_bool(None, True) is True
    assert coerce_bool("maybe", True) is True


def test_valid_camera_name():
    assert valid_camera_name("patio_1")
    assert not valid_camera_name("api")
    assert not valid_camera_name("bad/name")


def test_safe_int_and_float():
    assert safe_int("7", 0) == 7
    assert safe_int("x", 5) == 5
    assert safe_float("1.5", 0.0) == 1.5
    assert safe_float(None, 2.0) == 2.0


def test_redact_url():
    assert redact_url("rtsp://admin:secret@10.0.0.1:554/live") == "rtsp://admin:***@10.0.0.1:554/live"
    assert redact_url("rtsp://10.0.0.1/live") == "rtsp://10.0.0.1/live"
    assert redact_url("rtsp://u:p@host:notaport/live") == "rtsp://u:***@host/live"


def test_time_helpers_and_filename():
    assert utc_now_iso().endswith("Z")
    assert len(filename_timestamp()) >= 19


def test_ensure_dir_and_env_bool(monkeypatch, tmp_path):
    target = tmp_path / "a" / "b"
    assert ensure_dir(target) == target and target.is_dir()
    monkeypatch.setenv("CF_TEST_FLAG", "yes")
    assert env_bool("CF_TEST_FLAG") is True
    assert env_bool("CF_TEST_MISSING", True) is True
