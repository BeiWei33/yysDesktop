"""逐层回退的返回键出口：素材和文字都找不到出口时，按安卓返回键。

背景：绘卷跑完一轮、关掉个人突破场景后，游戏可能停在**结界突破界面**，
那屏可能没有探索界面那种左上角返回按钮。用户要求加"返回键"这条出口。

这里同样用"真实的 TanSuo 实例 + 假的依赖"来测：
return_home / retreat_once / press_back_key / dismiss_exit_game_dialog 都是真实实现，
只把屏幕状态、RuleImage、RuleOcr、Mouse、KeyBoard、emulator、wait_until 换掉。
"""

from types import SimpleNamespace

import pytest

import src.package.tansuo as tansuo_module
from src.package.tansuo import TanSuo as ProductionTanSuo


class Machine:
    """用界面状态队列模拟回退过程

    Args:
        screens: 界面状态队列，第一个是当前界面；动作成功时前进一格
        quit_visible: 左上角返回素材是否命中
        ocr_texts: 文字识别的结果（默认空）
        emulator_enabled: 是否模拟器模式（决定能不能按返回键）
        advance_on_back_key: 按返回键后界面是否前进（False = 按了没反应）
    """

    def __init__(
        self,
        monkeypatch,
        screens: list[str],
        *,
        quit_visible: bool = False,
        ocr_texts: tuple[str, ...] = (),
        emulator_enabled: bool = True,
        advance_on_back_key: bool = True,
        yard_anchor_visible: bool = False,
    ):
        self.screens = list(screens)
        self.current = self.screens[0]
        self.quit_visible = quit_visible
        self.ocr_texts = ocr_texts
        self.advance_on_back_key = advance_on_back_key
        self.yard_anchor_visible = yard_anchor_visible
        self.clicks: list[str] = []
        self.back_key_presses = 0

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
        runner.target_chapter = 28
        runner.chapter_list_visible = lambda: self.current == "chapter_list"
        runner.current_chapter = lambda: None
        self.runner = runner

        def advance():
            if len(self.screens) > 1:
                self.screens.pop(0)
                self.current = self.screens[0]

        self.advance = advance

        def match(asset):
            if asset.name == "yard_tansuo":
                return self.current == "yard"
            if asset.name == "yard_yinzhang":
                return self.yard_anchor_visible and self.current == "yard"
            return self.quit_visible and self.current.startswith("unknown")

        monkeypatch.setattr(
            tansuo_module,
            "RuleImage",
            lambda asset, *a, **k: SimpleNamespace(
                asset=asset,
                match=lambda *aa, **kk: match(asset),
                center_point=lambda: f"point-{asset.name}",
            ),
        )
        monkeypatch.setattr(
            tansuo_module,
            "RuleOcr",
            lambda *a, **k: SimpleNamespace(
                get_raw_result=lambda: [
                    SimpleNamespace(text=text, center=f"point-{text}")
                    for text in self.ocr_texts
                ]
            ),
        )

        def click(point=None, **kwargs):
            self.clicks.append(point)
            self.advance()

        monkeypatch.setattr(tansuo_module, "Mouse", SimpleNamespace(click=click))
        monkeypatch.setattr(
            tansuo_module,
            "KeyBoard",
            SimpleNamespace(esc=lambda *a, **k: self._press_back_key()),
        )
        monkeypatch.setattr(
            tansuo_module, "emulator", SimpleNamespace(enabled=emulator_enabled)
        )
        # 只判断一次，不做真实等待：界面有没有变化完全由假状态决定
        monkeypatch.setattr(
            tansuo_module, "wait_until", lambda predicate, **kwargs: predicate()
        )
        monkeypatch.setattr(tansuo_module, "sleep", lambda *a, **k: None)
        # 庭院组合判断会截一帧喂给多个素材，这里给假截图（命中与否由上面的 match 决定）
        monkeypatch.setattr(
            tansuo_module,
            "ScreenShot",
            lambda *a, **k: SimpleNamespace(rect=None, get_image=lambda: object()),
        )

    def _press_back_key(self):
        self.back_key_presses += 1
        if self.advance_on_back_key:
            self.advance()


def test_text_exit_button_used_when_image_missing(monkeypatch):
    """返回素材不命中时，改用文字识别「返回」再点。"""
    m = Machine(monkeypatch, ["unknown", "chapter_list"], ocr_texts=("返回",))

    assert m.runner.return_home() is True
    assert m.clicks == ["point-返回"]
    assert m.back_key_presses == 0


def test_back_key_used_when_image_and_text_missing(monkeypatch):
    """素材、文字都找不到出口时，按安卓返回键。"""
    m = Machine(monkeypatch, ["unknown", "chapter_list"])

    assert m.runner.return_home() is True
    assert m.back_key_presses == 1
    assert m.runner.last_retreat_layers == 1


def test_back_key_limited_per_call(monkeypatch):
    """每次调用最多按 back_key_limit 次：把本次计数打满后不再按。

    说明：正常情况下"按了没变化立即停止"会更早收手（见上一个用例），
    这个用例专门验证次数闸门本身。
    """
    m = Machine(monkeypatch, ["unknown"] * 10)
    m.runner.back_key_count = ProductionTanSuo.back_key_limit

    assert m.runner.retreat_once(1) is False
    assert m.back_key_presses == 0


def test_back_key_stops_when_screen_unchanged(monkeypatch):
    """按了返回键但界面没变化：立即停止，不连按。"""
    m = Machine(monkeypatch, ["unknown"], advance_on_back_key=False)

    assert m.runner.return_home() is False
    assert m.back_key_presses == 1


def test_exit_game_dialog_clicks_cancel_not_confirm(monkeypatch):
    """返回键弹出「确定退出游戏吗？」时必须点「取消」，绝不能点「确定」（那会关掉游戏）。"""
    m = Machine(
        monkeypatch,
        ["unknown"],
        ocr_texts=("确定退出游戏吗？", "取消", "确定"),
    )

    assert m.runner.return_home() is False
    assert "point-取消" in m.clicks
    assert "point-确定" not in m.clicks
    assert m.back_key_presses == 1


def test_yard_does_not_press_back_key(monkeypatch):
    """识别到庭院时不按返回键，优先点探索灯笼。"""
    m = Machine(monkeypatch, ["yard", "chapter_list"])

    assert m.runner.return_home() is True
    assert m.clicks == ["point-yard_tansuo"]
    assert m.back_key_presses == 0


def test_desktop_mode_never_presses_back_key(monkeypatch):
    """桌面版不发返回键（否则会把 ESC 当返回键用，行为就变了）。"""
    m = Machine(monkeypatch, ["unknown"] * 10, emulator_enabled=False)

    assert m.runner.return_home() is False
    assert m.back_key_presses == 0
    assert m.clicks == []


def test_back_key_total_limit_stops_task(monkeypatch):
    """多次调用累计按返回键到上限后，任务明确报错停止（不再无限重试）。"""
    m = Machine(monkeypatch, ["unknown"] * 10)
    m.runner.ensure_target_chapter = lambda: None

    with pytest.raises(tansuo_module.TanSuoChapterUnavailable):
        for _ in range(ProductionTanSuo.back_key_total_limit + 2):
            m.runner.try_fix_chapter()
