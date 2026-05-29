from app.core.utils import coerce_bool, valid_camera_name


def test_coerce_bool():
    assert coerce_bool("true") is True
    assert coerce_bool("false") is False
    assert coerce_bool("0") is False
    assert coerce_bool("si") is True


def test_valid_camera_name():
    assert valid_camera_name("patio_1")
    assert not valid_camera_name("api")
    assert not valid_camera_name("bad/name")
