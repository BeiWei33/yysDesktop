import numpy as np
import pytest
from PIL import Image

from src.utils.viewport import (
    ViewportDetectionError,
    ViewportRegistry,
    ViewportTransform,
    detect_active_rect,
)


def _content(size=(1136, 640)):
    image = Image.new("RGB", size, (40, 30, 20))
    for x in range(0, size[0], 20):
        image.putpixel((x, size[1] // 2), (200, 120, 60))
    return image


@pytest.mark.parametrize(
    ("canvas_size", "offset", "expected"),
    [
        ((1704, 960), (0, 0), (0, 0, 1136, 640)),
        ((1704, 960), (284, 160), (284, 160, 1420, 800)),
        ((1129, 636), (0, 0), (0, 0, 753, 424)),
    ],
)
def test_detects_active_rect_inside_black_padding(canvas_size, offset, expected):
    raw = Image.new("RGB", canvas_size, "black")
    content_size = (753, 424) if canvas_size == (1129, 636) else (1136, 640)
    raw.paste(_content(content_size), offset)

    assert detect_active_rect(raw) == expected


def test_ignores_rgb_zero_to_eight_noise_in_padding():
    pixels = np.random.default_rng(7).integers(0, 9, size=(960, 1704, 3), dtype=np.uint8)
    raw = Image.fromarray(pixels, "RGB")
    raw.paste(_content(), (284, 160))

    assert detect_active_rect(raw) == (284, 160, 1420, 800)


def test_corrects_low_complexity_bottom_strip_before_large_inactive_padding():
    raw = Image.new("RGB", (1129, 636), "black")
    raw.paste(_content((753, 424)), (0, 0))
    raw.paste((32, 24, 16), (0, 424, 753, 427))

    assert detect_active_rect(raw) == (0, 0, 753, 424)


@pytest.mark.parametrize(
    "dark_box",
    [
        (0, 0, 1136, 2),
        (0, 638, 1136, 640),
        (0, 0, 2, 640),
        (1134, 0, 1136, 640),
    ],
    ids=["top", "bottom", "left", "right"],
)
def test_preserves_up_to_four_pixel_inactive_band_at_image_edge(dark_box):
    raw = _content()
    raw.paste((8, 8, 8), dark_box)

    assert detect_active_rect(raw) == (0, 0, 1136, 640)


def test_does_not_correct_high_texture_bottom_strip():
    raw = Image.new("RGB", (1129, 636), "black")
    raw.paste(_content((753, 424)), (0, 0))
    for y in range(424, 427):
        for x in range(753):
            raw.putpixel((x, y), (220, 80, 30) if x % 2 else (30, 80, 220))

    assert detect_active_rect(raw) == (0, 0, 753, 427)


def test_corrects_low_complexity_top_strip_after_large_inactive_padding():
    raw = Image.new("RGB", (753, 527), "black")
    raw.paste((32, 24, 16), (0, 100, 753, 103))
    raw.paste(_content((753, 424)), (0, 103))

    assert detect_active_rect(raw) == (0, 103, 753, 527)


def test_corrects_low_complexity_right_strip_before_large_inactive_padding():
    raw = Image.new("RGB", (1129, 636), "black")
    raw.paste(_content((753, 424)), (0, 0))
    raw.paste((32, 24, 16), (753, 0, 756, 424))

    assert detect_active_rect(raw) == (0, 0, 753, 424)


def test_does_not_correct_high_texture_right_strip():
    raw = Image.new("RGB", (1129, 636), "black")
    raw.paste(_content((753, 424)), (0, 0))
    for x in range(753, 756):
        for y in range(424):
            raw.putpixel((x, y), (220, 80, 30) if y % 2 else (30, 80, 220))

    assert detect_active_rect(raw) == (0, 0, 756, 424)


def test_corrects_low_complexity_left_strip_after_large_inactive_padding():
    raw = Image.new("RGB", (856, 424), "black")
    raw.paste((32, 24, 16), (100, 0, 103, 424))
    raw.paste(_content((753, 424)), (103, 0))

    assert detect_active_rect(raw) == (103, 0, 856, 424)


def test_accepts_384_by_216_minimum_active_rect():
    raw = _content((384, 216))

    assert detect_active_rect(raw) == (0, 0, 384, 216)


def test_rejects_previous_320_by_180_minimum():
    raw = _content((320, 180))

    with pytest.raises(ViewportDetectionError):
        detect_active_rect(raw)


@pytest.mark.parametrize(
    "raw",
    [
        Image.new("RGB", (800, 600), (30, 30, 30)),
        Image.new("RGB", (1136, 640), "black"),
        Image.new("RGB", (100, 50), (30, 30, 30)),
    ],
    ids=["four_by_three", "fully_black", "too_small"],
)
def test_rejects_untrustworthy_active_rect(raw):
    with pytest.raises(ViewportDetectionError) as exc_info:
        detect_active_rect(raw)

    message = str(exc_info.value)
    assert str(raw.size) in message
    assert "candidate_rect" in message
    assert "reason" in message


def _transform():
    return ViewportTransform(
        handle=7,
        capture_size=(1129, 636),
        active_capture_rect=(10, 20, 763, 444),
        screen_client_rect=(1286, 276, 753, 424),
    )


def test_normalizes_active_rect_to_canonical_size_after_cropping():
    raw = Image.new("RGB", (1129, 636), "black")
    raw.paste(Image.new("RGB", (753, 424), (40, 30, 20)), (10, 20))

    normalized = _transform().normalize(raw)

    assert normalized.size == (1136, 640)
    assert normalized.getpixel((0, 0)) == (40, 30, 20)
    assert normalized.getpixel((1135, 639)) == (40, 30, 20)


def test_identity_transform_preserves_canonical_image():
    raw = _content()
    transform = ViewportTransform(
        handle=8,
        capture_size=(1136, 640),
        active_capture_rect=(0, 0, 1136, 640),
        screen_client_rect=(100, 200, 1136, 640),
    )

    normalized = transform.normalize(raw)

    assert normalized.size == (1136, 640)
    assert normalized.tobytes() == raw.tobytes()


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((0, 0), (10, 20)),
        ((568, 320), (386, 232)),
        ((1135, 639), (762, 443)),
    ],
)
def test_maps_canonical_points_to_backend_active_rect(point, expected):
    assert _transform().canonical_to_backend(point) == expected


@pytest.mark.parametrize("point", [(0, 0), (568, 320), (1135, 639)])
def test_backend_round_trip_is_within_one_pixel(point):
    transform = _transform()

    native = transform.canonical_to_backend(point)
    restored = transform.backend_to_canonical(native)

    assert abs(restored[0] - point[0]) <= 1
    assert abs(restored[1] - point[1]) <= 1


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((0, 0), (1286, 276)),
        ((568, 320), (1662, 488)),
        ((1135, 639), (2038, 699)),
    ],
)
def test_maps_canonical_points_to_real_screen_client_rect(point, expected):
    assert _transform().canonical_to_screen(point) == expected


@pytest.mark.parametrize("point", [(0, 0), (568, 320), (1135, 639)])
def test_screen_round_trip_is_within_one_pixel(point):
    transform = _transform()

    native = transform.canonical_to_screen(point)
    restored = transform.screen_to_canonical(native)

    assert abs(restored[0] - point[0]) <= 1
    assert abs(restored[1] - point[1]) <= 1


def test_point_conversions_clamp_inputs_before_mapping():
    transform = _transform()

    assert transform.canonical_to_backend((-50, 9999)) == transform.canonical_to_backend((0, 639))
    assert transform.canonical_to_screen((-50, 9999)) == transform.canonical_to_screen((0, 639))
    assert transform.backend_to_canonical((-50, 9999)) == transform.backend_to_canonical((10, 443))
    assert transform.screen_to_canonical((-50, 9999)) == transform.screen_to_canonical((1286, 699))


@pytest.mark.parametrize("native_size", [(384, 216), (2272, 1280)])
def test_point_mappings_preserve_closed_interval_endpoints(native_size):
    width, height = native_size
    transform = ViewportTransform(
        handle=9,
        capture_size=native_size,
        active_capture_rect=(0, 0, width, height),
        screen_client_rect=(100, 200, width, height),
    )

    assert transform.canonical_to_backend((0, 0)) == (0, 0)
    assert transform.canonical_to_backend((1135, 639)) == (width - 1, height - 1)
    assert transform.backend_to_canonical((0, 0)) == (0, 0)
    assert transform.backend_to_canonical((width - 1, height - 1)) == (1135, 639)
    assert transform.canonical_to_screen((0, 0)) == (100, 200)
    assert transform.canonical_to_screen((1135, 639)) == (100 + width - 1, 200 + height - 1)
    assert transform.screen_to_canonical((100, 200)) == (0, 0)
    assert transform.screen_to_canonical((100 + width - 1, 200 + height - 1)) == (1135, 639)


@pytest.mark.parametrize("native_size", [(384, 216), (2272, 1280)])
def test_point_mappings_round_trip_entire_axis_ranges_within_one_pixel(native_size):
    width, height = native_size
    transform = ViewportTransform(
        handle=9,
        capture_size=native_size,
        active_capture_rect=(0, 0, width, height),
        screen_client_rect=(100, 200, width, height),
    )

    for canonical_x in range(1136):
        backend_x = transform.canonical_to_backend((canonical_x, 0))[0]
        screen_x = transform.canonical_to_screen((canonical_x, 0))[0]
        assert abs(transform.backend_to_canonical((backend_x, 0))[0] - canonical_x) <= 1
        assert abs(transform.screen_to_canonical((screen_x, 200))[0] - canonical_x) <= 1
    for canonical_y in range(640):
        backend_y = transform.canonical_to_backend((0, canonical_y))[1]
        screen_y = transform.canonical_to_screen((0, canonical_y))[1]
        assert abs(transform.backend_to_canonical((0, backend_y))[1] - canonical_y) <= 1
        assert abs(transform.screen_to_canonical((100, screen_y))[1] - canonical_y) <= 1

    for backend_x in range(width):
        canonical_x = transform.backend_to_canonical((backend_x, 0))[0]
        assert abs(transform.canonical_to_backend((canonical_x, 0))[0] - backend_x) <= 1
    for backend_y in range(height):
        canonical_y = transform.backend_to_canonical((0, backend_y))[1]
        assert abs(transform.canonical_to_backend((0, canonical_y))[1] - backend_y) <= 1
    for screen_x in range(100, 100 + width):
        canonical_x = transform.screen_to_canonical((screen_x, 200))[0]
        assert abs(transform.canonical_to_screen((canonical_x, 0))[0] - screen_x) <= 1
    for screen_y in range(200, 200 + height):
        canonical_y = transform.screen_to_canonical((100, screen_y))[1]
        assert abs(transform.canonical_to_screen((0, canonical_y))[1] - screen_y) <= 1


def test_canonical_to_input_uses_client_size_not_capture_active_rect():
    transform = ViewportTransform(
        handle=10,
        capture_size=(1129, 636),
        active_capture_rect=(0, 0, 753, 424),
        screen_client_rect=(774, 734, 1129, 636),
    )

    assert transform.canonical_to_input((152, 539)) == (151, 536)
    assert transform.input_to_canonical((151, 536)) == (152, 539)


    region = _transform().canonical_region_to_capture((100, 50, 200, 100))

    assert region == (76, 53, 133, 66)
    left, top, width, height = region
    assert 10 <= left < left + width <= 763
    assert 20 <= top < top + height <= 444


def test_intersects_negative_region_origin_with_canonical_canvas_before_mapping():
    assert _transform().canonical_region_to_capture((-100, -50, 200, 100)) == (10, 20, 66, 33)


def test_clamps_region_fully_outside_canonical_bounds_without_negative_size():
    assert _transform().canonical_region_to_capture((1200, 700, 100, 100)) == (763, 444, 0, 0)


def _registry_transform(handle, capture_size, active_rect, screen_rect):
    return ViewportTransform(
        handle=handle,
        capture_size=capture_size,
        active_capture_rect=active_rect,
        screen_client_rect=screen_rect,
    )


def test_registry_isolates_transforms_by_handle():
    registry = ViewportRegistry()
    first = _registry_transform(1, (1129, 636), (0, 0, 753, 424), (10, 20, 753, 424))
    second = _registry_transform(2, (1136, 640), (0, 0, 1136, 640), (30, 40, 1136, 640))
    registry.set(first, "bitblt")
    registry.set(second, "printwindow")

    assert registry.get(1, "bitblt", (1129, 636), (10, 20, 753, 424)) is first
    assert registry.get(2, "printwindow", (1136, 640), (30, 40, 1136, 640)) is second


@pytest.mark.parametrize(
    ("capture_method", "capture_size", "screen_rect"),
    [
        ("printwindow", (1129, 636), (10, 20, 753, 424)),
        ("bitblt", (1136, 640), (10, 20, 753, 424)),
        ("bitblt", (1129, 636), (11, 20, 753, 424)),
    ],
    ids=["capture_method", "capture_size", "screen_geometry"],
)
def test_registry_invalidates_changed_geometry(capture_method, capture_size, screen_rect):
    registry = ViewportRegistry()
    transform = _registry_transform(1, (1129, 636), (0, 0, 753, 424), (10, 20, 753, 424))
    registry.set(transform, "bitblt")

    assert registry.get(1, capture_method, capture_size, screen_rect) is None
    assert registry.get(1, "bitblt", (1129, 636), (10, 20, 753, 424)) is None


def test_registry_reuses_cached_transform_for_unchanged_black_frame_geometry():
    registry = ViewportRegistry()
    transform = _registry_transform(1, (1129, 636), (0, 0, 753, 424), (10, 20, 753, 424))
    registry.set(transform, "bitblt")
    black_frame = Image.new("RGB", transform.capture_size, "black")

    with pytest.raises(ViewportDetectionError):
        detect_active_rect(black_frame)

    assert registry.get(1, "bitblt", black_frame.size, (10, 20, 753, 424)) is transform


def test_registry_can_invalidate_one_handle_and_clear_all():
    registry = ViewportRegistry()
    first = _registry_transform(1, (1129, 636), (0, 0, 753, 424), (10, 20, 753, 424))
    second = _registry_transform(2, (1136, 640), (0, 0, 1136, 640), (30, 40, 1136, 640))
    registry.set(first, "bitblt")
    registry.set(second, "printwindow")

    registry.invalidate(1)
    assert registry.get(1, "bitblt", (1129, 636), (10, 20, 753, 424)) is None
    assert registry.get(2, "printwindow", (1136, 640), (30, 40, 1136, 640)) is second

    registry.clear()
    assert registry.get(2, "printwindow", (1136, 640), (30, 40, 1136, 640)) is None


def test_screenshot_explicit_handles_keep_independent_canonical_transforms(monkeypatch):
    """Each explicit HWND owns its calibration, including raw-size changes."""
    import src.utils.screenshot as screenshot_module
    from src.utils.config import InteractionMode
    from src.utils.screenshot import ScreenShot

    class FakeWindow:
        def __init__(self, handle):
            self.handle = int(handle)
            self.client_rect = (0, 0, 1136, 640)
            self.screen_client_rect = (100 * handle, 200, 1136, 640)
            self._geometry_refresh_enabled = False

    def frame(size, active_rect, color):
        image = Image.new("RGB", size, "black")
        left, top, right, bottom = active_rect
        image.paste(color, (left, top, right, bottom))
        return image

    frames = {
        1: [frame((1129, 636), (0, 0, 753, 424), (50, 90, 130))],
        2: [frame((1704, 960), (284, 160, 1420, 800), (80, 120, 160))],
    }
    windows = {handle: FakeWindow(handle) for handle in (1, 2)}
    detect_calls = []

    monkeypatch.setattr(screenshot_module, "GameWindow", lambda handle: windows[int(handle)])
    monkeypatch.setattr(
        screenshot_module.config.user.interaction_mode,
        "mode",
        InteractionMode.FRONTEND,
    )
    monkeypatch.setattr(
        screenshot_module,
        "detect_active_rect",
        lambda image: (
            detect_calls.append(image.size)
            or ((0, 0, 753, 424) if image.size == (1129, 636) else (284, 160, 1420, 800))
        ),
    )
    monkeypatch.setattr(
        ScreenShot,
        "_capture_raw_front",
        lambda self: frames[self.hwnd].pop(0),
    )

    import src.utils.viewport as viewport_module

    viewport_module.viewport_registry.clear()
    first = ScreenShot(handle=1)
    second = ScreenShot(handle=2)
    first_transform = first.get_transform()
    second_transform = second.get_transform()

    assert len(viewport_module.viewport_registry._entries) == 2
    assert first.get_image().size == (1136, 640)
    assert second.get_image().size == (1136, 640)

    windows[1].client_rect = (0, 0, 1704, 960)
    windows[1].screen_client_rect = (100, 200, 1704, 960)
    frames[1].append(frame((1704, 960), (284, 160, 1420, 800), (90, 130, 170)))
    changed = ScreenShot(handle=1)

    assert changed.get_image().size == (1136, 640)
    assert changed.get_transform() is not first_transform
    assert changed.get_transform().capture_size == (1704, 960)
    assert viewport_module.viewport_registry.current(2) is second_transform
    assert detect_calls == [(1129, 636), (1704, 960), (1704, 960)]
