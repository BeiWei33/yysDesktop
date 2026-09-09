from types import SimpleNamespace

import pytest

import src.utils.point as point_module
from src.utils.exception import ViewportDetectionError
from src.utils.point import Point
from src.utils.viewport import ViewportTransform, viewport_registry


@pytest.fixture
def registered_transform(monkeypatch):
    transform = ViewportTransform(
        handle=7,
        capture_size=(1129, 636),
        active_capture_rect=(0, 0, 753, 424),
        screen_client_rect=(1286, 276, 753, 424),
    )
    viewport_registry.clear()
    viewport_registry.set(transform, "bitblt")
    monkeypatch.setattr(
        point_module.window_manager,
        "current",
        SimpleNamespace(handle=7),
    )
    yield transform
    viewport_registry.clear()


def test_point_to_screen_uses_registered_canonical_transform(registered_transform):
    screen_x, screen_y = Point(568, 320).to_screen()

    expected_x, expected_y = registered_transform.canonical_to_screen((568, 320))
    assert abs(screen_x - expected_x) <= 1
    assert abs(screen_y - expected_y) <= 1


def test_point_screen_round_trip_uses_registered_transform(registered_transform):
    screen = Point(568, 320).to_screen()

    restored = Point.from_screen(*screen)

    assert abs(restored.client_x - 568) <= 1
    assert abs(restored.client_y - 320) <= 1


def test_point_conversion_without_transform_fails_explicitly(monkeypatch):
    viewport_registry.clear()
    monkeypatch.setattr(
        point_module.window_manager,
        "current",
        SimpleNamespace(handle=7),
    )

    with pytest.raises(ViewportDetectionError):
        Point(568, 320).to_screen()

    with pytest.raises(ViewportDetectionError):
        Point.from_screen(1663, 488)


def test_point_conversion_accepts_explicit_handle(monkeypatch, registered_transform):
    monkeypatch.setattr(point_module.window_manager, "get_current_handle", lambda: 99)

    screen = Point(568, 320).to_screen(handle=7)
    restored = Point.from_screen(*screen, handle=7)

    assert abs(restored.client_x - 568) <= 1
    assert abs(restored.client_y - 320) <= 1


