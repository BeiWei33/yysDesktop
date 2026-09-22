"""验证式等待：条件一成立就立刻继续，超时也能正常返回。"""

import time
from types import SimpleNamespace

import pytest

import src.utils.function as function_module
from src.package.base_package import BasePackage
from src.utils.exception import GUIStopException
from src.utils.function import wait_until


def test_wait_until_returns_immediately_when_ready(monkeypatch):
    """条件一开始就成立时不应该有任何等待。"""
    sleeps = []
    monkeypatch.setattr(function_module, "random_sleep", lambda **kwargs: sleeps.append(kwargs))
    monkeypatch.setattr(function_module, "event_thread", False)

    start = time.perf_counter()
    assert wait_until(lambda: True, timeout=5.0) is True
    assert time.perf_counter() - start < 0.2
    assert sleeps == []


def test_wait_until_stops_polling_once_ready(monkeypatch):
    """条件在第 3 次成立时，应该只睡了 2 次（不是睡满整个 timeout）。"""
    calls = []
    sleeps = []

    def predicate():
        calls.append(1)
        return len(calls) >= 3

    monkeypatch.setattr(function_module, "random_sleep", lambda **kwargs: sleeps.append(kwargs))
    monkeypatch.setattr(function_module, "event_thread", False)

    assert wait_until(predicate, timeout=5.0, interval=0.2) is True
    assert len(calls) == 3
    assert len(sleeps) == 2


def test_wait_until_times_out(monkeypatch):
    """条件始终不成立时，返回 False 且等待不超过 timeout。"""
    monkeypatch.setattr(function_module, "random_sleep", lambda **kwargs: None)
    monkeypatch.setattr(function_module, "event_thread", False)

    start = time.perf_counter()
    assert wait_until(lambda: False, timeout=0.3, interval=0.1) is False
    elapsed = time.perf_counter() - start
    assert 0.25 <= elapsed < 1.5


def test_wait_until_respects_stop_event(monkeypatch):
    monkeypatch.setattr(function_module, "event_thread", True)

    with pytest.raises(GUIStopException):
        wait_until(lambda: False, timeout=5.0)


def test_wait_frame_returns_hit_frame_and_scans_every_poll(monkeypatch):
    """wait_frame 每轮都重新抓帧，命中后立刻返回，不跨时间复用旧帧。"""
    import src.package.base_package as base_package_module

    frames = []
    poll = {"n": 0}

    class FakeScreenshot:
        def __init__(self):
            self.rect = None
            poll["n"] += 1
            self.index = poll["n"]
            frames.append(self)

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, image=None, **kwargs):
            # 第三帧才命中
            return image is not None and image.index >= 3

    monkeypatch.setattr(base_package_module, "ScreenShot", FakeScreenshot)
    monkeypatch.setattr(base_package_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(base_package_module, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(base_package_module, "event_thread", False)

    runner = object.__new__(BasePackage)
    asset = SimpleNamespace(name="target")
    result = runner.wait_frame([asset], timeout=5.0, interval=0.01)

    assert poll["n"] == 3
    assert result.index == 3
    assert result is frames[-1]


def test_wait_frame_returns_last_frame_on_timeout(monkeypatch):
    import src.package.base_package as base_package_module

    poll = {"n": 0}

    class FakeScreenshot:
        def __init__(self):
            self.rect = None
            poll["n"] += 1
            self.index = poll["n"]

    monkeypatch.setattr(base_package_module, "ScreenShot", FakeScreenshot)
    monkeypatch.setattr(
        base_package_module,
        "RuleImage",
        lambda *args, **kwargs: SimpleNamespace(match=lambda *a, **k: False),
    )
    monkeypatch.setattr(base_package_module, "sleep", lambda *args, **kwargs: None)

    runner = object.__new__(BasePackage)
    result = runner.wait_frame([SimpleNamespace(name="never")], timeout=0.05, interval=0.01)

    # 至少抓过一帧，返回的是最后一帧，供调用方继续判断
    assert poll["n"] >= 1
    assert result.index == poll["n"]
