from doomsday_watch.formats import format_depth_guidance, normalise_format


def test_infinity_vision_is_not_imax():
    fmt = normalise_format("MS INFINITY VISION 3D")
    assert fmt["key"] == "infinity_vision_3d"
    assert fmt["is_3d"] is True
    assert fmt["is_premium"] is True
    assert "IMAX" not in fmt["label"]
    assert fmt["key"] != normalise_format("IMAX 3D")["key"]


def test_imax_3d():
    fmt = normalise_format("IMAX 3D")
    assert fmt["key"] == "imax_3d"
    assert fmt["is_3d"] is True
    assert fmt["is_large_format"] is True


def test_infinity_vision_4dx_3d_is_distinct():
    fmt = normalise_format("MS INFINITY VISION 4DX-3D")
    assert fmt["key"] == "infinity_vision_4dx_3d"
    assert fmt["is_3d"] is True


def test_plain_3d_and_2d():
    assert normalise_format("3D")["key"] == "3d"
    assert normalise_format("2D")["key"] == "2d"
    assert normalise_format("2D")["is_3d"] is False


def test_dolby_and_screenx():
    assert normalise_format("DOLBY CINEMA 3D")["key"] == "dolby_3d"
    assert normalise_format("SCREEN X 2D")["key"] == "screenx_2d"
    assert normalise_format("P[XL] 3D")["key"] == "pxl_3d"


def test_unknown_is_not_guessed():
    fmt = normalise_format("")
    assert fmt["key"] == "unknown"
    assert fmt["is_3d"] is None
    assert fmt["confidence"] == "unknown"
    assert normalise_format("MSO SPECIAL")["key"] == "unknown"


def test_depth_guidance_differs_for_imax_and_4dx():
    imax = format_depth_guidance("imax_3d")
    motion = format_depth_guidance("4dx_3d")
    assert imax[0] > motion[0]
    assert 0.4 < motion[1] < imax[1] <= 1.0
