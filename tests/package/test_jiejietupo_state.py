from types import MethodType, SimpleNamespace

import pytest

import src.package.jiejietupo as jiejietupo_module
from src.package.jiejietupo import (
    JieJieTuPo,
    JieJieTuPoGeRen,
    JieJieTuPoLineupStateError,
    LineupState,
)


def _make_runner(monkeypatch, success_after_fight: bool):
    runner = object.__new__(JieJieTuPoGeRen)
    runner.list_xunzhang = [0, 0, -1, -1, -1, -1, -1, -1, -1, -1]
    runner.tupo_victory = 0
    runner.IMAGE_FAIL = object()
    runner.IMAGE_SUCCESS = object()
    runner.IMAGE_JINGONG = object()

    attacks = []
    completed = []

    def fighting_into(x, y):
        point = (x, y)
        if point in attacks:
            raise RuntimeError(f"duplicate barrier attack: {point}")
        attacks.append(point)

    class FakeRuleImage:
        def __init__(self, asset, region=None):
            self.asset = asset

        def match(self):
            if self.asset is runner.IMAGE_SUCCESS:
                return success_after_fight and bool(attacks)
            return False

    runner.fighting_into = fighting_into
    runner.check_finish = lambda: False
    runner.done = lambda: completed.append(True)

    monkeypatch.setattr(jiejietupo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(jiejietupo_module, "finish_random_left_right", lambda: None)

    return runner, attacks, completed


def test_fighting_corrects_false_failure_when_barrier_is_already_breached(monkeypatch):
    runner, attacks, completed = _make_runner(monkeypatch, success_after_fight=True)

    runner.fighting()

    assert attacks == [(215, 140)]
    assert completed == [True]


def test_fighting_attempts_each_available_barrier_at_most_once_per_scan(monkeypatch):
    runner, attacks, completed = _make_runner(monkeypatch, success_after_fight=False)

    runner.fighting()

    assert attacks == [(215, 140)]
    assert completed == []


def test_fighting_returns_to_rescan_when_target_is_no_longer_clickable(monkeypatch):
    runner, _, completed = _make_runner(monkeypatch, success_after_fight=False)
    runner.fighting_into = MethodType(JieJieTuPo.fighting_into, runner)
    runner.check_click = lambda *args, **kwargs: False
    monkeypatch.setattr(jiejietupo_module.Mouse, "click", lambda *args, **kwargs: None)

    runner.fighting()

    assert completed == []


def test_proactive_failure_does_not_attack_when_lineup_state_is_unknown(monkeypatch):
    runner = object.__new__(JieJieTuPoGeRen)
    runner.get_lineup_state = lambda: (LineupState.NONE, None)
    runner.list_num_xunzhang = lambda **kwargs: [0, 0, -1, -1, -1, -1, -1, -1, -1, -1]
    runner.fighting_into = lambda *args: (_ for _ in ()).throw(RuntimeError("unexpected attack"))
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)

    with pytest.raises(JieJieTuPoLineupStateError, match="无法确认阵容已解锁"):
        runner.fighting_proactive_failure(1)


def test_ensure_lineup_locked_switches_unlocked_lineup(monkeypatch):
    point = object()
    states = iter([(LineupState.UNLOCK, point), (LineupState.LOCK, None)])
    runner = object.__new__(JieJieTuPoGeRen)
    runner.get_lineup_state = lambda: next(states)
    clicks = []
    monkeypatch.setattr(jiejietupo_module.Mouse, "click", clicks.append)
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)

    runner.ensure_lineup_locked(max_attempts=2)

    assert clicks == [point]


def test_wait_for_ready_checks_old_variant_when_new_variant_is_absent(monkeypatch):
    ready_new = object()
    ready_old = object()
    runner = object.__new__(JieJieTuPoGeRen)
    runner.global_assets = SimpleNamespace(IMAGE_READY_NEW=ready_new, IMAGE_READY_OLD=ready_old)
    checked = []

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            checked.append(self.asset)
            return self.asset is ready_old

    monkeypatch.setattr(jiejietupo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(jiejietupo_module, "ScreenShot", lambda: object(), raising=False)

    assert runner.wait_for_ready(max_attempts=1)
    assert checked == [ready_new, ready_old]


def test_wait_for_ready_stops_after_bounded_attempts(monkeypatch):
    ready_new = object()
    ready_old = object()
    runner = object.__new__(JieJieTuPoGeRen)
    runner.global_assets = SimpleNamespace(IMAGE_READY_NEW=ready_new, IMAGE_READY_OLD=ready_old)
    checked = []

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            checked.append(self.asset)
            return False

    monkeypatch.setattr(jiejietupo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(jiejietupo_module, "ScreenShot", lambda: object(), raising=False)
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)

    assert not runner.wait_for_ready(max_attempts=2)
    assert checked == [ready_new, ready_old, ready_new, ready_old]


def test_level_failure_is_corrected_when_victory_settlement_appears(monkeypatch):
    finish = object()
    fight_again = object()
    runner = object.__new__(JieJieTuPoGeRen)
    runner.global_assets = SimpleNamespace(IMAGE_FINISH=finish)
    runner.IMAGE_FIGHT_AGAIN = fight_again
    checked = []

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            checked.append(self.asset)
            return self.asset is finish

    monkeypatch.setattr(jiejietupo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(jiejietupo_module, "ScreenShot", lambda: object())
    monkeypatch.setattr(
        jiejietupo_module.Mouse,
        "click",
        lambda *args: (_ for _ in ()).throw(RuntimeError("unexpected retry")),
    )

    assert runner.resolve_level_failure(max_attempts=1)
    assert checked == [finish]


def test_level_failure_skips_without_retry_when_fight_again_appears(monkeypatch):
    finish = object()
    fight_again = object()
    runner = object.__new__(JieJieTuPoGeRen)
    runner.global_assets = SimpleNamespace(IMAGE_FINISH=finish)
    runner.IMAGE_FIGHT_AGAIN = fight_again
    dismissed = []

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            return self.asset is fight_again

        def random_point(self):
            return object()

    monkeypatch.setattr(jiejietupo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(jiejietupo_module, "ScreenShot", lambda: object())
    monkeypatch.setattr(
        jiejietupo_module.Mouse,
        "click",
        lambda *args: (_ for _ in ()).throw(RuntimeError("unexpected retry click")),
    )
    monkeypatch.setattr(
        jiejietupo_module.KeyBoard,
        "enter",
        lambda: (_ for _ in ()).throw(RuntimeError("unexpected retry confirmation")),
    )
    monkeypatch.setattr(
        jiejietupo_module,
        "finish_random_left_right",
        lambda: dismissed.append(True),
    )

    assert not runner.resolve_level_failure(max_attempts=1)
    assert dismissed == [True]


def test_level_failure_resolution_stops_after_bounded_attempts(monkeypatch):
    finish = object()
    fight_again = object()
    runner = object.__new__(JieJieTuPoGeRen)
    runner.global_assets = SimpleNamespace(IMAGE_FINISH=finish)
    runner.IMAGE_FIGHT_AGAIN = fight_again
    checked = []

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            checked.append(self.asset)
            return False

    monkeypatch.setattr(jiejietupo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(jiejietupo_module, "ScreenShot", lambda: object())
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)

    with pytest.raises(Exception, match="未识别到胜利结算或再次挑战"):
        runner.resolve_level_failure(max_attempts=2)

    assert checked == [finish, fight_again, finish, fight_again]


def test_level_task_moves_to_next_barrier_after_first_real_failure(monkeypatch):
    runner = object.__new__(JieJieTuPoGeRen)
    runner.n = 0
    runner.max = 1
    runner.flag_keep_level = False
    runner.list_xunzhang = [0, 0, 0, -1, -1, -1, -1, -1, -1, -1]
    runner.IMAGE_FANGSHOUJILU = object()
    runner.tupo_geren_x = {1: 100, 2: 200, 3: 300}
    runner.tupo_geren_y = {1: 100, 2: 200, 3: 300}
    outcomes = iter([False, True])
    attacks = []
    resolved_failures = []

    runner.check_scene = lambda *args, **kwargs: True
    runner.fighting_into = lambda x, y: attacks.append((x, y))
    runner.check_finish = lambda: next(outcomes)
    runner.resolve_level_failure = lambda: resolved_failures.append(True) or False

    def done():
        runner.n += 1

    runner.done = done
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(jiejietupo_module, "finish_random_left_right", lambda: None)

    runner.level_task(0)

    assert attacks == [(100, 100), (200, 100)]
    assert resolved_failures == [True]


def test_level_task_does_not_revisit_failed_barriers_after_one_pass(monkeypatch):
    runner = object.__new__(JieJieTuPoGeRen)
    runner.n = 0
    runner.max = 1
    runner.flag_keep_level = False
    runner.list_xunzhang = [0, 0, 0, -1, -1, -1, -1, -1, -1, -1]
    runner.IMAGE_FANGSHOUJILU = object()
    runner.tupo_geren_x = {1: 100, 2: 200, 3: 300}
    runner.tupo_geren_y = {1: 100, 2: 200, 3: 300}
    outcomes = iter([False, False, True])
    attacks = []

    runner.check_scene = lambda *args, **kwargs: True
    runner.fighting_into = lambda x, y: attacks.append((x, y))
    runner.check_finish = lambda: next(outcomes)
    runner.resolve_level_failure = lambda: False
    runner.done = lambda: setattr(runner, "n", runner.n + 1)
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(jiejietupo_module, "finish_random_left_right", lambda: None)

    runner.level_task(0)

    assert runner.n == 0
    assert attacks == [(100, 100), (200, 100)]
