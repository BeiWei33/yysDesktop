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


def _make_runner(
    monkeypatch,
    ready_after: int,
    list_visible: bool = True,
    list_moves: bool = True,
    detail_chapter: int | None = None,
    entry_visible: bool = False,
    click_polls: int = 0,
    back_visible: bool = False,
):
    """按章节列表滑动次数模拟28章何时出现。

    Args:
        ready_after: 滑动多少次后28章出现（标题识别成功）
        list_visible: 章节列表是否能识别到「第X章」
        list_moves: 滑动后列表内容是否变化
        detail_chapter: 章节详情页左上角识别到的章节号
        entry_visible: 章节列表里是否能看到「第二十八章」
        click_polls: 点击28章后还要等几次检查才出现标题
        back_visible: 详情页左上角是否能识别到返回按钮
    """
    runner = object.__new__(ProductionTanSuo)
    runner.IMAGE_TITLE_28 = object()
    runner.IMAGE_TANSUO_28 = object()
    runner.IMAGE_QUIT = object()
    runner.chapter_miss_count = 0
    runner.chapter_fix_failures = 0

    state = {
        "scrolled": 0,
        "entry_clicks": 0,
        "polls": 0,
        "in_detail": detail_chapter is not None,
    }
    events = []

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            if self.asset is runner.IMAGE_TITLE_28:
                if state["entry_clicks"]:
                    state["polls"] += 1
                    return state["polls"] > click_polls
                return state["scrolled"] >= ready_after
            if self.asset is runner.IMAGE_QUIT:
                return back_visible and state["in_detail"]
            return False

        def center_point(self):
            return "back"

    def move(point=None, **kwargs):
        events.append(("move", point))

    def scroll(distance):
        state["scrolled"] += 1
        events.append(("scroll", distance))

    def drag(x_offset=None, y_offset=None, duration=None):
        state["scrolled"] += 1
        events.append(("drag", x_offset, y_offset))

    def click(point=None, **kwargs):
        events.append(("click", point))
        if point == "back":
            state["in_detail"] = False
        else:
            state["entry_clicks"] += 1

    def list_result():
        if state["in_detail"] or not (list_visible or entry_visible):
            return []
        # 列表可见时至少识别到两个章节；滑动有效时内容会变化，但不会滑动到28章
        first = 1 + (state["scrolled"] % 26 if list_moves else 0)
        texts = [f"第{first}章", f"第{first + 1}章"]
        if entry_visible:
            texts.append(f"第{runner.target_chapter}章")
        return [SimpleNamespace(text=text, center=f"point-{text}") for text in texts]

    def detail_result():
        if not state["in_detail"] or detail_chapter is None:
            return []
        return [SimpleNamespace(text=f"第{detail_chapter}章", center="detail")]

    def fake_ocr(*args, **kwargs):
        region = kwargs.get("region")
        if region == ProductionTanSuo.chapter_number_region:
            return SimpleNamespace(get_raw_result=detail_result)
        return SimpleNamespace(get_raw_result=list_result)

    monkeypatch.setattr(tansuo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(tansuo_module, "RuleOcr", fake_ocr)
    monkeypatch.setattr(
        tansuo_module,
        "Mouse",
        SimpleNamespace(move=move, scroll=scroll, drag=drag, click=click),
    )
    monkeypatch.setattr(tansuo_module, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(tansuo_module, "random_num", lambda a, b: a)

    return runner, state, events


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("第二十八章", 28),
        ("第一章", 1),
        ("第十章", 10),
        ("第二十章", 20),
        ("第三十一章", 31),
        ("第1章", 1),
        ("少女与面具", None),
        ("第章", None),
    ],
)
def test_parse_chapter_number(text, expected):
    assert tansuo_module.parse_chapter_number(text) == expected


def test_visible_chapters_parses_ocr_result(monkeypatch):
    runner, _, _ = _make_runner(monkeypatch, ready_after=0)

    assert runner.visible_chapters() == [1, 2]
    assert runner.chapter_list_visible() is True


def test_chapter_list_visible_is_false_without_chapter_text(monkeypatch):
    runner, _, _ = _make_runner(monkeypatch, ready_after=0, list_visible=False)

    assert runner.visible_chapters() == []
    assert runner.chapter_list_visible() is False


def test_chapter_ready_returns_true_when_title_visible(monkeypatch):
    runner, _, events = _make_runner(monkeypatch, ready_after=0)

    assert runner.chapter_ready() is True
    assert events == []


def test_chapter_ready_clicks_entry_found_by_ocr(monkeypatch):
    runner, _, events = _make_runner(monkeypatch, ready_after=10**6, entry_visible=True, click_polls=2)

    assert runner.chapter_ready() is True
    assert [event[0] for event in events][0] == "click"
    assert events[0][1] == f"point-第{runner.target_chapter}章"


def test_chapter_ready_returns_false_when_entry_missing(monkeypatch):
    runner, _, events = _make_runner(monkeypatch, ready_after=10**6, entry_visible=False)

    assert runner.chapter_ready() is False
    assert events == []


def test_chapter_ready_accepts_detail_page_of_chapter_28(monkeypatch):
    runner, _, events = _make_runner(monkeypatch, ready_after=10**6, detail_chapter=28)

    assert runner.chapter_ready() is True
    assert events == []


def test_ensure_chapter_28_drags_until_chapter_appears(monkeypatch):
    runner, state, events = _make_runner(monkeypatch, ready_after=3)

    assert runner.ensure_chapter_28() is True
    assert state["scrolled"] == 3
    # 每次拖动前都要把指针移到章节列表上，方向为向列表末尾翻
    assert [event[0] for event in events] == ["move", "drag"] * 3
    assert [event[2] for event in events if event[0] == "drag"] == [runner.chapter_drag_distance * -1] * 3


def test_ensure_chapter_28_falls_back_to_wheel(monkeypatch):
    attempts = ProductionTanSuo.chapter_scroll_attempts
    # 拖动两个方向都试完后仍然没有28章，改用滚轮
    runner, _, events = _make_runner(monkeypatch, ready_after=attempts * 2 + 1)

    assert runner.ensure_chapter_28() is True
    kinds = [event[0] for event in events if event[0] != "move"]
    assert kinds.count("drag") == attempts * 2
    assert kinds.count("scroll") == 1
    assert events[0][0] == "move"


def test_ensure_chapter_28_returns_none_outside_chapter_list(monkeypatch):
    runner, state, _ = _make_runner(monkeypatch, ready_after=1, list_visible=False)

    assert runner.ensure_chapter_28() is None
    assert state["scrolled"] == 0


def test_ensure_chapter_28_returns_none_on_other_chapter_detail_page(monkeypatch):
    runner, state, _ = _make_runner(monkeypatch, ready_after=1, list_visible=False, detail_chapter=21)

    assert runner.ensure_chapter_28() is None
    assert state["scrolled"] == 0


def test_ensure_chapter_28_goes_back_to_list_from_other_chapter_detail_page(monkeypatch):
    runner, state, events = _make_runner(
        monkeypatch, ready_after=1, detail_chapter=21, back_visible=True
    )

    assert runner.ensure_chapter_28() is True
    # 先点左上角返回，回到列表后再滑动找到28章
    assert events[0] == ("click", "back")
    assert any(event[0] == "drag" for event in events)
    assert state["in_detail"] is False


def test_ensure_chapter_28_gives_up_after_bounded_attempts(monkeypatch):
    runner, state, _ = _make_runner(monkeypatch, ready_after=10**6)

    assert runner.ensure_chapter_28() is False
    assert state["scrolled"] == ProductionTanSuo.chapter_scroll_attempts * 4


def test_ensure_chapter_28_switches_mechanism_when_list_does_not_move(monkeypatch):
    runner, _, events = _make_runner(monkeypatch, ready_after=10**6, list_moves=False)
    limit = ProductionTanSuo.chapter_no_movement_limit

    assert runner.ensure_chapter_28() is False

    kinds = [event[0] for event in events if event[0] != "move"]
    # 列表不动时每种方式只试 limit 次就换下一种
    assert kinds.count("drag") == limit * 2
    assert kinds.count("scroll") == limit * 2


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
    runner, _, _ = _make_runner(monkeypatch, ready_after=1, list_visible=False)
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
