from types import SimpleNamespace

import pytest

import src.package.tansuo as tansuo_module
from src.package.tansuo import TanSuo as ProductionTanSuo
from src.package.tansuo import TanSuoChapterUnavailable

from .utils import Package, check_package


class TanSuo(Package):
    resource_path = "tansuo"


def test_tansuo_drag_bounds_are_canonical():
    assert ProductionTanSuo.view_drag_bounds() == (568, 1022)


def test_tansuo():
    check_package(TanSuo)


def _make_runner(monkeypatch, ready_after: int, start_visible: bool = True):
    """按章节列表滑动次数模拟28章何时出现。"""
    runner = object.__new__(ProductionTanSuo)
    runner.IMAGE_TITLE_28 = object()
    runner.IMAGE_TANSUO_28 = object()
    runner.IMAGE_START = object()
    runner.chapter_miss_count = 0
    runner.chapter_fix_failures = 0

    state = {"scrolled": 0}
    events = []

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            if self.asset is runner.IMAGE_TITLE_28:
                return state["scrolled"] >= ready_after
            if self.asset is runner.IMAGE_START:
                return start_visible
            return False

    def move(point=None, **kwargs):
        events.append(("move", point))

    def scroll(distance):
        state["scrolled"] += 1
        events.append(("scroll", distance))

    def drag(x_offset=None, y_offset=None, duration=None):
        state["scrolled"] += 1
        events.append(("drag", x_offset, y_offset))

    monkeypatch.setattr(tansuo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(
        tansuo_module,
        "Mouse",
        SimpleNamespace(move=move, scroll=scroll, drag=drag, click=lambda *a, **k: None),
    )
    monkeypatch.setattr(tansuo_module, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(tansuo_module, "random_num", lambda a, b: a)

    return runner, state, events


def test_chapter_ready_returns_true_when_title_visible(monkeypatch):
    runner, _, events = _make_runner(monkeypatch, ready_after=0)

    assert runner.chapter_ready() is True
    assert events == []


def test_chapter_ready_clicks_visible_entry_and_waits_for_title(monkeypatch):
    runner = object.__new__(ProductionTanSuo)
    runner.IMAGE_TITLE_28 = object()
    runner.IMAGE_TANSUO_28 = object()
    checks = {"title": 0}
    clicks = []

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            if self.asset is runner.IMAGE_TITLE_28:
                checks["title"] += 1
                # 点击后需要等几帧标题才出现
                return checks["title"] >= 3
            return True

        def center_point(self):
            return "entry"

    monkeypatch.setattr(tansuo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(tansuo_module, "Mouse", SimpleNamespace(click=clicks.append))
    monkeypatch.setattr(tansuo_module, "sleep", lambda *args, **kwargs: None)

    assert runner.chapter_ready() is True
    assert clicks == ["entry"]
    assert checks["title"] >= 3


def test_ensure_chapter_28_drags_until_chapter_appears(monkeypatch):
    runner, state, events = _make_runner(monkeypatch, ready_after=3)

    assert runner.ensure_chapter_28() is True
    assert state["scrolled"] == 3
    # 每次拖动前都要把指针移到章节列表上，方向为向列表末尾翻
    assert [event[0] for event in events] == ["move", "drag"] * 3
    assert [event[2] for event in events if event[0] == "drag"] == [runner.chapter_scroll_distance * -1] * 3


def test_ensure_chapter_28_falls_back_to_wheel(monkeypatch):
    attempts = ProductionTanSuo.chapter_scroll_attempts
    # 拖动两个方向都试完后仍然没有28章，改用滚轮
    runner, _, events = _make_runner(monkeypatch, ready_after=attempts * 2 + 1)

    assert runner.ensure_chapter_28() is True
    kinds = [event[0] for event in events if event[0] != "move"]
    assert kinds.count("drag") == attempts * 2
    assert kinds.count("scroll") == 1
    assert events[0][0] == "move"


def test_ensure_chapter_28_returns_none_outside_tansuo_screen(monkeypatch):
    runner, state, _ = _make_runner(monkeypatch, ready_after=1, start_visible=False)

    assert runner.ensure_chapter_28() is None
    assert state["scrolled"] == 0


def test_ensure_chapter_28_gives_up_after_bounded_attempts(monkeypatch):
    runner, state, _ = _make_runner(monkeypatch, ready_after=10**6)

    assert runner.ensure_chapter_28() is False
    assert state["scrolled"] == ProductionTanSuo.chapter_scroll_attempts * 4


def test_try_fix_chapter_waits_before_first_attempt(monkeypatch):
    runner, state, _ = _make_runner(monkeypatch, ready_after=1)
    runner.chapter_fix_interval = 3

    runner.try_fix_chapter()
    runner.try_fix_chapter()
    assert state["scrolled"] == 0
    assert runner.chapter_miss_count == 2

    runner.try_fix_chapter()
    assert state["scrolled"] == 1
    assert runner.chapter_miss_count == 0
    assert runner.chapter_fix_failures == 0


def test_try_fix_chapter_does_not_count_absence_from_screen(monkeypatch):
    runner, _, _ = _make_runner(monkeypatch, ready_after=1, start_visible=False)
    runner.chapter_fix_interval = 1

    for _ in range(ProductionTanSuo.chapter_fix_max_failures):
        runner.try_fix_chapter()

    assert runner.chapter_fix_failures == 0


def test_try_fix_chapter_stops_after_repeated_failures(monkeypatch):
    runner, _, _ = _make_runner(monkeypatch, ready_after=10**6)
    runner.chapter_fix_interval = 1

    for _ in range(ProductionTanSuo.chapter_fix_max_failures - 1):
        runner.try_fix_chapter()

    with pytest.raises(TanSuoChapterUnavailable):
        runner.try_fix_chapter()
