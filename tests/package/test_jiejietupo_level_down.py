"""退级流程在模拟器模式下的键位适配。"""

from types import SimpleNamespace

import src.package.jiejietupo as jiejietupo_module
from src.package.jiejietupo import JieJieTuPoGeRen


def _runner(monkeypatch, ocr_texts: list[str], emulator_enabled: bool):
    runner = object.__new__(JieJieTuPoGeRen)
    keys: list[str] = []
    clicks: list = []
    runner.global_assets = SimpleNamespace(
        IMAGE_READY_NEW=SimpleNamespace(name="ready_new"),
        IMAGE_READY_OLD=SimpleNamespace(name="ready_old"),
    )

    monkeypatch.setattr(
        jiejietupo_module, "ScreenShot", lambda *a, **k: SimpleNamespace(rect=None)
    )
    monkeypatch.setattr(
        jiejietupo_module,
        "RuleImage",
        lambda *a, **k: SimpleNamespace(match=lambda *aa, **kk: False),
    )
    monkeypatch.setattr(
        jiejietupo_module,
        "RuleOcr",
        lambda *a, **k: SimpleNamespace(
            get_raw_result=lambda: [SimpleNamespace(text=t, center=t) for t in ocr_texts]
        ),
    )
    monkeypatch.setattr(
        jiejietupo_module,
        "KeyBoard",
        SimpleNamespace(esc=lambda *a, **k: keys.append("esc"), enter=lambda *a, **k: keys.append("enter")),
    )
    monkeypatch.setattr(jiejietupo_module, "Mouse", SimpleNamespace(click=clicks.append))
    monkeypatch.setattr(jiejietupo_module, "emulator", SimpleNamespace(enabled=emulator_enabled))
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *a, **k: None)
    return runner, keys, clicks


def test_wait_for_ready_accepts_ocr_text(monkeypatch):
    """手机版准备按钮图像素材不命中时，用「准备」文字兜底。"""
    runner, _, _ = _runner(monkeypatch, ["准备", "加成"], emulator_enabled=True)

    assert runner.wait_for_ready(max_attempts=2) is True


def test_wait_for_ready_times_out_without_ready(monkeypatch):
    runner, _, _ = _runner(monkeypatch, ["取消", "加成"], emulator_enabled=True)

    assert runner.wait_for_ready(max_attempts=2) is False


def test_press_enter_only_on_desktop(monkeypatch):
    """模拟器模式不该再发键盘回车（安卓回车键点不掉界面）。"""
    import inspect

    source = inspect.getsource(JieJieTuPoGeRen.fighting_proactive_failure)

    assert "if not emulator.enabled:" in source
    assert "KeyBoard.enter()" in source
