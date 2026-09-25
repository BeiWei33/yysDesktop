"""高光结算界面「点一下继续」的测试

用真实的 BasePackage.tap_highlight_continue，只替换外部依赖（OCR/鼠标/等待），
这样测的是真逻辑，而不是造一个假对象。
"""

from types import SimpleNamespace

import pytest

import src.package.base_package as base_package_module
from src.package.base_package import BasePackage
from src.package.douji import DouJi

SHARE_POINT = (1034, 572)  # 右下角「分享」按钮（实测坐标），绝对不能点
LINEUP_POINT = (92, 521)  # 左下角「我的阵容」（实测坐标）


def _make_runner(monkeypatch, matched_text: str | None = "6连胜", screen_changes: bool = True, limit: int = 3):
    runner = object.__new__(BasePackage)
    runner.highlight_continue_count = 0
    runner.highlight_click_point = BasePackage.highlight_click_point
    runner.highlight_click_limit = limit
    runner.global_assets = SimpleNamespace(
        OCR_HIGHLIGHT_CONTINUE=SimpleNamespace(name="highlight_continue", keyword="连胜", region=(0, 430, 1136, 210))
    )

    state = {"clicks": [], "match_calls": 0}

    class FakeRuleOcr:
        def __init__(self, asset=None, **kwargs):
            self.match_result = SimpleNamespace(text=matched_text) if matched_text else None

        def match(self, *args, **kwargs):
            state["match_calls"] += 1
            if matched_text is None:
                return None
            # 第一次是"判定界面"，之后是"验证画面是否翻页"
            if state["match_calls"] == 1:
                return self.match_result
            return self.match_result if not screen_changes else None

    monkeypatch.setattr(base_package_module, "RuleOcr", FakeRuleOcr)
    monkeypatch.setattr(base_package_module, "Mouse", SimpleNamespace(click=state["clicks"].append))
    # 真实 wait_until 会轮询 + 睡眠，这里只求值一次（它自己有单独的测试）
    monkeypatch.setattr(
        base_package_module, "wait_until", lambda predicate, **kwargs: bool(predicate())
    )
    return runner, state


def test_taps_once_when_highlight_detected(monkeypatch):
    runner, state = _make_runner(monkeypatch)

    assert runner.tap_highlight_continue() is True

    assert len(state["clicks"]) == 1
    point = state["clicks"][0]
    assert (point.client_x, point.client_y) == BasePackage.highlight_click_point


def test_click_point_avoids_share_and_lineup(monkeypatch):
    """点击位置必须避开「分享」（会打开分享面板）和「我的阵容」。"""
    x, y = BasePackage.highlight_click_point

    assert abs(x - SHARE_POINT[0]) > 200 or abs(y - SHARE_POINT[1]) > 200
    assert abs(x - LINEUP_POINT[0]) > 200 or abs(y - LINEUP_POINT[1]) > 200
    # 落在画面中上部，和两个危险按钮都不在同一角落
    assert 400 <= x <= 740
    assert 200 <= y <= 380


def test_no_repeat_when_screen_not_changed(monkeypatch):
    runner, state = _make_runner(monkeypatch, screen_changes=False)

    assert runner.tap_highlight_continue() is True
    assert len(state["clicks"]) == 1

    # 画面没变化 → 直接停手，第二次调用不再点
    assert runner.tap_highlight_continue() is False
    assert len(state["clicks"]) == 1


def test_stops_after_limit(monkeypatch):
    runner, state = _make_runner(monkeypatch, limit=1)

    assert runner.tap_highlight_continue() is True
    assert runner.tap_highlight_continue() is False
    assert len(state["clicks"]) == 1


def test_returns_false_when_not_highlight(monkeypatch):
    """不命中高光特征时行为不变：不点击、返回 False。"""
    runner, state = _make_runner(monkeypatch, matched_text=None)

    assert runner.tap_highlight_continue() is False
    assert state["clicks"] == []
    assert runner.highlight_continue_count == 0


def test_douji_prefers_highlight_over_fail_images(monkeypatch):
    """斗技轮询里：没匹配到预期素材时先试高光界面，命中就继续，不去查失败图。"""
    runner = object.__new__(DouJi)
    runner.highlight_continue_count = 0
    runner.highlight_click_point = BasePackage.highlight_click_point
    runner.highlight_click_limit = BasePackage.highlight_click_limit
    # fighting_once 会自己拼 current_asset_list，需要这些 OCR 资产
    runner.OCR_TITLE = SimpleNamespace(name="title")
    runner.OCR_FIGHT = SimpleNamespace(name="fight")
    runner.OCR_AUTO = SimpleNamespace(name="auto", region=None)
    runner.OCR_CANCEL = SimpleNamespace(name="cancel")
    runner.OCR_INTENTIONAL = SimpleNamespace(name="intentional")
    runner.OCR_VICTORY = SimpleNamespace(name="victory")
    runner.OCR_FAIL = SimpleNamespace(name="fail")
    runner.global_assets = SimpleNamespace(
        OCR_HIGHLIGHT_CONTINUE=SimpleNamespace(name="highlight_continue"),
        OCR_CLICK_AND_CONTINUE=SimpleNamespace(name="click_and_continue"),
        ALL_FAIL_IMAGES=[SimpleNamespace(name="fail")],
    )

    calls = []

    def fake_highlight():
        calls.append("highlight")
        return True

    runner.tap_highlight_continue = fake_highlight
    monkeypatch.setattr(base_package_module, "RuleImage", lambda *a, **k: SimpleNamespace(match=lambda *aa, **kk: calls.append("fail_image")))
    monkeypatch.setattr(base_package_module, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        base_package_module, "Point", lambda *a, **k: SimpleNamespace(client_x=a[0], client_y=a[1])
    )

    import src.package.douji as douji_module

    # 让循环跑两轮后停下：第一轮命中高光 continue，第二轮抛异常退出
    def ocr_match_once(*args, **kwargs):
        if len(calls) >= 1:
            raise RuntimeError("stop-loop")
        return None

    monkeypatch.setattr(douji_module, "ocr_match_once", ocr_match_once)
    runner.current_asset_list = []
    runner.log_current_asset_list = lambda: None
    runner.click_ready_once = lambda: False

    with pytest.raises(RuntimeError, match="stop-loop"):
        runner.fighting_once()

    assert calls == ["highlight"]
