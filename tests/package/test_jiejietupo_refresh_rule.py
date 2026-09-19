"""验证 3 胜刷新规则：>=3 就刷新，不再"暂不支持"。"""

import src.package.jiejietupo as jiejietupo_module
from src.package.jiejietupo import JieJieTuPoGeRen


def _runner(monkeypatch, xunzhang: list[int]):
    runner = object.__new__(JieJieTuPoGeRen)
    runner.n = 0
    runner.max = 1
    runner.max_no_progress_refresh = 3
    runner.list_num_xunzhang = lambda only_victory=False: xunzhang

    refreshed: list[bool] = []
    fought: list[bool] = []

    def stop_loop():
        # 让 while self.n < self.max 立刻结束，避免测试里空转
        runner.n = runner.max

    def refresh():
        refreshed.append(True)
        stop_loop()

    def fighting():
        fought.append(True)
        stop_loop()
        return True

    runner.refresh = refresh
    runner.fighting = fighting
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)
    return runner, refreshed, fought


def test_refresh_when_three_broken(monkeypatch):
    runner, refreshed, _ = _runner(monkeypatch, [0, -1, -1, -1, 5, 5, 3, 2, 4])

    runner.refresh_task()

    assert refreshed == [True]


def test_refresh_when_more_than_three_broken(monkeypatch):
    """列表里本来就攻破了 4 个时，以前会输出「暂不支持大于3个」并放弃，现在应该刷新。"""
    runner, refreshed, _ = _runner(monkeypatch, [0, -1, -1, -1, -1, 5, 3, 2, 4])

    runner.refresh_task()

    assert refreshed == [True]


def test_fight_when_less_than_three_broken(monkeypatch):
    runner, refreshed, fought = _runner(monkeypatch, [0, -1, -1, 5, 5, 3, 2, 4, 5])

    runner.refresh_task()

    assert fought == [True]
    assert refreshed == []
