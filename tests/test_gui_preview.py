from types import SimpleNamespace

import pytest
from PIL import Image

from src.utils.exception import CaptureUnavailableError, ViewportDetectionError


class _ComboBox:
    def currentData(self):
        return 42


class _PreviewImage:
    def __init__(self):
        self.pixmap = "previous-pixmap"
        self.set_calls = []

    def width(self):
        return 320

    def height(self):
        return 180

    def setPixmap(self, pixmap):
        self.pixmap = pixmap
        self.set_calls.append(pixmap)


class _WindowManagerWidget:
    def __init__(self):
        self.comboBox = _ComboBox()
        self.preview_image = _PreviewImage()
        self.capture_size_labels = []
        self.capture_time_labels = []

    def update_capture_size_label(self, value):
        self.capture_size_labels.append(value)

    def update_capture_time_label(self, value):
        self.capture_time_labels.append(value)


def _owner():
    widget = _WindowManagerWidget()
    return SimpleNamespace(windowManagerInterface=widget), widget


def test_preview_window_uses_explicit_handle_and_canonical_label(monkeypatch):
    import src.utils.gui as gui_module

    owner, widget = _owner()
    image = Image.new("RGB", (1136, 640), (40, 30, 20))
    captured_handles = []

    class FakeScreenShot:
        def __init__(self, *, handle):
            captured_handles.append(handle)

        def get_image(self):
            return image

    class FakePixmap:
        @staticmethod
        def fromImage(_image):
            return FakePixmap()

        def scaled(self, *_args):
            return "scaled-pixmap"

    monkeypatch.setattr(gui_module, "ScreenShot", FakeScreenShot)
    monkeypatch.setattr(gui_module, "ImageQt", lambda value: value)
    monkeypatch.setattr(gui_module, "QPixmap", FakePixmap)

    gui_module.MainWindow.preview_window(owner)

    assert captured_handles == [42]
    assert widget.preview_image.pixmap == "scaled-pixmap"
    assert widget.capture_size_labels == ["标准画面 1136 X 640"]
    assert len(widget.capture_time_labels) == 1


@pytest.mark.parametrize(
    "failure",
    [
        ViewportDetectionError(
            (800, 600),
            (0, 0, 800, 600),
            "no plausible 16:9 active rectangle",
        ),
        CaptureUnavailableError(42, 10, "capture returned None"),
    ],
    ids=["viewport-detection", "capture-unavailable"],
)
def test_preview_window_keeps_previous_pixmap_and_reports_capture_failure(
    monkeypatch, failure
):
    import src.utils.gui as gui_module

    owner, widget = _owner()
    errors = []

    class FailingScreenShot:
        def __init__(self, *, handle):
            raise failure

    def fail_imageqt(_image):
        raise AssertionError("ImageQt must not run on capture failure")

    monkeypatch.setattr(gui_module, "ScreenShot", FailingScreenShot)
    monkeypatch.setattr(gui_module.logger, "ui_error", errors.append)
    monkeypatch.setattr(gui_module, "ImageQt", fail_imageqt)

    gui_module.MainWindow.preview_window(owner)

    assert widget.preview_image.pixmap == "previous-pixmap"
    assert widget.preview_image.set_calls == []
    assert len(errors) == 1
    assert str(failure) in errors[0]
