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


def test_configured_chapter_defaults_to_28(monkeypatch):
    monkeypatch.setattr(tansuo_module.config.user, "tansuo_target_chapter", 28, raising=False)

    assert ProductionTanSuo.configured_chapter() == 28


def test_configured_chapter_reads_config(monkeypatch):
    monkeypatch.setattr(tansuo_module.config.user, "tansuo_target_chapter", 1, raising=False)

    assert ProductionTanSuo.configured_chapter() == 1


@pytest.mark.parametrize("value", [29, -1, "abc", None])
def test_configured_chapter_falls_back_on_invalid_value(monkeypatch, value):
    monkeypatch.setattr(tansuo_module.config.user, "tansuo_target_chapter", value, raising=False)

    assert ProductionTanSuo.configured_chapter() == 28


def test_chapter_assets_empty_when_target_is_not_28(monkeypatch):
    runner, _, _ = _make_runner(monkeypatch, ready_after=1)
    runner.target_chapter = 1

    assert runner.chapter_assets() == []


def test_chapter_assets_used_for_chapter_28(monkeypatch):
    runner, _, _ = _make_runner(monkeypatch, ready_after=1)

    assert len(runner.chapter_assets()) == 2


def test_ensure_target_chapter_skips_check_when_disabled(monkeypatch):
    """目标章节为 0（不校验）时不应该有滑动或点击动作。"""
    runner, _, events = _make_runner(monkeypatch, ready_after=10**6, list_visible=True)
    runner.target_chapter = 0

    assert runner.ensure_target_chapter() is True
    assert events == []


def _make_runner(
    monkeypatch,
    ready_after: int,
    list_visible: bool = True,
    list_moves: bool = True,
    detail_chapter: int | None = None,
    entry_visible: bool = False,
    click_polls: int = 0,
    back_visible: bool = False,
    list_tail: int | None = None,
    list_base_y: int = 200,
    yard_visible: bool = False,
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
        list_tail: 列表只显示这一章（用于模拟最后一行被截断识别）
        yard_visible: 当前是否停在庭院（能识别到庭院探索入口）
    """
    runner = object.__new__(ProductionTanSuo)
    runner.IMAGE_TITLE_28 = object()
    runner.IMAGE_TANSUO_28 = object()
    runner.IMAGE_QUIT = object()
    runner.IMAGE_YARD_TANSUO = object()
    runner.chapter_miss_count = 0
    runner.chapter_fix_failures = 0
    runner.chapter_unknown_count = 0
    runner.yard_click_count = 0
    runner.back_key_count = 0
    runner.back_key_total_count = 0

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
            if self.asset is runner.IMAGE_YARD_TANSUO:
                return yard_visible
            return False

        def center_point(self):
            if self.asset is runner.IMAGE_YARD_TANSUO:
                return "yard"
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
        elif point == "yard":
            state["yard_clicks"] = state.get("yard_clicks", 0) + 1
        else:
            state["entry_clicks"] += 1

    def list_result():
        if state["in_detail"] or not (list_visible or entry_visible):
            return []
        if list_tail is not None:
            numbers = [list_tail]
        else:
            # 列表可见时至少识别到两个章节；滑动有效时内容会变化，但不会滑动到28章
            first = 1 + (state["scrolled"] % 25 if list_moves else 0)
            numbers = [first, first + 1]
            if entry_visible:
                numbers.append(runner.target_chapter)
        return [
            SimpleNamespace(
                text=f"第{number}章",
                center=SimpleNamespace(client_x=976, client_y=list_base_y + index * 94),
            )
            for index, number in enumerate(numbers)
        ]

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
    # 不做真实等待：界面状态由假对象决定，判断一次即可（否则每个用例都要真等 3~4 秒）
    monkeypatch.setattr(tansuo_module, "wait_until", lambda predicate, **kwargs: predicate())

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
    clicks = [event for event in events if event[0] == "click"]
    assert clicks[0][1].client_x == 976
    assert clicks[0][1].client_y == 200 + 2 * 94  # 第三个条目＝28章


def test_target_entry_point_infers_row_below_previous_chapter(monkeypatch):
    runner, _, _ = _make_runner(monkeypatch, ready_after=10**6, list_tail=27)
    items = runner.chapter_items()

    point = runner.target_entry_point(items)

    assert point is not None
    assert point.client_y == 200 + runner.chapter_row_spacing


def test_ensure_target_chapter_clicks_inferred_row_for_misread_last_row(monkeypatch):
    # 27章下面那一行就是28章（最后一行常被截断识别成「十八」）
    runner, _, events = _make_runner(monkeypatch, ready_after=10**6, list_tail=27)

    assert runner.ensure_target_chapter() is True
    clicks = [event for event in events if event[0] == "click"]
    assert clicks[0][1].client_y == 200 + runner.chapter_row_spacing


def test_chapter_ready_returns_false_when_entry_missing(monkeypatch):
    runner, _, events = _make_runner(monkeypatch, ready_after=10**6, entry_visible=False)

    assert runner.chapter_ready() is False
    assert events == []


def test_chapter_ready_accepts_detail_page_of_chapter_28(monkeypatch):
    runner, _, events = _make_runner(monkeypatch, ready_after=10**6, detail_chapter=28)

    assert runner.chapter_ready() is True
    assert events == []


def test_ensure_target_chapter_drags_until_chapter_appears(monkeypatch):
    runner, state, events = _make_runner(monkeypatch, ready_after=3)

    assert runner.ensure_target_chapter() is True
    assert state["scrolled"] == 3
    # 每次拖动前都要把指针移到章节列表上，方向为向列表末尾翻
    assert [event[0] for event in events] == ["move", "drag"] * 3
    assert [event[2] for event in events if event[0] == "drag"] == [runner.chapter_drag_distance * -1] * 3


def test_ensure_target_chapter_falls_back_to_wheel(monkeypatch):
    drags = ProductionTanSuo.chapter_drag_attempts
    # 拖动两个方向都试完后仍然没有28章，改用滚轮
    runner, _, events = _make_runner(monkeypatch, ready_after=drags * 2 + 1)

    assert runner.ensure_target_chapter() is True
    kinds = [event[0] for event in events if event[0] != "move"]
    assert kinds.count("drag") == drags * 2
    assert kinds.count("scroll") == 1
    assert events[0][0] == "move"


def test_ensure_target_chapter_returns_none_outside_chapter_list(monkeypatch):
    runner, state, _ = _make_runner(monkeypatch, ready_after=1, list_visible=False)

    assert runner.ensure_target_chapter() is None
    assert state["scrolled"] == 0


def test_ensure_target_chapter_returns_none_on_other_chapter_detail_page(monkeypatch):
    runner, state, _ = _make_runner(monkeypatch, ready_after=1, list_visible=False, detail_chapter=21)

    assert runner.ensure_target_chapter() is None
    assert state["scrolled"] == 0


def test_ensure_target_chapter_goes_back_to_list_from_other_chapter_detail_page(monkeypatch):
    runner, state, events = _make_runner(
        monkeypatch, ready_after=1, detail_chapter=21, back_visible=True
    )

    assert runner.ensure_target_chapter() is True
    # 先点左上角返回，回到列表后再滑动找到28章
    assert events[0] == ("click", "back")
    assert any(event[0] == "drag" for event in events)
    assert state["in_detail"] is False


def test_ensure_target_chapter_scrolls_after_failed_target_click(monkeypatch):
    """28章就在眼前但点击无效时，必须滑动改变状态，不能原地重复点击。"""
    runner, _, events = _make_runner(monkeypatch, ready_after=10**6, list_tail=27, click_polls=10**6)

    assert runner.ensure_target_chapter() is False

    kinds = [event[0] for event in events]
    first_click = kinds.index("click")
    assert "drag" in kinds[first_click:] or "scroll" in kinds[first_click:]


def test_ensure_target_chapter_stops_after_repeated_click_failures(monkeypatch):
    runner, _, events = _make_runner(monkeypatch, ready_after=10**6, list_tail=27, click_polls=10**6)
    limit = ProductionTanSuo.chapter_click_failure_limit

    assert runner.ensure_target_chapter() is False

    clicks = [event for event in events if event[0] == "click"]
    assert len(clicks) == limit


def _base_y_below_visible_area() -> int:
    """放在列表可视区底部的一行：再往下推断一行就会超出可视区。"""
    _, top, _, height = ProductionTanSuo.chapter_list_region
    bottom = top + height - ProductionTanSuo.chapter_row_spacing // 2
    return bottom - ProductionTanSuo.chapter_row_spacing + 10


def test_target_entry_point_does_not_infer_row_outside_visible_area(monkeypatch):
    """27章已经在列表最底部时，推断出的28章在可视区外，不能按坐标点击。"""
    runner, _, _ = _make_runner(
        monkeypatch, ready_after=10**6, list_tail=27, list_base_y=_base_y_below_visible_area()
    )

    assert runner.target_entry_point(runner.chapter_items()) is None


def test_ensure_target_chapter_scrolls_when_target_row_is_below_visible_area(monkeypatch):
    runner, _, events = _make_runner(
        monkeypatch,
        ready_after=10**6,
        list_tail=27,
        list_base_y=_base_y_below_visible_area(),
        list_moves=False,
    )

    assert runner.ensure_target_chapter() is False

    # 不能对着看不见的位置点击，只能滑动
    assert all(event[0] != "click" for event in events)
    assert any(event[0] in ("drag", "scroll") for event in events)


def test_ensure_target_chapter_gives_up_after_bounded_attempts(monkeypatch):
    runner, state, _ = _make_runner(monkeypatch, ready_after=10**6)

    assert runner.ensure_target_chapter() is False
    per_pass = ProductionTanSuo.chapter_drag_attempts + ProductionTanSuo.chapter_scroll_attempts
    assert state["scrolled"] == per_pass * 2


def test_ensure_target_chapter_switches_mechanism_when_list_does_not_move(monkeypatch):
    runner, _, events = _make_runner(monkeypatch, ready_after=10**6, list_moves=False)
    limit = ProductionTanSuo.chapter_no_movement_limit

    assert runner.ensure_target_chapter() is False

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
    """界面认不出来时不计入「切换章节失败」，但会计入空转保护计数。"""
    runner, _, _ = _make_runner(monkeypatch, ready_after=1, list_visible=False)
    runner.chapter_fix_interval = 1

    for _ in range(ProductionTanSuo.chapter_fix_max_failures):
        runner.try_fix_chapter()

    assert runner.chapter_fix_failures == 0
    assert runner.chapter_unknown_count == ProductionTanSuo.chapter_fix_max_failures


def test_try_fix_chapter_stops_when_screen_never_recognized(monkeypatch):
    """连续多次认不出界面就报错停止，不再无限空转（曾经空转 6 分钟）。"""
    runner, _, _ = _make_runner(monkeypatch, ready_after=1, list_visible=False)
    runner.chapter_fix_interval = 1

    with pytest.raises(TanSuoChapterUnavailable):
        for _ in range(ProductionTanSuo.chapter_unknown_limit):
            runner.try_fix_chapter()


def test_try_fix_chapter_clicks_yard_exploration_entry(monkeypatch):
    """停在庭院时应点探索入口，而不是继续空转。"""
    runner, state, events = _make_runner(
        monkeypatch, ready_after=1, list_visible=False, yard_visible=True
    )
    runner.chapter_fix_interval = 1

    runner.try_fix_chapter()

    assert state["yard_clicks"] == 1
    assert runner.chapter_unknown_count == 0  # 点了入口就不算空转


def test_try_fix_chapter_stops_when_yard_entry_useless(monkeypatch):
    """点了探索入口仍停在庭院（连点超过上限）也要报错停止。"""
    runner, _, _ = _make_runner(
        monkeypatch, ready_after=1, list_visible=False, yard_visible=True
    )
    runner.chapter_fix_interval = 1

    with pytest.raises(TanSuoChapterUnavailable):
        for _ in range(ProductionTanSuo.yard_click_limit + 1):
            runner.try_fix_chapter()


def test_yard_click_counter_resets_after_recovery(monkeypatch):
    """恢复到正常界面后，庭院点击计数要清零。"""
    runner, _, _ = _make_runner(monkeypatch, ready_after=0)
    runner.chapter_fix_interval = 1
    runner.yard_click_count = 2
    runner.chapter_unknown_count = 3

    runner.try_fix_chapter()

    assert runner.yard_click_count == 0
    assert runner.chapter_unknown_count == 0


def test_try_fix_chapter_stops_after_repeated_failures(monkeypatch):
    runner, _, _ = _make_runner(monkeypatch, ready_after=10**6)
    runner.chapter_fix_interval = 1

    for _ in range(ProductionTanSuo.chapter_fix_max_failures - 1):
        runner.try_fix_chapter()

    with pytest.raises(TanSuoChapterUnavailable):
        runner.try_fix_chapter()
