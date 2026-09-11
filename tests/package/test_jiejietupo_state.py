from types import MethodType, SimpleNamespace

import pytest

import src.package.jiejietupo as jiejietupo_module
from src.package.jiejietupo import (
    JieJieTuPo,
    JieJieTuPoGeRen,
    JieJieTuPoLineupStateError,
    JieJieTuPoReadyTimeout,
    JieJieTuPoTargetUnavailable,
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
    runner.check_finish = lambda *args, **kwargs: False
    runner.done = lambda: completed.append(True)
    runner.ensure_lineup_locked = lambda: None
    runner.start_battle_from_ready_screen = lambda: False

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


def test_fighting_locks_lineup_before_attacking(monkeypatch):
    runner, _, _ = _make_runner(monkeypatch, success_after_fight=False)
    events = []

    runner.ensure_lineup_locked = lambda: events.append(("lock",))
    runner.fighting_into = lambda x, y: events.append(("attack", x, y))
    runner.start_battle_from_ready_screen = lambda: events.append(("ready",))

    runner.fighting()

    assert events == [("lock",), ("attack", 215, 140), ("ready",)]


def test_fighting_does_not_attack_when_lineup_state_is_unknown(monkeypatch):
    runner, _, _ = _make_runner(monkeypatch, success_after_fight=False)
    # 移除默认桩，验证真实的阵容锁定检查
    del runner.ensure_lineup_locked
    runner.get_lineup_state = lambda: (LineupState.NONE, None)
    runner.fighting_into = lambda *args: (_ for _ in ()).throw(RuntimeError("unexpected attack"))
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)

    with pytest.raises(JieJieTuPoLineupStateError, match="无法确认阵容已锁定"):
        runner.fighting()


def test_start_battle_from_ready_screen_clicks_prepare_when_lineup_unlocked(monkeypatch):
    ready_new = object()
    prepare_point = object()
    runner = object.__new__(JieJieTuPoGeRen)
    runner.global_assets = SimpleNamespace(
        IMAGE_READY_NEW=ready_new,
        IMAGE_READY_OLD=object(),
    )
    clicks = []

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            return self.asset is ready_new

        def center_point(self):
            return prepare_point

    monkeypatch.setattr(jiejietupo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(jiejietupo_module, "ScreenShot", lambda: object())
    monkeypatch.setattr(jiejietupo_module, "Mouse", SimpleNamespace(click=clicks.append))
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)

    assert runner.start_battle_from_ready_screen(max_attempts=2)
    assert clicks == [prepare_point]


def test_start_battle_from_ready_screen_is_bounded_when_battle_already_started(monkeypatch):
    runner = object.__new__(JieJieTuPoGeRen)
    runner.global_assets = SimpleNamespace(
        IMAGE_READY_NEW=object(),
        IMAGE_READY_OLD=object(),
    )
    screenshots = []

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            return False

    def screenshot():
        screenshots.append(True)
        return object()

    monkeypatch.setattr(jiejietupo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(jiejietupo_module, "ScreenShot", screenshot)
    monkeypatch.setattr(
        jiejietupo_module.Mouse,
        "click",
        lambda *args: (_ for _ in ()).throw(RuntimeError("unexpected prepare click")),
    )
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)

    assert not runner.start_battle_from_ready_screen(max_attempts=2)
    assert len(screenshots) == 2


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


def test_level_task_locks_lineup_before_attacking(monkeypatch):
    runner = object.__new__(JieJieTuPoGeRen)
    runner.n = 0
    runner.max = 1
    runner.flag_keep_level = False
    runner.list_xunzhang = [0, 0, -1, -1, -1, -1, -1, -1, -1, -1]
    runner.IMAGE_FANGSHOUJILU = object()
    runner.tupo_geren_x = {1: 100, 2: 200, 3: 300}
    runner.tupo_geren_y = {1: 100, 2: 200, 3: 300}
    events = []

    runner.back_to_barrier_list = lambda: events.append(("list",))
    runner.ensure_lineup_locked = lambda: events.append(("lock",))
    runner.fighting_into = lambda x, y: events.append(("attack", x, y))
    runner.start_battle_from_ready_screen = lambda: events.append(("ready",))
    runner.check_finish = lambda *args, **kwargs: True
    runner.done = lambda: setattr(runner, "n", runner.n + 1)
    runner.global_assets = SimpleNamespace(IMAGE_FINISH=object())
    runner.check_click = lambda *args, **kwargs: None
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(jiejietupo_module, "finish_random_left_right", lambda: None)

    runner.level_task(0)

    assert events == [("list",), ("lock",), ("attack", 100, 100), ("ready",)]


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

    runner.back_to_barrier_list = lambda: None
    runner.ensure_lineup_locked = lambda: None
    runner.start_battle_from_ready_screen = lambda: False
    runner.fighting_into = lambda x, y: attacks.append((x, y))
    runner.check_finish = lambda *args, **kwargs: next(outcomes)
    runner.resolve_level_failure = lambda: resolved_failures.append(True) or False

    def done():
        runner.n += 1

    runner.done = done
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(jiejietupo_module, "finish_random_left_right", lambda: None)

    runner.level_task(0)

    assert attacks == [(100, 100), (200, 100)]
    assert resolved_failures == [True]


def test_level_task_refreshes_list_after_one_pass(monkeypatch):
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
    refreshed = []

    runner.back_to_barrier_list = lambda: None
    runner.ensure_lineup_locked = lambda: None
    runner.start_battle_from_ready_screen = lambda: False
    runner.fighting_into = lambda x, y: attacks.append((x, y))
    runner.check_finish = lambda *args, **kwargs: next(outcomes)
    runner.resolve_level_failure = lambda: False
    runner.done = lambda: setattr(runner, "n", runner.n + 1)
    runner.global_assets = SimpleNamespace(IMAGE_FINISH=object())
    runner.check_click = lambda *args, **kwargs: None
    runner.list_num_xunzhang = lambda **kwargs: [0, 0, 0, -1, -1, -1, -1, -1, -1, -1]

    def refresh():
        refreshed.append(True)
        runner.max = runner.n  # 结束循环，便于断言

    runner.refresh = refresh
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(jiejietupo_module, "finish_random_left_right", lambda: None)

    runner.level_task(0)

    assert runner.n == 0
    assert attacks == [(100, 100), (200, 100)]
    assert refreshed == [True]


def test_level_task_rescans_when_barrier_state_changed(monkeypatch):
    runner = object.__new__(JieJieTuPoGeRen)
    runner.n = 0
    runner.max = 1
    runner.flag_keep_level = False
    runner.list_xunzhang = [0, 0, -1, -1, -1, -1, -1, -1, -1, -1]
    runner.IMAGE_FANGSHOUJILU = object()
    runner.tupo_geren_x = {1: 100, 2: 200, 3: 300}
    runner.tupo_geren_y = {1: 100, 2: 200, 3: 300}
    attempts = []
    scans = []

    def fighting_into(x, y):
        attempts.append((x, y))
        if len(attempts) == 1:
            raise JieJieTuPoTargetUnavailable("未点到结界")

    runner.back_to_barrier_list = lambda: None
    runner.ensure_lineup_locked = lambda: None
    runner.fighting_into = fighting_into
    runner.start_battle_from_ready_screen = lambda: False
    runner.check_finish = lambda *args, **kwargs: True
    runner.done = lambda: setattr(runner, "n", runner.n + 1)
    runner.global_assets = SimpleNamespace(IMAGE_FINISH=object())
    runner.check_click = lambda *args, **kwargs: None
    runner.list_num_xunzhang = lambda **kwargs: scans.append(True) or [0, 0, -1, -1, -1, -1, -1, -1, -1, -1]
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(jiejietupo_module, "finish_random_left_right", lambda: None)

    runner.level_task(0)

    assert attempts == [(100, 100), (100, 100)]
    assert scans == [True]
    assert runner.n == 1


def test_level_task_stops_when_no_barrier_is_attackable(monkeypatch):
    runner = object.__new__(JieJieTuPoGeRen)
    runner.n = 0
    runner.max = 5
    runner.flag_keep_level = False
    runner.list_xunzhang = [0] + [-1] * 9
    runner.IMAGE_FANGSHOUJILU = object()
    runner.tupo_geren_x = {1: 100, 2: 200, 3: 300}
    runner.tupo_geren_y = {1: 100, 2: 200, 3: 300}
    refreshed = []
    errors = []

    runner.back_to_barrier_list = lambda: None
    runner.ensure_lineup_locked = lambda: None
    runner.fighting_into = lambda *args: (_ for _ in ()).throw(RuntimeError("unexpected attack"))
    runner.list_num_xunzhang = lambda **kwargs: [0] + [-1] * 9
    runner.refresh = lambda: refreshed.append(True)
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(jiejietupo_module.logger, "ui_error", errors.append)

    runner.level_task(0)

    assert len(refreshed) == JieJieTuPoGeRen.max_no_progress_refresh
    assert errors == ["没有可进攻的结界，已停止结界突破"]


def test_back_to_barrier_list_returns_immediately_when_list_is_visible(monkeypatch):
    fangshoujilu = object()
    runner = object.__new__(JieJieTuPoGeRen)
    runner.IMAGE_FANGSHOUJILU = fangshoujilu
    runner.global_assets = SimpleNamespace(IMAGE_FINISH=object())
    esc_calls = []

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            return self.asset is fangshoujilu

    monkeypatch.setattr(jiejietupo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(jiejietupo_module.KeyBoard, "esc", lambda: esc_calls.append(True))
    monkeypatch.setattr(
        jiejietupo_module.Mouse,
        "click",
        lambda *args: (_ for _ in ()).throw(RuntimeError("unexpected dismiss click")),
    )
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)

    runner.back_to_barrier_list()

    assert esc_calls == []


def test_back_to_barrier_list_recovers_from_battle_settlement(monkeypatch):
    fangshoujilu = object()
    finish = object()
    finish_point = object()
    list_checks = []
    esc_calls = []
    clicks = []
    runner = object.__new__(JieJieTuPoGeRen)
    runner.IMAGE_FANGSHOUJILU = fangshoujilu
    runner.global_assets = SimpleNamespace(IMAGE_FINISH=finish)

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            if self.asset is fangshoujilu:
                list_checks.append(True)
                # 第一次退出结算界面后才回到列表页
                return len(list_checks) >= 2
            return self.asset is finish

        def center_point(self):
            return finish_point

    monkeypatch.setattr(jiejietupo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(jiejietupo_module.KeyBoard, "esc", lambda: esc_calls.append(True))
    monkeypatch.setattr(jiejietupo_module.Mouse, "click", clicks.append)
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)

    runner.back_to_barrier_list(wait_attempts=1)

    assert esc_calls == [True]
    assert clicks == [finish_point]
    assert len(list_checks) == 2


def test_back_to_barrier_list_stops_when_list_never_appears(monkeypatch):
    fangshoujilu = object()
    runner = object.__new__(JieJieTuPoGeRen)
    runner.IMAGE_FANGSHOUJILU = fangshoujilu
    runner.global_assets = SimpleNamespace(IMAGE_FINISH=object())
    esc_calls = []

    class FakeRuleImage:
        def __init__(self, asset):
            self.asset = asset

        def match(self, *args, **kwargs):
            return False

    monkeypatch.setattr(jiejietupo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(jiejietupo_module.KeyBoard, "esc", lambda: esc_calls.append(True))
    monkeypatch.setattr(jiejietupo_module.Mouse, "click", lambda *args: None)
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)

    with pytest.raises(JieJieTuPoReadyTimeout, match="未返回个人突破页面"):
        runner.back_to_barrier_list(wait_attempts=1, max_attempts=2)

    assert esc_calls == [True, True]


def test_level_task_bounds_reward_click_when_reward_screen_is_absent(monkeypatch):
    runner = object.__new__(JieJieTuPoGeRen)
    runner.n = 0
    runner.max = 1
    runner.flag_keep_level = False
    runner.list_xunzhang = [0, 0, -1, -1, -1, -1, -1, -1, -1, -1]
    runner.IMAGE_FANGSHOUJILU = object()
    runner.tupo_geren_x = {1: 100, 2: 200, 3: 300}
    runner.tupo_geren_y = {1: 100, 2: 200, 3: 300}
    click_calls = []

    runner.back_to_barrier_list = lambda: None
    runner.ensure_lineup_locked = lambda: None
    runner.start_battle_from_ready_screen = lambda: False
    runner.fighting_into = lambda x, y: None
    runner.check_finish = lambda *args, **kwargs: True
    runner.done = lambda: setattr(runner, "n", runner.n + 1)
    runner.global_assets = SimpleNamespace(IMAGE_FINISH=object())
    runner.check_click = lambda *args, **kwargs: click_calls.append(kwargs) or False
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(jiejietupo_module, "finish_random_left_right", lambda: None)

    runner.level_task(0)

    # 已完成 9 个结界（8 个已攻破 + 本次胜利），需要处理奖励界面且不能无限等待
    assert "timeout" in click_calls[0]


def test_fighting_reports_no_attack_when_all_barriers_failed(monkeypatch):
    runner = object.__new__(JieJieTuPoGeRen)
    runner.list_xunzhang = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    runner.tupo_victory = 0
    runner.IMAGE_FAIL = object()
    runner.IMAGE_SUCCESS = object()
    runner.tupo_geren_x = {1: 100, 2: 200, 3: 300}
    runner.tupo_geren_y = {1: 100, 2: 200, 3: 300}
    runner.ensure_lineup_locked = lambda: None
    runner.fighting_into = lambda *args: (_ for _ in ()).throw(RuntimeError("unexpected attack"))

    class FakeRuleImage:
        def __init__(self, asset, region=None):
            self.asset = asset

        def match(self, *args, **kwargs):
            return self.asset is runner.IMAGE_FAIL

    monkeypatch.setattr(jiejietupo_module, "RuleImage", FakeRuleImage)
    monkeypatch.setattr(jiejietupo_module, "sleep", lambda *args, **kwargs: None)

    assert runner.fighting() is False


def test_refresh_task_refreshes_list_when_no_barrier_is_attackable(monkeypatch):
    runner = object.__new__(JieJieTuPoGeRen)
    runner.n = 0
    runner.max = 10
    runner.list_xunzhang = None
    runner.list_num_xunzhang = lambda **kwargs: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    runner.fighting = lambda: False
    refreshed = []
    runner.refresh = lambda: refreshed.append(True)
    errors = []
    monkeypatch.setattr(jiejietupo_module.logger, "ui_error", errors.append)

    runner.refresh_task()

    assert len(refreshed) == JieJieTuPoGeRen.max_no_progress_refresh
    assert errors == ["没有可进攻的结界，已停止结界突破"]
