from types import SimpleNamespace

import pytest

import src.package.base_package as base_package_module
import src.package.douji as douji_module
from src.package.douji import DouJi

from .utils import Package, check_package


class DouJiPackage(Package):
    resource_path = "douji"


def test_douji():
    check_package(DouJiPackage)


def _make_runner(monkeypatch, ready_asset: str | None = None, ready_clicks: list | None = None):
    """构造一个只带必要属性的斗技实例。"""
    runner = object.__new__(DouJi)
    runner.OCR_TITLE = SimpleNamespace(name="title")
    runner.OCR_FIGHT = SimpleNamespace(name="fight")
    runner.OCR_AUTO = SimpleNamespace(name="auto", region=None)
    runner.OCR_CANCEL = SimpleNamespace(name="cancel")
    runner.OCR_INTENTIONAL = SimpleNamespace(name="intentional")
    runner.OCR_VICTORY = SimpleNamespace(name="victory")
    runner.OCR_FAIL = SimpleNamespace(name="fail")
    runner.global_assets = SimpleNamespace(
        IMAGE_READY_NEW=SimpleNamespace(name="ready_new"),
        IMAGE_READY_OLD=SimpleNamespace(name="ready_old"),
        ALL_FAIL_IMAGES=[],
        OCR_CLICK_AND_CONTINUE=SimpleNamespace(name="click_and_continue"),
    )
    runner.log_current_asset_list = lambda: None
    runner.done = lambda: None

    clicks = ready_clicks if ready_clicks is not None else []

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            return ready_asset is not None and self.asset.name == ready_asset

        def center_point(self):
            return f"point-{self.asset.name}"

    monkeypatch.setattr(douji_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(douji_module, "Mouse", SimpleNamespace(click=clicks.append))
    monkeypatch.setattr(douji_module, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(douji_module, "ocr_match_once", lambda *args, **kwargs: None)
    # click_ready_once 定义在 BasePackage，使用的是该模块自己的引用
    monkeypatch.setattr(base_package_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(base_package_module, "Mouse", SimpleNamespace(click=clicks.append))
    monkeypatch.setattr(base_package_module, "sleep", lambda *args, **kwargs: None)
    return runner, clicks


def test_click_ready_once_returns_false_without_ready_button(monkeypatch):
    runner, clicks = _make_runner(monkeypatch)

    assert runner.click_ready_once() is False
    assert clicks == []


@pytest.mark.parametrize("ready_asset", ["ready_new", "ready_old"])
def test_click_ready_once_clicks_ready_button(monkeypatch, ready_asset):
    runner, clicks = _make_runner(monkeypatch, ready_asset=ready_asset)

    assert runner.click_ready_once() is True
    assert clicks == [f"point-{ready_asset}"]


def test_fighting_once_checks_ready_even_when_ocr_matches_something(monkeypatch):
    """OCR 匹配到其它文字时也要先检查准备按钮，否则会一直卡在上阵阶段。"""
    runner, clicks = _make_runner(monkeypatch, ready_asset="ready_new")

    events = []

    def click_ready_once():
        events.append("ready")
        # 第一次识别到准备并点击，之后按钮消失
        if len(events) == 1:
            return True
        return False

    def ocr_match_once(*args, **kwargs):
        events.append("ocr")
        raise RuntimeError("stop-loop")

    runner.click_ready_once = click_ready_once
    monkeypatch.setattr(douji_module, "ocr_match_once", ocr_match_once)

    with pytest.raises(RuntimeError, match="stop-loop"):
        runner.fighting_once()

    # 第一轮先点准备并 continue，第二轮继续检查准备后才走 OCR
    assert events == ["ready", "ready", "ocr"]
    assert clicks == []
