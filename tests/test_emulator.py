"""模拟器后端的单元测试：截图裁剪与坐标换算。"""

from types import SimpleNamespace

from PIL import Image

import src.utils.screenshot as screenshot_module
from src.utils.emulator import Emulator


def _fake_emulator(image: Image.Image):
    return SimpleNamespace(enabled=True, screenshot=lambda: image)


def test_screenshot_uses_full_frame_without_rect(monkeypatch):
    image = Image.new("RGB", (1136, 640), (10, 20, 30))
    monkeypatch.setattr(screenshot_module, "emulator", _fake_emulator(image))

    shot = screenshot_module.ScreenShot()

    assert shot.get_image().size == (1136, 640)


def test_screenshot_crops_rect_in_emulator_mode(monkeypatch):
    """区域 OCR 会把区域原点当作结果偏移加回去，所以必须真的裁剪。

    曾经漏掉这一步，导致模拟器模式下所有区域 OCR 都在整屏上识别，
    坐标整体偏移出画面（例如章节列表区域返回 2000+ 的 x）。
    """
    image = Image.new("RGB", (1136, 640), (10, 20, 30))
    monkeypatch.setattr(screenshot_module, "emulator", _fake_emulator(image))

    shot = screenshot_module.ScreenShot(rect=(930, 150, 206, 420))

    assert shot.get_image().size == (206, 420)


def test_emulator_tap_maps_canonical_to_device(monkeypatch):
    emulator = Emulator()
    emulator.adb_path = "adb"  # 让 _adb 不因为找不到 adb 提前返回
    emulator.serial = "127.0.0.1:16416"
    emulator.width, emulator.height = 1920, 1080
    calls = []
    monkeypatch.setattr(emulator, "_adb", lambda *args, **kwargs: calls.append(args))

    emulator.tap(251, 392)

    assert calls
    assert calls[-1][-2:] == ("424", "662")


def test_emulator_scale_uses_capture_size(monkeypatch):
    """缩放系数必须以实际截图尺寸为准（wm size 报的是设备自然方向）。"""
    emulator = Emulator()
    emulator.width, emulator.height = 1920, 1080

    assert emulator.scale() == (1920 / 1136, 1080 / 640)
