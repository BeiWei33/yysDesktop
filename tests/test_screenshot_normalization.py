from __future__ import annotations

import io

import pytest
from PIL import Image

import src.utils.exception as exception_module
import src.utils.screenshot as screenshot_module
import src.utils.viewport as viewport_module
from src.utils.config import InteractionMode, ScreenshotMethod
from src.utils.screenshot import ScreenShot
from src.utils.window import GameWindow


def _fake_window(handle: int = 321) -> GameWindow:
    window = object.__new__(GameWindow)
    window.handle = handle
    window.client_rect = (0, 0, 1129, 636)
    window.client_left = 40
    window.client_top = 60
    window.screen_client_rect = (40, 60, 1129, 636)
    return window


def _padded_frame(color: tuple[int, int, int] = (64, 128, 192)) -> Image.Image:
    image = Image.new("RGB", (1129, 636), "black")
    image.paste(color, (0, 0, 753, 424))
    return image


@pytest.fixture(autouse=True)
def _isolate_viewport_registry():
    registry = getattr(viewport_module, "viewport_registry", None)
    if registry is not None:
        registry.clear()
    yield
    if registry is not None:
        registry.clear()


@pytest.fixture
def backend_mode(monkeypatch):
    monkeypatch.setattr(
        screenshot_module.config.user.interaction_mode,
        "mode",
        InteractionMode.BACKEND,
    )
    monkeypatch.setattr(
        screenshot_module.config.user.interaction_mode.backend,
        "screenshot_method",
        ScreenshotMethod.BITBLT,
    )


def _install_backend_frames(monkeypatch, frames):
    remaining = iter(frames)
    attempts = []

    def capture(_self, *_args):
        attempts.append(None)
        return next(remaining)

    monkeypatch.setattr(
        ScreenShot,
        "_capture_raw_backend",
        capture,
        raising=False,
    )
    return attempts


def test_full_capture_returns_canonical_image_and_exposes_raw_transform(
    monkeypatch, backend_mode
):
    raw = _padded_frame()
    _install_backend_frames(monkeypatch, [raw])

    shot = ScreenShot(handle=_fake_window())

    assert shot.get_raw_image().size == (1129, 636)
    assert shot.get_image().size == (1136, 640)
    assert shot.get_transform().active_capture_rect == (0, 0, 753, 424)


def test_canonical_region_is_cropped_after_full_frame_normalization(
    monkeypatch, backend_mode
):
    _install_backend_frames(monkeypatch, [_padded_frame()])

    shot = ScreenShot(rect=(100, 50, 200, 100), handle=_fake_window())

    assert shot.get_image().size == (200, 100)
    assert shot.get_image().getpixel((100, 50)) == (64, 128, 192)
    assert shot.get_raw_image().size == (1129, 636)


def test_none_capture_retries_ten_times_then_raises_diagnostic_error(
    monkeypatch, backend_mode
):
    attempts = _install_backend_frames(monkeypatch, [None] * 10)
    error_type = getattr(exception_module, "CaptureUnavailableError")

    with pytest.raises(error_type) as raised:
        ScreenShot(handle=_fake_window(handle=654))

    assert len(attempts) == 10
    assert raised.value.handle == 654
    assert raised.value.attempts == 10
    assert raised.value.reason == "capture returned None"
    assert "handle=654" in str(raised.value)
    assert "attempts=10" in str(raised.value)


def test_calibrated_transform_is_reused_for_black_frame_with_same_geometry(
    monkeypatch, backend_mode
):
    raw = _padded_frame()
    black = Image.new("RGB", raw.size, "black")
    attempts = _install_backend_frames(monkeypatch, [raw, black])

    first = ScreenShot(handle=_fake_window(handle=777))
    second = ScreenShot(handle=_fake_window(handle=777))

    assert len(attempts) == 2
    assert second.get_transform() is first.get_transform()
    assert second.get_image().size == (1136, 640)
    assert second.get_image().getpixel((0, 0)) == (0, 0, 0)


def test_black_frame_without_cached_transform_raises_viewport_detection_error(
    monkeypatch, backend_mode
):
    attempts = _install_backend_frames(
        monkeypatch, [Image.new("RGB", (1129, 636), "black")] * 10
    )

    with pytest.raises(viewport_module.ViewportDetectionError):
        ScreenShot(handle=_fake_window(handle=778))

    assert len(attempts) == 10


def test_capture_exception_retries_ten_times_and_chains_last_exception(
    monkeypatch, backend_mode
):
    attempts = []

    def capture(_self, *_args):
        attempts.append(None)
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(ScreenShot, "_capture_raw_backend", capture, raising=False)

    with pytest.raises(exception_module.CaptureUnavailableError) as raised:
        ScreenShot(handle=_fake_window(handle=779))

    assert len(attempts) == 10
    assert raised.value.handle == 779
    assert raised.value.attempts == 10
    assert raised.value.reason == "backend unavailable"
    assert isinstance(raised.value.__cause__, RuntimeError)


def test_int_handle_path_uses_explicit_window_even_without_current_window(
    monkeypatch, backend_mode
):
    fake_window = _fake_window(handle=780)
    monkeypatch.setattr(screenshot_module, "GameWindow", lambda handle: fake_window)
    _install_backend_frames(monkeypatch, [_padded_frame()])
    monkeypatch.setattr(screenshot_module.window_manager, "current", None)

    shot = ScreenShot(handle=780)

    assert shot.hwnd == 780
    assert shot.get_image().size == (1136, 640)


def test_gamewindow_screen_client_rect_uses_real_client_geometry(monkeypatch):
    import src.utils.window as window_module

    monkeypatch.setattr(window_module.win32gui, "GetWindowText", lambda handle: "game")
    monkeypatch.setattr(window_module.win32gui, "GetWindowRect", lambda handle: (100, 120, 1300, 900))
    monkeypatch.setattr(window_module.win32gui, "GetClientRect", lambda handle: (0, 0, 1129, 636))
    monkeypatch.setattr(window_module.win32gui, "ClientToScreen", lambda handle, point: (140, 160))

    window = window_module.GameWindow(781)

    assert window.screen_client_rect == (140, 160, 1129, 636)
    assert window.client_left == 140
    assert window.client_top == 160
    assert window.client_width == 1129
    assert window.client_height == 636


def test_front_capture_uses_screen_client_rect_and_returns_canonical_image(
    monkeypatch,
):
    window = _fake_window(handle=783)
    window.client_left = 900
    window.client_top = 901
    raw = _padded_frame()
    calls = []

    monkeypatch.setattr(
        screenshot_module.config.user.interaction_mode,
        "mode",
        InteractionMode.FRONTEND,
    )

    def grab(box):
        calls.append(box)
        return raw

    monkeypatch.setattr(screenshot_module.ImageGrab, "grab", grab)

    shot = ScreenShot(handle=window)

    assert calls == [(40, 60, 1169, 696)]
    assert shot.get_raw_image().size == (1129, 636)
    assert shot.get_image().size == (1136, 640)
    assert shot.get_transform().screen_client_rect == (40, 60, 1129, 636)


def test_capture_method_change_invalidates_transform_cache(monkeypatch, backend_mode):
    _install_backend_frames(monkeypatch, [_padded_frame(), _padded_frame()])
    fake_window = _fake_window(handle=782)

    first = ScreenShot(handle=fake_window)
    monkeypatch.setattr(
        screenshot_module.config.user.interaction_mode.backend,
        "screenshot_method",
        ScreenshotMethod.PRINTWINDOW,
    )
    second = ScreenShot(handle=fake_window)




def _uninitialized_screenshot(window=None):
    shot = object.__new__(ScreenShot)
    shot.gamewindow = window or _fake_window()
    shot.hwnd = shot.gamewindow.handle
    shot._log = False
    shot._debug = False
    shot._raw_image = None
    shot._image = None
    shot._transform = None
    shot.time_cost = 0.0
    shot.rect = None
    return shot


def test_backend_creation_failure_releases_acquired_window_and_mfc_dc(monkeypatch):
    released = []
    deleted = []
    shot = _uninitialized_screenshot()

    class FakeMfcDC:
        def CreateCompatibleDC(self):
            raise RuntimeError("compatible dc creation failed")

        def DeleteDC(self):
            deleted.append("mfc")

    monkeypatch.setattr(screenshot_module.win32gui, "GetDC", lambda hwnd: "window-dc")
    monkeypatch.setattr(
        screenshot_module.win32ui,
        "CreateDCFromHandle",
        lambda _handle: FakeMfcDC(),
    )
    monkeypatch.setattr(
        screenshot_module.win32gui,
        "ReleaseDC",
        lambda hwnd, dc: released.append((hwnd, dc)),
    )

    with pytest.raises(RuntimeError, match="compatible dc creation failed"):
        shot._capture_raw_backend(ScreenshotMethod.BITBLT)

    assert deleted == ["mfc"]
    assert released == [(shot.hwnd, "window-dc")]


def test_backend_cleanup_is_independent_and_preserves_capture_exception(monkeypatch):
    calls = []

    class FakeBitmap:
        def CreateCompatibleBitmap(self, *_args):
            calls.append("create-bitmap")

        def GetHandle(self):
            calls.append("bitmap-handle")
            return "bitmap"

        def GetInfo(self):
            raise AssertionError("capture should fail before reading bitmap")

    class FakeSaveDC:
        def SelectObject(self, _bitmap):
            calls.append("select")

        def BitBlt(self, *_args):
            calls.append("bitblt")
            raise RuntimeError("capture failed")

        def DeleteDC(self):
            calls.append("save-delete")
            raise RuntimeError("save cleanup failed")

    class FakeMfcDC:
        def CreateCompatibleDC(self):
            calls.append("create-save")
            return FakeSaveDC()

        def DeleteDC(self):
            calls.append("mfc-delete")
            raise RuntimeError("mfc cleanup failed")

    monkeypatch.setattr(screenshot_module.win32gui, "GetDC", lambda hwnd: "window-dc")
    monkeypatch.setattr(
        screenshot_module.win32ui,
        "CreateDCFromHandle",
        lambda dc: FakeMfcDC(),
    )
    monkeypatch.setattr(screenshot_module.win32ui, "CreateBitmap", lambda: FakeBitmap())
    monkeypatch.setattr(
        screenshot_module.win32gui,
        "DeleteObject",
        lambda handle: (calls.append("delete-object"), (_ for _ in ()).throw(RuntimeError("bitmap cleanup failed")))[1],
    )
    monkeypatch.setattr(
        screenshot_module.win32gui,
        "ReleaseDC",
        lambda hwnd, dc: (calls.append("release-dc"), (_ for _ in ()).throw(RuntimeError("dc cleanup failed")))[1],
    )

    with pytest.raises(RuntimeError, match="capture failed"):
        _uninitialized_screenshot()._capture_raw_backend(ScreenshotMethod.BITBLT)

    assert calls == [
        "create-save",
        "create-bitmap",
        "select",
        "bitblt",
        "bitmap-handle",
        "delete-object",
        "save-delete",
        "mfc-delete",
        "release-dc",
    ]


def test_screenshot_refreshes_same_window_geometry_before_each_capture(
    monkeypatch, backend_mode
):
    window = _fake_window(handle=784)
    states = [
        (40, 60, 1129, 636),
        (80, 90, 1000, 562),
    ]
    refresh_calls = []

    def refresh_client_geometry():
        state = states[len(refresh_calls)]
        refresh_calls.append(state)
        left, top, width, height = state
        window.client_rect = (0, 0, width, height)
        window.client_left = left
        window.client_top = top
        window.screen_client_rect = state

    window.refresh_client_geometry = refresh_client_geometry
    _install_backend_frames(monkeypatch, [_padded_frame(), _padded_frame()])

    first = ScreenShot(handle=window)
    second = ScreenShot(handle=window)

    assert refresh_calls == states
    assert first.get_transform().screen_client_rect == states[0]
    assert second.get_transform().screen_client_rect == states[1]
    assert second.get_transform() is not first.get_transform()


def test_last_mixed_failure_type_controls_final_exception(monkeypatch, backend_mode):
    black = Image.new("RGB", (1129, 636), "black")
    calls = []
    monkeypatch.setattr(screenshot_module.time, "sleep", lambda _seconds: None)

    def capture(_self, *_args):
        calls.append(len(calls))
        if len(calls) == 1:
            return black
        raise RuntimeError("last backend failure")

    monkeypatch.setattr(ScreenShot, "_capture_raw_backend", capture, raising=False)

    with pytest.raises(exception_module.CaptureUnavailableError) as raised:
        ScreenShot(handle=_fake_window(handle=785))

    assert len(calls) == 10
    assert raised.value.reason == "last backend failure"
    assert isinstance(raised.value.__cause__, RuntimeError)


def test_compatibility_wrapper_keeps_public_image_canonical_and_uses_method_key(
    monkeypatch, backend_mode
):
    first_raw = _padded_frame()
    second_raw = _padded_frame((20, 100, 180))
    _install_backend_frames(monkeypatch, [first_raw])
    shot = ScreenShot(handle=_fake_window(handle=786))
    first_transform = shot.get_transform()

    monkeypatch.setattr(
        ScreenShot,
        "_capture_raw_backend",
        lambda _self, *_args: second_raw,
        raising=False,
    )
    returned = shot._screenshot_backend(None, ScreenshotMethod.PRINTWINDOW)

    assert returned is second_raw
    assert shot.get_raw_image() is second_raw
    assert shot.get_image().size == (1136, 640)
    assert shot.get_transform() is not first_transform
    assert (
        viewport_module.viewport_registry.get(
            shot.hwnd,
            "backend:PrintWindow",
            second_raw.size,
            shot.get_transform().screen_client_rect,
        )
        is shot.get_transform()
    )

    output = io.BytesIO()
    shot.save(output, format="PNG")
    output.seek(0)
    assert Image.open(output).size == (1136, 640)
