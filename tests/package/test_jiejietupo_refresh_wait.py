"""结界突破刷新流程：轮询替代固定睡眠、冷却分段报进度。"""

from types import SimpleNamespace

import src.package.jiejietupo as jiejietupo_module
import src.utils.function as function_module
from src.package.jiejietupo import JieJieTuPoGeRen
from src.utils.function import wait_until


class FakeClock:
    """可控时钟：sleep 时推进，避免测试里真的等待。"""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def perf_counter(self) -> float:
        return self.now


def _refresh_runner(monkeypatch, clock: FakeClock, time_refresh: float):
    runner = object.__new__(JieJieTuPoGeRen)
    runner.time_refresh = time_refresh
    runner.IMAGE_REFRESH = SimpleNamespace(name="refresh")
    runner.IMAGE_REFRESH_TRUE = SimpleNamespace(name="refresh_true")

    calls: list = []
    chunks: list = []

    def fake_wait_frame(assets, timeout=3.0, interval=0.3):
        name = assets[0].name if assets else "?"
        calls.append(f"wait_frame:{name}:{timeout}")
        return SimpleNamespace(rect=None)

    def fake_check_click(asset, **kwargs):
        calls.append(f"click:{asset.name}")
        return True

    def fake_wait_until(predicate, timeout=3.0, interval=0.3, caller_name=""):
        calls.append(f"wait_until:{caller_name}")
        # 让时钟走过等待时间，模拟"新列表已经刷出来"
        clock.now += timeout
        return True

    def fake_sleep(minimum=1.0, maximum=None, **kwargs):
        chunks.append(minimum)
        clock.now += minimum

    monkeypatch.setattr(runner, "wait_frame", fake_wait_frame)
    monkeypatch.setattr(runner, "check_click", fake_check_click)
    monkeypatch.setattr(jiejietupo_module, "wait_until", fake_wait_until)
    monkeypatch.setattr(jiejietupo_module, "sleep", fake_sleep)
    monkeypatch.setattr(jiejietupo_module, "RuleImage", lambda *a, **k: SimpleNamespace(match=lambda *aa, **kk: False))
    monkeypatch.setattr(
        jiejietupo_module,
        "time",
        SimpleNamespace(perf_counter=clock.perf_counter),
    )
    return runner, calls, chunks


def test_refresh_polls_panel_and_confirm_dialog(monkeypatch):
    """回归：刷新流程不再用固定 sleep，而是轮询面板/弹窗出现（上限与原来一致）。"""
    clock = FakeClock()
    runner, calls, _ = _refresh_runner(monkeypatch, clock, time_refresh=0)

    runner.refresh()

    assert calls[0] == "wait_frame:refresh:8.0"
    assert "click:refresh" in calls
    assert "wait_frame:refresh_true:4.0" in calls
    assert "click:refresh_true" in calls
    assert "wait_until:refresh_wait_list" in calls
    assert runner.time_refresh > 0


def test_refresh_cooldown_waits_in_chunks_with_progress(monkeypatch):
    """冷却剩余 71 秒 → 分成 30/30/11 三段分段等待并报进度。"""
    clock = FakeClock()
    # 冷却 5 分钟，已经过了 229 秒 → 还剩 71 秒
    runner, calls, chunks = _refresh_runner(
        monkeypatch, clock, time_refresh=clock.now - (5 * 60 - 71)
    )

    runner.refresh()

    assert chunks[:3] == [30, 30, 11]
    # 总等待不短于冷却剩余时间（末尾多睡 1 秒用于越过边界）
    assert sum(chunks) >= 71
    # 冷却结束后仍然完成了刷新
    assert "click:refresh" in calls


def test_refresh_cooldown_boundary_does_not_spin(monkeypatch):
    """回归：刚好卡在冷却边界上时不能空转（曾经会两个分支都不命中）。"""
    clock = FakeClock()
    runner, calls, chunks = _refresh_runner(
        monkeypatch, clock, time_refresh=clock.now - (5 * 60 - 30)
    )

    runner.refresh()

    assert chunks[0] == 30
    assert "click:refresh" in calls


def test_refresh_skips_cooldown_when_expired(monkeypatch):
    """冷却早就过了 → 不应该有任何分段等待。"""
    clock = FakeClock()
    runner, calls, chunks = _refresh_runner(
        monkeypatch, clock, time_refresh=clock.now - 10 * 60
    )

    runner.refresh()

    assert chunks == []
    assert "click:refresh" in calls


def test_wait_until_does_not_pass_caller_name_to_random_sleep(monkeypatch):
    """回归：random_sleep 被 @log_caller 装饰会自己注入 caller_name。

    如果 wait_until 再显式传一次，就会抛
    "random_sleep() got multiple values for argument 'caller_name'"。
    """
    seen = {}

    def fake_random_sleep(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs

    monkeypatch.setattr(function_module, "random_sleep", fake_random_sleep)
    monkeypatch.setattr(function_module, "event_thread", False)

    wait_until(lambda: False, timeout=0.05, interval=0.01, caller_name="somewhere")

    assert "caller_name" not in seen["kwargs"]
    assert seen["kwargs"]["minimum"] > 0
