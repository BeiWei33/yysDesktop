"""遍历结界勋章：一个结界只截一次图。"""

from types import SimpleNamespace

import src.package.jiejietupo as jiejietupo_module
from src.package.jiejietupo import JieJieTuPoGeRen


class _FakeImage:
    """假截图对象，只记录区域与裁剪调用。"""

    def __init__(self, rect, counter):
        self.rect = rect
        self._counter = counter
        counter.append(rect)

    def get_image(self):
        return SimpleNamespace(crop=lambda box: box)


def test_union_region_covers_all_inputs():
    base = JieJieTuPoGeRen.union_region((100, 200, 205, 90), (35, 250, 205, 70))

    assert base == (35, 200, 270, 120)


def test_crop_region_is_relative_to_base():
    fake = SimpleNamespace(crop=lambda box: box)

    box = JieJieTuPoGeRen.crop_region(fake, (35, 250, 205, 70), (35, 200, 270, 140))

    assert box == (0, 50, 205, 120)


def test_list_num_xunzhang_captures_once_per_barrier(monkeypatch):
    """9 个结界只应截图 9 次（原先最多 63 次，模拟器上每次截图都是一次 adb 往返）。"""
    captures: list = []

    def fake_screen_shot(*args, **kwargs):
        rect = kwargs.get("rect") or (args[0] if args else None)
        return _FakeImage(rect, captures)

    monkeypatch.setattr(jiejietupo_module, "ScreenShot", fake_screen_shot)
    monkeypatch.setattr(
        jiejietupo_module,
        "RuleImage",
        lambda *args, **kwargs: SimpleNamespace(match=lambda *a, **k: False),
    )

    runner = object.__new__(JieJieTuPoGeRen)
    runner.tupo_geren_x = [-1, 0, 190, 380, 570]
    runner.tupo_geren_y = [-1, 0, 130, 260, 390, 520]
    runner.IMAGE_SUCCESS = object()
    for index in range(6):
        setattr(runner, f"IMAGE_XUNZHANG_{index}", object())

    result = runner.list_num_xunzhang()

    assert len(captures) == 9
    assert result[1:] == [0] * 9
