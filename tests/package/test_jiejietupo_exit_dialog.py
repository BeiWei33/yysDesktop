"""验证模拟器模式下主动失败：用文字识别点掉退出确认弹窗。"""

from types import SimpleNamespace

import src.package.jiejietupo as jiejietupo_module
from src.package.jiejietupo import JieJieTuPoGeRen


def _runner(monkeypatch, texts: list[str], emulator_enabled: bool = True):
    runner = object.__new__(JieJieTuPoGeRen)
    clicks: list = []
    keys: list = []

    monkeypatch.setattr(
        jiejietupo_module,
        "RuleOcr",
        lambda *args, **kwargs: SimpleNamespace(
            get_raw_result=lambda: [
                SimpleNamespace(text=text, center=f"point-{text}") for text in texts
            ]
        ),
    )
    monkeypatch.setattr(jiejietupo_module, "Mouse", SimpleNamespace(click=clicks.append))
    monkeypatch.setattr(
        jiejietupo_module, "KeyBoard", SimpleNamespace(esc=lambda *a, **k: keys.append("esc"), enter=lambda *a, **k: keys.append("enter"))
    )
    monkeypatch.setattr(
        jiejietupo_module, "emulator", SimpleNamespace(enabled=emulator_enabled)
    )
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)
    return runner, clicks, keys


def test_emulator_taps_confirm_button(monkeypatch):
    """模拟器模式：回车键点不掉触摸按钮，必须用文字识别找到「确定」再点。"""
    runner, clicks, keys = _runner(monkeypatch, ["确定退出当前战斗？", "取消", "确定"])

    runner.fighting_proactive_failure_once()

    assert clicks == ["point-确定"]
    assert keys == ["esc"]


def test_desktop_still_uses_enter(monkeypatch):
    """桌面版行为不变：还是 ESC + ENTER。"""
    runner, clicks, keys = _runner(monkeypatch, [], emulator_enabled=False)

    runner.fighting_proactive_failure_once()

    assert keys == ["esc", "enter"]
    assert clicks == []


def test_emulator_warns_when_confirm_missing(monkeypatch):
    runner, clicks, _ = _runner(monkeypatch, ["取消"])

    assert runner.confirm_exit_dialog(timeout=0) is False
    assert clicks == []
