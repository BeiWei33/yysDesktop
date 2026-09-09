from types import SimpleNamespace

import pytest

import src.utils.adapter as adapter
from src.utils.point import Point
from src.utils.viewport import ViewportTransform, viewport_registry


def _config(mode="前台", enabled=True):
    return SimpleNamespace(
        input_motion_enabled=enabled,
        model_dump=lambda: {"interaction_mode": {"mode": mode}},
    )


def _register_identity_transform(*handles):
    for handle in handles:
        viewport_registry.set(
            ViewportTransform(
                handle=handle,
                capture_size=(1136, 640),
                active_capture_rect=(0, 0, 1136, 640),
                screen_client_rect=(0, 0, 1136, 640),
            ),
            "test",
        )


@pytest.fixture(autouse=True)
def _legacy_viewport(monkeypatch):
    viewport_registry.clear()
    _register_identity_transform(1, 2, 123)
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: 123)
    yield
    viewport_registry.clear()


def test_sample_click_point_stays_inside_recognition_bounds(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config())
    adapter.Mouse.set_random_seed(17)
    point = Point(50, 50, click_bounds=(10, 20, 90, 80))

    samples = [adapter.Mouse._sample_click_point(point) for _ in range(100)]

    assert all(10 <= sample.client_x <= 90 for sample in samples)
    assert all(20 <= sample.client_y <= 80 for sample in samples)
    assert len({(sample.client_x, sample.client_y) for sample in samples}) > 20


def test_disabled_motion_keeps_original_click_point(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(enabled=False))
    point = Point(50, 50, click_bounds=(10, 20, 90, 80))

    assert adapter.Mouse._sample_click_point(point) is point


def test_adjusting_detected_point_clears_stale_click_bounds():
    point = Point(50, 50, click_bounds=(10, 20, 90, 80))

    point.set_y(25)

    assert point.click_bounds is None


def test_rule_image_random_point_returns_center_with_bounds(monkeypatch):
    import src.utils.image as image_module

    rule = object.__new__(image_module.RuleImage)
    rule.match_result = (10, 20, 90, 80)

    point = rule.random_point()

    assert (point.client_x, point.client_y) == (50, 50)
    assert point.click_bounds == (10, 20, 90, 80)


def test_click_uses_bounded_delay_for_wait(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config())
    delays = []
    monkeypatch.setattr(adapter, "sample_bounded_delay", lambda base, rng=None: base * 1.5)
    monkeypatch.setattr(adapter.time, "sleep", lambda delay: delays.append(delay))
    monkeypatch.setattr(adapter.Mouse, "_click_front", lambda point, duration: None)

    adapter.Mouse.click(Point(10, 10), wait=2.0)

    assert delays == [3.0]


def test_front_click_without_target_does_not_move_for_duration(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config())
    moves = []
    clicks = []
    monkeypatch.setattr(adapter.pyautogui, "moveTo", lambda *args, **kwargs: moves.append((args, kwargs)))
    monkeypatch.setattr(adapter.pyautogui, "click", lambda *args, **kwargs: clicks.append((args, kwargs)))

    adapter.Mouse._click_front(None, duration=2.0)

    assert moves == []
    assert clicks == [((), {"_pause": False})]


def test_front_click_executes_path_then_clicks_endpoint(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config())
    moves = []
    clicks = []
    monkeypatch.setattr(adapter.pyautogui, "position", lambda: (5, 7))
    monkeypatch.setattr(
        adapter.pyautogui,
        "moveTo",
        lambda x, y, duration=0, **kwargs: moves.append((x, y, duration, kwargs)),
    )
    monkeypatch.setattr(adapter.pyautogui, "click", lambda *args, **kwargs: clicks.append((args, kwargs)))
    monkeypatch.setattr(adapter.time, "sleep", lambda _delay: None)
    adapter.Mouse.set_random_seed(3)

    adapter.Mouse._click_front(Point(105, 107), duration=0.3)

    assert len(moves) > 2
    assert moves[-1][:2] == (105, 107)
    assert moves[-1][3]["_pause"] is False
    assert clicks == [((105, 107), {"_pause": False})]


def test_front_path_disables_pyautogui_pause_for_each_micro_step(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config())
    moves = []
    monkeypatch.setattr(adapter.pyautogui, "moveTo", lambda *args, **kwargs: moves.append((args, kwargs)))
    monkeypatch.setattr(adapter.time, "sleep", lambda _delay: None)
    adapter.Mouse.set_random_seed(3)

    adapter.Mouse._execute_front_path((0, 0), (100, 100), duration=0.3)

    assert len(moves) > 2
    assert all(call[1].get("_pause") is False for call in moves)


def test_disabled_front_path_uses_supplied_tween(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(enabled=False))
    calls = []
    custom_tween = lambda value: value
    monkeypatch.setattr(adapter.pyautogui, "moveTo", lambda *args, **kwargs: calls.append((args, kwargs)))

    adapter.Mouse._execute_front_path((0, 0), (100, 100), duration=0.3, tween=custom_tween)

    assert calls == [
        ((100, 100), {"duration": 0.3, "tween": custom_tween, "_pause": False})
    ]


def test_backend_click_uses_bounded_path_and_exact_endpoint(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(mode="后台"))
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: 123)
    posted_moves = []
    clicks = []
    monkeypatch.setattr(adapter.Mouse, "_win_move", lambda hwnd, lparam: posted_moves.append((hwnd, lparam)))
    monkeypatch.setattr(adapter.Mouse, "_win_left_click", lambda hwnd, lparam: clicks.append((hwnd, lparam)))
    monkeypatch.setattr(adapter.time, "sleep", lambda _delay: None)
    adapter.Mouse.reset_backend_position()
    adapter.Mouse.set_random_seed(5)

    adapter.Mouse._click_backend(Point(10, 10), duration=0.2)
    adapter.Mouse._click_backend(Point(1010, 610), duration=0.5)

    assert 2 < len(posted_moves) <= adapter.Mouse._MAX_BACKEND_STEPS + 2
    expected = adapter.win32api.MAKELONG(1010, 610)
    assert posted_moves[-1] == (123, expected)
    assert clicks[-1] == (123, expected)


def test_backend_click_without_target_does_not_reuse_old_handle_position(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(mode="后台"))
    handle = {"value": 1}
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: handle["value"])
    clicks = []
    monkeypatch.setattr(adapter.Mouse, "_win_move", lambda hwnd, lparam: None)
    monkeypatch.setattr(adapter.Mouse, "_win_left_click", lambda hwnd, lparam: clicks.append((hwnd, lparam)))
    monkeypatch.setattr(adapter.time, "sleep", lambda _delay: None)
    adapter.Mouse.reset_backend_position()

    adapter.Mouse._click_backend(Point(100, 100), duration=0.2)
    handle["value"] = 2
    adapter.Mouse._click_backend(None, duration=0.2)

    assert clicks[-1] == (2, adapter.win32api.MAKELONG(0, 0))


def test_backend_offset_is_based_on_reset_position_after_handle_change(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(mode="后台"))
    handle = {"value": 1}
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: handle["value"])
    moves = []
    monkeypatch.setattr(adapter.Mouse, "_win_move", lambda hwnd, lparam: moves.append((hwnd, lparam)))
    monkeypatch.setattr(adapter.time, "sleep", lambda _delay: None)
    adapter.Mouse.reset_backend_position()

    adapter.Mouse._move_backend(Point(100, 100), duration=0.2)
    handle["value"] = 2
    adapter.Mouse._move_backend(xOffset=10, yOffset=20, duration=0.2)

    assert moves[-1] == (2, adapter.win32api.MAKELONG(10, 20))


def test_backend_drag_uses_full_duration_intervals(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(mode="后台"))
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: 123)
    moves = []
    sleeps = []

    def post_message(_hwnd, message, _wparam, lparam):
        if message == adapter.win32con.WM_MOUSEMOVE:
            moves.append(lparam)

    monkeypatch.setattr(adapter.win32api, "PostMessage", post_message)
    monkeypatch.setattr(adapter.time, "sleep", lambda delay: sleeps.append(delay))
    adapter.Mouse.reset_backend_position()
    adapter.Mouse._move_backend(Point(100, 100), duration=0)
    moves.clear()
    sleeps.clear()

    adapter.Mouse._drag_backend(200, 100, duration=0.5)

    assert len(moves) > 2
    assert len(sleeps) == len(moves)
    assert abs(sum(sleeps) - 0.5) < 1e-9


def test_backend_interruption_keeps_last_sent_position(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(mode="后台"))
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: 123)
    moves = []

    class StopAfterFirstSend:
        sent = False

        def __bool__(self):
            return self.sent

    stop_event = StopAfterFirstSend()
    monkeypatch.setattr(
        adapter.Mouse,
        "_win_move",
        lambda _hwnd, lparam: (moves.append(lparam), setattr(stop_event, "sent", True)),
    )
    monkeypatch.setattr(adapter.time, "sleep", lambda _delay: None)
    adapter.Mouse.reset_backend_position()

    class NeverStop:
        def __bool__(self):
            return False

    monkeypatch.setattr(adapter, "event_thread", NeverStop())
    adapter.Mouse._move_backend(Point(100, 100), duration=0)
    moves.clear()
    stop_event.sent = False
    monkeypatch.setattr(adapter, "event_thread", stop_event)
    try:
        adapter.Mouse._move_backend(Point(500, 300), duration=0.5)
    except adapter.GUIStopException:
        pass

    last_lparam = moves[-1]
    expected = (last_lparam & 0xFFFF, (last_lparam >> 16) & 0xFFFF)
    position = adapter.Mouse.position()
    assert (position.client_x, position.client_y) == expected


def test_backend_handle_change_resets_path_origin(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(mode="后台"))
    handle = {"value": 1}
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: handle["value"])
    posted_moves = []
    monkeypatch.setattr(adapter.Mouse, "_win_move", lambda hwnd, lparam: posted_moves.append((hwnd, lparam)))
    monkeypatch.setattr(adapter.time, "sleep", lambda _delay: None)
    adapter.Mouse.reset_backend_position()

    adapter.Mouse._move_backend(Point(100, 100), duration=0.5)
    first_count = len(posted_moves)
    handle["value"] = 2
    adapter.Mouse._move_backend(Point(900, 600), duration=0.5)

    assert 1 <= first_count <= adapter.Mouse._MAX_BACKEND_STEPS + 1
    second_count = len(posted_moves) - first_count
    assert 1 <= second_count <= adapter.Mouse._MAX_BACKEND_STEPS + 1
    assert posted_moves[-1] == (2, adapter.win32api.MAKELONG(900, 600))


def test_backend_click_maps_each_canonical_path_point_to_native_active_rect(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(mode="后台"))
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: 123)
    transform = ViewportTransform(
        handle=123,
        capture_size=(1129, 636),
        active_capture_rect=(0, 0, 753, 424),
        screen_client_rect=(1286, 276, 753, 424),
    )
    viewport_registry.clear()
    viewport_registry.set(transform, "bitblt")
    posted_moves = []
    clicks = []
    monkeypatch.setattr(adapter.Mouse, "_win_move", lambda hwnd, lparam: posted_moves.append((hwnd, lparam)))
    monkeypatch.setattr(adapter.Mouse, "_win_left_click", lambda hwnd, lparam: clicks.append((hwnd, lparam)))
    monkeypatch.setattr(adapter.time, "sleep", lambda _delay: None)
    adapter.Mouse.reset_backend_position()

    try:
        adapter.Mouse._click_backend(Point(1135, 639), duration=0.5)

        native_points = [
            (lparam & 0xFFFF, (lparam >> 16) & 0xFFFF)
            for _, lparam in posted_moves
        ]
        expected = adapter.win32api.MAKELONG(752, 423)
        assert posted_moves[-1] == (123, expected)
        assert clicks == [(123, expected)]
        assert all(0 <= x <= 752 and 0 <= y <= 423 for x, y in native_points)
    finally:
        viewport_registry.clear()




def test_backend_click_uses_client_input_size_when_capture_active_rect_is_smaller(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(mode="后台", enabled=False))
    transform = ViewportTransform(
        handle=123,
        capture_size=(1129, 636),
        active_capture_rect=(0, 0, 753, 427),
        screen_client_rect=(774, 734, 1129, 636),
    )
    viewport_registry.clear()
    viewport_registry.set(transform, "test")
    clicks = []
    monkeypatch.setattr(adapter.Mouse, "_win_move", lambda hwnd, lparam: None)
    monkeypatch.setattr(
        adapter.Mouse,
        "_win_left_click",
        lambda hwnd, lparam: clicks.append((hwnd, lparam)),
    )
    adapter.Mouse.reset_backend_position()

    try:
        adapter.Mouse._click_backend(Point(152, 539), duration=0)

        assert clicks == [(123, adapter.win32api.MAKELONG(151, 536))]
    finally:
        viewport_registry.clear()


    monkeypatch.setattr(adapter.config, "user", _config(mode="后台", enabled=False))
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: 123)
    transform = ViewportTransform(
        handle=123,
        capture_size=(1129, 636),
        active_capture_rect=(0, 0, 753, 424),
        screen_client_rect=(1286, 276, 753, 424),
    )
    viewport_registry.clear()
    viewport_registry.set(transform, "bitblt")
    messages = []
    monkeypatch.setattr(
        adapter.win32api,
        "PostMessage",
        lambda hwnd, message, wparam, lparam: messages.append(
            (hwnd, message, wparam, lparam)
        ),
    )
    adapter.Mouse.reset_backend_position()

    try:
        adapter.Mouse._drag_backend(1135, 639, duration=0.2)

        expected_start = adapter.win32api.MAKELONG(0, 0)
        expected_end = adapter.win32api.MAKELONG(752, 423)
        assert messages[0] == (
            123,
            adapter.win32con.WM_LBUTTONDOWN,
            adapter.win32con.MK_LBUTTON,
            expected_start,
        )
        move_messages = [
            message for message in messages if message[1] == adapter.win32con.WM_MOUSEMOVE
        ]
        assert move_messages[-1][-1] == expected_end
        assert messages[-1] == (123, adapter.win32con.WM_LBUTTONUP, 0, expected_end)
        assert all(
            0 <= (message[3] & 0xFFFF) <= 752
            and 0 <= ((message[3] >> 16) & 0xFFFF) <= 423
            for message in messages
        )
    finally:
        viewport_registry.clear()


def test_backend_scroll_maps_current_canonical_position_to_screen_lparam(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(mode="后台", enabled=False))
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: 123)
    transform = ViewportTransform(
        handle=123,
        capture_size=(1129, 636),
        active_capture_rect=(0, 0, 753, 424),
        screen_client_rect=(1286, 276, 753, 424),
    )
    viewport_registry.clear()
    viewport_registry.set(transform, "bitblt")
    scrolls = []
    monkeypatch.setattr(
        adapter.Mouse,
        "_win_scroll",
        lambda hwnd, distance, lparam: scrolls.append((hwnd, distance, lparam)),
    )
    monkeypatch.setattr(adapter.Mouse, "_win_move", lambda _hwnd, _lparam: None)
    adapter.Mouse.reset_backend_position()

    try:
        adapter.Mouse._move_backend(Point(568, 320), duration=0)
        adapter.Mouse._scroll_backend(120)

        expected = transform.canonical_to_screen((568, 320))
        assert scrolls == [(123, 120, adapter.win32api.MAKELONG(*expected))]
    finally:
        viewport_registry.clear()


def test_front_position_maps_screen_coordinates_to_canonical(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(mode="前台"))
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: 123)
    transform = ViewportTransform(
        handle=123,
        capture_size=(1129, 636),
        active_capture_rect=(0, 0, 753, 424),
        screen_client_rect=(1286, 276, 753, 424),
    )
    viewport_registry.clear()
    viewport_registry.set(transform, "bitblt")
    monkeypatch.setattr(adapter.pyautogui, "position", lambda: (1662, 488))

    try:
        position = adapter.Mouse.position()

        assert abs(position.client_x - 568) <= 1
        assert abs(position.client_y - 320) <= 1
    finally:
        viewport_registry.clear()


def test_backend_position_stays_canonical_and_resets_on_handle_change(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(mode="后台", enabled=False))
    handle = {"value": 123}
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: handle["value"])
    first = ViewportTransform(
        handle=123,
        capture_size=(1129, 636),
        active_capture_rect=(0, 0, 753, 424),
        screen_client_rect=(1286, 276, 753, 424),
    )
    second = ViewportTransform(
        handle=456,
        capture_size=(1136, 640),
        active_capture_rect=(0, 0, 1136, 640),
        screen_client_rect=(100, 200, 1136, 640),
    )
    viewport_registry.clear()
    viewport_registry.set(first, "bitblt")
    viewport_registry.set(second, "bitblt")
    monkeypatch.setattr(adapter.Mouse, "_win_move", lambda _hwnd, _lparam: None)
    adapter.Mouse.reset_backend_position()

    try:
        adapter.Mouse._move_backend(Point(568, 320), duration=0)
        position = adapter.Mouse.position()
        assert (position.client_x, position.client_y) == (568, 320)

        handle["value"] = 456
        position = adapter.Mouse.position()
        assert (position.client_x, position.client_y) == (0, 0)
    finally:
        viewport_registry.clear()


@pytest.mark.parametrize("motion_enabled", [False, True])
def test_front_drag_maps_canonical_offset_to_screen(monkeypatch, motion_enabled):
    monkeypatch.setattr(adapter.config, "user", _config(mode="前台", enabled=motion_enabled))
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: 123)
    transform = ViewportTransform(
        handle=123,
        capture_size=(1129, 636),
        active_capture_rect=(0, 0, 753, 424),
        screen_client_rect=(1286, 276, 753, 424),
    )
    viewport_registry.clear()
    viewport_registry.set(transform, "bitblt")
    start_screen = (1662, 488)
    moves = []
    drag_rel_calls = []
    mouse_events = []
    monkeypatch.setattr(adapter.pyautogui, "position", lambda: start_screen)
    monkeypatch.setattr(
        adapter.pyautogui,
        "moveTo",
        lambda x, y, **kwargs: moves.append((x, y, kwargs)),
    )
    monkeypatch.setattr(
        adapter.pyautogui,
        "dragRel",
        lambda *args, **kwargs: drag_rel_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        adapter.pyautogui,
        "mouseDown",
        lambda: mouse_events.append("down"),
    )
    monkeypatch.setattr(
        adapter.pyautogui,
        "mouseUp",
        lambda: mouse_events.append("up"),
    )
    monkeypatch.setattr(adapter.time, "sleep", lambda _delay: None)

    try:
        adapter.Mouse._drag_front(100, 50, duration=0.2)

        canonical_start = transform.screen_to_canonical(start_screen)
        canonical_end = (
            canonical_start[0] + 100,
            canonical_start[1] + 50,
        )
        expected_end = transform.canonical_to_screen(canonical_end)
        assert drag_rel_calls == []
        assert moves[-1][:2] == expected_end
        assert mouse_events == ["down", "up"]
    finally:
        viewport_registry.clear()


def test_backend_scroll_uses_screen_coordinates_for_wheel_lparam(monkeypatch):
    monkeypatch.setattr(adapter.config, "user", _config(mode="后台", enabled=False))
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: 123)
    transform = ViewportTransform(
        handle=123,
        capture_size=(1129, 636),
        active_capture_rect=(0, 0, 753, 424),
        screen_client_rect=(1286, 276, 753, 424),
    )
    viewport_registry.clear()
    viewport_registry.set(transform, "bitblt")
    monkeypatch.setattr(adapter.Mouse, "_win_move", lambda _hwnd, _lparam: None)
    scrolls = []
    monkeypatch.setattr(
        adapter.Mouse,
        "_win_scroll",
        lambda hwnd, distance, lparam: scrolls.append((hwnd, distance, lparam)),
    )
    adapter.Mouse.reset_backend_position()

    try:
        adapter.Mouse._move_backend(Point(568, 320), duration=0)
        adapter.Mouse._scroll_backend(120)

        expected_screen = transform.canonical_to_screen((568, 320))
        assert scrolls == [(123, 120, adapter.win32api.MAKELONG(*expected_screen))]
    finally:
        viewport_registry.clear()


@pytest.mark.parametrize("frontend_action", ["position", "scroll"])
def test_frontend_action_resets_backend_position_when_switching_back(
    monkeypatch, frontend_action
):
    monkeypatch.setattr(adapter.config, "user", _config(mode="后台", enabled=False))
    monkeypatch.setattr(adapter.window_manager, "get_current_handle", lambda: 123)
    transform = ViewportTransform(
        handle=123,
        capture_size=(1129, 636),
        active_capture_rect=(0, 0, 753, 424),
        screen_client_rect=(1286, 276, 753, 424),
    )
    viewport_registry.clear()
    viewport_registry.set(transform, "bitblt")
    monkeypatch.setattr(adapter.Mouse, "_win_move", lambda _hwnd, _lparam: None)
    monkeypatch.setattr(adapter.pyautogui, "position", lambda: (1662, 488))
    monkeypatch.setattr(adapter.pyautogui, "scroll", lambda _distance: None)
    adapter.Mouse.reset_backend_position()

    try:
        adapter.Mouse._move_backend(Point(568, 320), duration=0)
        monkeypatch.setattr(adapter.config, "user", _config(mode="前台", enabled=False))
        if frontend_action == "position":
            position = adapter.Mouse.position()
            assert abs(position.client_x - 568) <= 1
            assert abs(position.client_y - 320) <= 1
        else:
            adapter.Mouse._scroll_front(1)

        monkeypatch.setattr(adapter.config, "user", _config(mode="后台", enabled=False))
        position = adapter.Mouse.position()
        assert (position.client_x, position.client_y) == (0, 0)
    finally:
        viewport_registry.clear()
