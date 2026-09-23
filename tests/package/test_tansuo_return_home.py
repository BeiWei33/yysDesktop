"""逐层回退（return_home）：把落在任意子界面的情况拉回探索界面。

背景：绘卷跑完一轮、关闭个人突破场景后，游戏可能停在结界突破入口/庭院等界面，
原来只认庭院一条路，其它界面会一直空转。这里逐层回退，每层只点有依据的按钮，
点完验证界面真的变了。

这里用"真实的 TanSuo 实例 + 假的依赖"来测：return_home / recognize_current_screen
都是真实实现，只把屏幕状态、RuleImage、Mouse、wait_until 换掉。
"""

from types import SimpleNamespace

import pytest

import src.package.tansuo as tansuo_module
from src.package.tansuo import TanSuo as ProductionTanSuo


class ScreenMachine:
    """用一个"界面状态队列"模拟回退过程：每点一次就前进一格"""

    def __init__(self, monkeypatch, screens: list[str], quit_visible: bool = True, yard_anchor_visible: bool = False):
        self.screens = list(screens)
        self.quit_visible = quit_visible
        self.yard_anchor_visible = yard_anchor_visible
        self.clicks: list[str] = []
        self.current = self.screens[0]

        runner = object.__new__(ProductionTanSuo)
        runner.IMAGE_YARD_TANSUO = SimpleNamespace(name="yard_tansuo")
        runner.IMAGE_YARD_YINZHANG = SimpleNamespace(name="yard_yinzhang")
        runner.IMAGE_QUIT = SimpleNamespace(name="quit")
        runner.yard_tansuo_point = (663, 225)
        runner.yard_click_count = 0
        runner.yard_click_fail_count = 0
        runner.last_retreat_layers = 0
        runner.chapter_miss_count = 0
        runner.chapter_fix_failures = 0
        runner.chapter_unknown_count = 0
        runner.back_key_count = 0
        runner.back_key_total_count = 0
        runner.chapter_fix_interval = 1
        runner.chapter_list_visible = lambda: self.current == "chapter_list"
        runner.current_chapter = lambda: 3 if self.current == "chapter_detail" else None
        self.runner = runner

        # 默认：文字识别看不到任何出口按钮（这些用例只考察返回素材那条路）
        monkeypatch.setattr(
            tansuo_module,
            "RuleOcr",
            lambda *a, **k: SimpleNamespace(get_raw_result=lambda: []),
        )

        def match(self_rule, *args, **kwargs):
            if self_rule.asset.name == "yard_tansuo":
                return self.current == "yard"
            if self_rule.asset.name == "yard_yinzhang":
                # 封印锚点：默认关闭，只在指定用例里打开（测"灯笼认不出但锚点认得出"）
                return self.yard_anchor_visible and self.current == "yard"
            # 返回按钮只在"左侧有返回键"的界面上出现
            return self.quit_visible and self.current == "unknown_quit"

        monkeypatch.setattr(
            tansuo_module,
            "RuleImage",
            lambda asset, *a, **k: SimpleNamespace(
                asset=asset,
                match=lambda *aa, **kk: match(SimpleNamespace(asset=asset)),
                center_point=lambda: f"point-{asset.name}",
            ),
        )

        def click(point):
            self.clicks.append(point)
            self.advance()

        def advance():
            if len(self.screens) > 1:
                self.screens.pop(0)
                self.current = self.screens[0]

        self.advance = advance
        monkeypatch.setattr(tansuo_module, "Mouse", SimpleNamespace(click=click))
        monkeypatch.setattr(tansuo_module, "wait_until", lambda *a, **k: True)
        monkeypatch.setattr(tansuo_module, "sleep", lambda *a, **k: None)
        # 庭院组合判断会截一帧喂给多个素材，这里给假截图（命中与否由上面的 match 决定）
        monkeypatch.setattr(
            tansuo_module,
            "ScreenShot",
            lambda *a, **k: SimpleNamespace(rect=None, get_image=lambda: object()),
        )


def test_unknown_screen_clicks_back_button_then_returns(monkeypatch):
    """落在不认识的界面：点左上角返回，回到章节列表就算到家。"""
    m = ScreenMachine(monkeypatch, ["unknown_quit", "chapter_list"])

    assert m.runner.return_home() is True
    assert m.clicks == ["point-quit"]
    assert m.runner.last_retreat_layers == 1


def test_multi_level_retreat_returns_after_two_layers(monkeypatch):
    """可以逐层退多层：退两层后回到章节列表。"""
    m = ScreenMachine(monkeypatch, ["unknown_quit", "unknown_quit", "chapter_list"])

    assert m.runner.return_home() is True
    assert m.runner.last_retreat_layers == 2
    assert m.clicks == ["point-quit", "point-quit"]


def test_unknown_screen_without_back_button_does_nothing(monkeypatch):
    """认不出界面、又没有返回按钮时不能盲点，直接放弃（层数为 0）。"""
    m = ScreenMachine(monkeypatch, ["unknown"], quit_visible=False)

    assert m.runner.return_home() is False
    assert m.clicks == []
    assert m.runner.last_retreat_layers == 0


def test_yard_clicks_exploration_entry_once_and_returns(monkeypatch):
    m = ScreenMachine(monkeypatch, ["yard", "chapter_list"])

    assert m.runner.return_home() is True
    assert m.clicks == ["point-yard_tansuo"]
    assert m.runner.yard_click_count == 1


def test_yard_stuck_still_yard_gives_up_without_repeated_clicks(monkeypatch):
    """点了探索灯笼但还停在庭院：只点一次就交回上层，不连续猛点。"""
    m = ScreenMachine(monkeypatch, ["yard"])

    assert m.runner.return_home() is False
    assert m.clicks == ["point-yard_tansuo"]
    assert m.runner.yard_click_count == 1


def test_retreat_limit_stops_after_n_layers(monkeypatch):
    """一直退不出去时最多退 retreat_limit 层就放弃。"""
    m = ScreenMachine(monkeypatch, ["unknown_quit"] * 10)

    assert m.runner.return_home() is False
    assert m.runner.last_retreat_layers == ProductionTanSuo.retreat_limit


def test_detail_page_counts_as_home(monkeypatch):
    """章节详情页也算"到家"（原有流程能处理它）。"""
    m = ScreenMachine(monkeypatch, ["chapter_detail"])

    assert m.runner.return_home() is True
    assert m.clicks == []
    assert m.runner.last_retreat_layers == 0


def test_try_fix_chapter_counts_unknown_only_when_no_retreat(monkeypatch):
    """没有做任何回退动作时才计入"界面不认识"，避免把回退尝试算成空转。"""
    m = ScreenMachine(monkeypatch, ["unknown"], quit_visible=False)
    m.runner.ensure_target_chapter = lambda: None

    m.runner.try_fix_chapter()

    assert m.runner.chapter_unknown_count == 1


def test_try_fix_chapter_raises_after_unknown_limit(monkeypatch):
    m = ScreenMachine(monkeypatch, ["unknown"], quit_visible=False)
    m.runner.ensure_target_chapter = lambda: None

    with pytest.raises(tansuo_module.TanSuoChapterUnavailable):
        for _ in range(ProductionTanSuo.chapter_unknown_limit):
            m.runner.try_fix_chapter()


def test_yard_clicks_beyond_limit_raise(monkeypatch):
    """庭院入口反复点不通（每次调用点一次）就报错停止。"""
    m = ScreenMachine(monkeypatch, ["yard"])
    m.runner.ensure_target_chapter = lambda: None

    with pytest.raises(tansuo_module.TanSuoChapterUnavailable):
        for _ in range(ProductionTanSuo.yard_click_limit + 2):
            m.runner.try_fix_chapter()
