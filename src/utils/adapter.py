import random
import time
from random import Random

import pyautogui
import pytweening
import win32api
import win32con

from .config import config
from .event import event_thread, event_xuanshang
from .exception import GUIStopException, ViewportDetectionError
from .input_motion import generate_bezier_points, sample_bounded_delay, sample_centered_point
from .log import logger
from .point import Point
from .viewport import viewport_registry
from .window import window_manager

_back_click_point = Point(0, 0)  # 当前后台逻辑坐标
_back_click_handle: int | None = None
_last_input_mode: str | None = None


def _backend_transform(hwnd: int):
    transform = viewport_registry.current(hwnd)
    if transform is None:
        raise ViewportDetectionError(
            (0, 0),
            (0, 0, 0, 0),
            f"no viewport transform for handle={hwnd}",
        )
    return transform


def linear(n):
    """
    Returns ``n``, where ``n`` is the float argument between ``0.0`` and ``1.0``. This function is for the default
    linear tween for mouse moving functions.

    This function was copied from PyTweening module, so that it can be called even if PyTweening is not installed.
    """
    if not 0.0 <= n <= 1.0:
        raise ValueError("Argument must be between 0 and 1.")
    return n


class Mouse:
    """Mouse input adapter.

    Recognition targets can carry safe click bounds. When enabled, clicks sample
    near the center and movement follows a bounded cubic Bezier path.
    """

    _rng = Random()
    _MAX_FRONT_STEPS = 80
    _MAX_BACKEND_STEPS = 48

    @classmethod
    def position(cls) -> Point:
        if config.user.model_dump().get("interaction_mode", {}).get("mode") == "后台":
            hwnd = window_manager.get_current_handle()
            if hwnd is None:
                raise ViewportDetectionError(
                    (0, 0),
                    (0, 0, 0, 0),
                    "no current window handle",
                )
            cls._prepare_backend(hwnd)
            _backend_transform(hwnd)
            return Point(_back_click_point.client_x, _back_click_point.client_y)
        abs_x, abs_y = pyautogui.position()
        cls._prepare_front()
        return Point.from_screen(abs_x, abs_y)

    @classmethod
    def reset_backend_position(cls) -> None:
        """Reset the backend logical cursor and bound window state."""
        global _back_click_point, _back_click_handle, _last_input_mode
        _back_click_point = Point(0, 0)
        _back_click_handle = None
        _last_input_mode = None

    @staticmethod
    def random_tween():
        """Choose a legacy-compatible tween function."""
        tweens = [
            pytweening.easeInQuad,
            pytweening.easeOutQuad,
            pytweening.easeInOutQuad,
        ]
        return random.choice(tweens)

    @classmethod
    def set_random_seed(cls, seed: int | None) -> None:
        """Set the input-motion random source for reproducible tests."""
        cls._rng = Random(seed)

    @staticmethod
    def _motion_enabled() -> bool:
        return bool(getattr(config.user, "input_motion_enabled", True))

    @classmethod
    def _sample_click_point(cls, point: Point | None) -> Point | None:
        if point is None or not cls._motion_enabled() or not point.click_bounds:
            return point
        x, y = sample_centered_point(point.click_bounds, rng=cls._rng)
        return Point(x, y)

    @classmethod
    def _path(cls, start: tuple[int, int], end: tuple[int, int], duration: float, max_steps: int):
        distance = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
        if distance == 0:
            return [start]
        steps = max(2, min(max_steps, int(round(max(duration, 0.05) * 60))))
        if cls._motion_enabled():
            arc_limit = min(distance * 0.18, 80.0)
            arc = cls._rng.uniform(-arc_limit, arc_limit)
            jitter = min(2.0, max(0.2, distance * 0.005))
        else:
            arc = 0.0
            jitter = 0.0
        return generate_bezier_points(
            start,
            end,
            steps=steps,
            arc=arc,
            jitter=jitter,
            rng=cls._rng,
        )

    @staticmethod
    def _deduplicate(points):
        result = []
        for point in points:
            if not result or point != result[-1]:
                result.append(point)
        return result

    @classmethod
    def _execute_front_path(
        cls,
        start: tuple[int, int],
        end: tuple[int, int],
        duration: float,
        tween=linear,
    ) -> None:
        if not cls._motion_enabled():
            pyautogui.moveTo(end[0], end[1], duration=duration, tween=tween, _pause=False)
            return

        points = cls._deduplicate(cls._path(start, end, duration, cls._MAX_FRONT_STEPS))
        interval = max(float(duration), 0.0) / max(len(points) - 1, 1)
        for index, (x, y) in enumerate(points):
            if bool(event_thread):
                raise GUIStopException
            pyautogui.moveTo(x, y, duration=0, _pause=False)
            if index < len(points) - 1 and interval:
                time.sleep(interval)

    # 鼠标后台消息参考：https://learn.microsoft.com/zh-cn/windows/win32/inputdev/mouse-input-notifications

    @staticmethod
    def _win_move(hwnd, lParam):
        win32api.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lParam)

    @staticmethod
    def _win_left_click(hwnd, lParam):
        win32api.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lParam)
        win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lParam)
        win32api.SendMessage(hwnd, win32con.WM_CAPTURECHANGED, 0, 0)
        win32api.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lParam)

    @staticmethod
    def _win_scroll(hwnd, wheel_delta, lParam):
        win32api.PostMessage(hwnd, win32con.WM_MOUSEWHEEL, win32api.MAKELONG(0, wheel_delta), lParam)

    @classmethod
    def _prepare_backend(cls, hwnd: int) -> bool:
        global _back_click_point, _back_click_handle, _last_input_mode
        _backend_transform(hwnd)
        fresh = _last_input_mode != "backend" or _back_click_handle != hwnd
        if fresh:
            _back_click_point = Point(0, 0)
            _back_click_handle = hwnd
        _last_input_mode = "backend"
        return fresh

    @classmethod
    def _prepare_front(cls) -> None:
        global _last_input_mode
        _last_input_mode = "frontend"

    @classmethod
    def _backend_move_to(
        cls,
        hwnd: int,
        dst_point: Point,
        duration: float,
        already_prepared: bool = False,
    ) -> None:
        global _back_click_point
        if not already_prepared:
            cls._prepare_backend(hwnd)
        start = (_back_click_point.client_x, _back_click_point.client_y)
        end = (dst_point.client_x, dst_point.client_y)
        if not cls._motion_enabled():
            points = [end]
        else:
            points = cls._deduplicate(cls._path(start, end, duration, cls._MAX_BACKEND_STEPS))
        interval = max(float(duration), 0.0) / max(len(points) - 1, 1)
        transform = _backend_transform(hwnd)
        for index, (x, y) in enumerate(points):
            if bool(event_thread):
                raise GUIStopException
            native_x, native_y = transform.canonical_to_input((x, y))
            cls._win_move(hwnd, win32api.MAKELONG(native_x, native_y))
            _back_click_point = Point(int(x), int(y))
            if index < len(points) - 1 and interval:
                time.sleep(interval)
        

    @classmethod
    def _move_front(
        cls,
        dst_point: Point | None = None,
        x: float = None,
        y: float = None,
        xOffset: float = None,
        yOffset: float = None,
        duration: float = 0,
        tween=linear,
    ):
        try:
            start = pyautogui.position()
            if dst_point is not None:
                end = dst_point.to_screen()
            elif x is not None or y is not None:
                end = (int(x) if x is not None else start[0], int(y) if y is not None else start[1])
            elif xOffset is not None or yOffset is not None:
                end = (start[0] + int(xOffset or 0), start[1] + int(yOffset or 0))
            else:
                return
            cls._prepare_front()
            cls._execute_front_path(start, end, duration, tween)
        except pyautogui.FailSafeException:
            logger.error("鼠标移动失败，请检查是否点击了屏幕左上角，请重启后使用")
            return

    @classmethod
    def _move_backend(
        cls,
        dst_point: Point | None = None,
        x: float | None = None,
        y: float | None = None,
        xOffset: float | None = None,
        yOffset: float | None = None,
        duration: float = 0,
    ):
        global _back_click_point
        hwnd = window_manager.get_current_handle()
        if hwnd is None:
            return
        cls._prepare_backend(hwnd)

        if dst_point is None:
            if x is not None or y is not None:
                dst_point = Point(
                    x if x is not None else _back_click_point.client_x,
                    y if y is not None else _back_click_point.client_y,
                )
            elif xOffset is not None or yOffset is not None:
                dst_point = Point(
                    _back_click_point.client_x + int(xOffset or 0),
                    _back_click_point.client_y + int(yOffset or 0),
                )
            else:
                return

        cls._backend_move_to(hwnd, dst_point, duration, already_prepared=True)
        logger.info(f"update ({_back_click_point.client_x},{_back_click_point.client_y})")

    @classmethod
    def move(
        cls,
        point: Point | None = None,
        x: float = None,
        y: float = None,
        xOffset: float = None,
        yOffset: float = None,
        duration: float = 0,
        tween=linear,
    ):
        if config.user.model_dump().get("interaction_mode").get("mode") == "后台":
            cls._move_backend(point, x, y, xOffset, yOffset, duration)
        else:
            cls._move_front(point, x, y, xOffset, yOffset, duration, tween)

    @classmethod
    def _click_front(cls, point: Point | None = None, duration: float = 0.5):
        point = cls._sample_click_point(point)
        try:
            if point is None:
                cls._prepare_front()
                pyautogui.click(_pause=False)
                return

            start = pyautogui.position()
            end = point.to_screen()
            cls._prepare_front()
            cls._execute_front_path(start, end, duration, linear)
            pyautogui.click(end[0], end[1], _pause=False)
            logger.info(f"Point:({end[0]},{end[1]})")
        except pyautogui.FailSafeException:
            logger.error("Click failed; check whether the pointer reached the screen corner")
            logger.ui_error("安全错误，可能是您点击了屏幕左上角，请重启后使用")

    @classmethod
    def _click_backend(cls, point: Point | None = None, duration: float = 0.5):
        global _back_click_point
        hwnd = window_manager.get_current_handle()
        if hwnd is None:
            return
        cls._prepare_backend(hwnd)
        if point is None:
            dst_point = _back_click_point
        else:
            dst_point = point
        cls._backend_move_to(hwnd, dst_point, duration, already_prepared=True)
        transform = _backend_transform(hwnd)
        native_x, native_y = transform.canonical_to_input(
            (dst_point.client_x, dst_point.client_y)
        )
        lParam = win32api.MAKELONG(native_x, native_y)
        cls._win_left_click(hwnd, lParam)
        logger.info(f"update ({_back_click_point.client_x},{_back_click_point.client_y})")

    @classmethod
    def click(
        cls,
        point: Point | None = None,
        duration: float = 0.5,
        wait: float = 0,
    ) -> None:
        """Click at a target point or the current pointer position.

        Args:
            point: Optional client-coordinate target.
            duration: Movement duration for a target click.
            wait: Base pre-click delay; enabled motion samples 0.5x to 2x.
        """
        if bool(event_thread):
            raise GUIStopException
        if wait:
            delay = sample_bounded_delay(wait, rng=cls._rng) if cls._motion_enabled() else wait
            time.sleep(delay)

        if config.user.model_dump().get("interaction_mode").get("mode") == "后台":
            cls._click_backend(cls._sample_click_point(point), duration)
        else:
            cls._click_front(point, duration)

    @classmethod
    def _drag_front(cls, x_offset: int = None, y_offset: int = None, duration: float = 0.5):
        x_offset = int(x_offset or 0)
        y_offset = int(y_offset or 0)
        start_screen = pyautogui.position()
        handle = window_manager.get_current_handle()
        start_point = Point.from_screen(*start_screen, handle=handle)
        end_point = Point(
            start_point.client_x + x_offset,
            start_point.client_y + y_offset,
        )
        cls._prepare_front()
        pyautogui.moveTo(start_screen[0], start_screen[1], duration=0, _pause=False)
        pyautogui.mouseDown()
        try:
            if not cls._motion_enabled():
                end_screen = end_point.to_screen(handle=handle)
                pyautogui.moveTo(
                    end_screen[0],
                    end_screen[1],
                    duration=duration,
                    tween=linear,
                    _pause=False,
                )
                return

            start = (start_point.client_x, start_point.client_y)
            end = (end_point.client_x, end_point.client_y)
            points = cls._deduplicate(cls._path(start, end, duration, cls._MAX_FRONT_STEPS))
            interval = max(float(duration), 0.0) / max(len(points) - 1, 1)
            for index, (x, y) in enumerate(points):
                if bool(event_thread):
                    raise GUIStopException
                screen_x, screen_y = Point(x, y).to_screen(handle=handle)
                pyautogui.moveTo(screen_x, screen_y, duration=0, _pause=False)
                if index < len(points) - 1 and interval:
                    time.sleep(interval)
        finally:
            pyautogui.mouseUp()

    @classmethod
    def _drag_backend(cls, x_offset: int = None, y_offset: int = None, duration: float = 0.5):
        global _back_click_point
        hwnd = window_manager.get_current_handle()
        if hwnd is None:
            return
        cls._prepare_backend(hwnd)
        start = (_back_click_point.client_x, _back_click_point.client_y)
        end = (start[0] + int(x_offset or 0), start[1] + int(y_offset or 0))
        points = (
            [start, end]
            if not cls._motion_enabled()
            else cls._deduplicate(cls._path(start, end, duration, cls._MAX_BACKEND_STEPS))
        )
        transform = _backend_transform(hwnd)
        native_start = transform.canonical_to_input(start)
        down_lparam = win32api.MAKELONG(*native_start)
        win32api.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, down_lparam)
        interval = max(float(duration), 0.0) / max(len(points) - 1, 1)
        last_point = start
        try:
            for x, y in points[1:]:
                if bool(event_thread):
                    raise GUIStopException
                if interval:
                    time.sleep(interval)
                native_x, native_y = transform.canonical_to_input((x, y))
                lParam = win32api.MAKELONG(native_x, native_y)
                win32api.PostMessage(hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, lParam)
                last_point = (int(x), int(y))
                _back_click_point = Point(*last_point)
        finally:
            native_last = transform.canonical_to_input(last_point)
            lParam = win32api.MAKELONG(*native_last)
            win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lParam)
        logger.info(f"update ({_back_click_point.client_x},{_back_click_point.client_y})")

    @classmethod
    def drag(cls, x_offset: int = None, y_offset: int = None, duration: float = 0.5):
        """Drag after moving the pointer to the intended start position."""
        if config.user.model_dump().get("interaction_mode").get("mode") == "后台":
            cls._drag_backend(x_offset, y_offset, duration)
        else:
            cls._drag_front(x_offset, y_offset, duration)

    @classmethod
    def _scroll_front(cls, distance: int):
        cls._prepare_front()
        pyautogui.scroll(distance)

    @classmethod
    def _scroll_backend(cls, distance: int):
        hwnd = window_manager.get_current_handle()
        if hwnd is None:
            return
        cls._prepare_backend(hwnd)
        transform = _backend_transform(hwnd)
        native_x, native_y = transform.canonical_to_screen(
            (_back_click_point.client_x, _back_click_point.client_y)
        )
        lParam = win32api.MAKELONG(native_x, native_y)
        cls._win_scroll(hwnd, distance, lParam)

    @classmethod
    def scroll(cls, distance: int) -> None:
        """Scroll the backend window."""
        if config.user.model_dump().get("interaction_mode").get("mode") == "后台":
            cls._scroll_backend(distance)
        else:
            cls._scroll_front(distance)
        logger.info(f"scroll at ({distance})")


class KeyBoard:
    """键盘事件"""

    _KEY_MAPPING = {
        "enter": win32con.VK_RETURN,
        "esc": win32con.VK_ESCAPE,
    }

    @classmethod
    def _front_operation(cls, key: str) -> None:
        pyautogui.press(key)

    @classmethod
    def _backend_operation(cls, key: str) -> None:
        vk_code = cls._KEY_MAPPING.get(key.lower())
        if not vk_code:
            raise ValueError(f"Unsupported key: {key}")

        hwnd = window_manager.get_current_handle()
        if hwnd is None:
            return
        win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, vk_code, 0)
        win32api.PostMessage(hwnd, win32con.WM_KEYUP, vk_code, 1)

    @classmethod
    def send(cls, key: str, delay: float = 0) -> None:
        """Send a keyboard event."""
        if delay:
            time.sleep(delay)

        event_xuanshang.wait()
        logger.info(f"Sending key: {key.upper()}")

        if config.user.model_dump().get("interaction_mode").get("mode") == "后台":
            cls._backend_operation(key)
        else:
            cls._front_operation(key)

    @classmethod
    def enter(cls, delay: float = 0) -> None:
        """发送回车键"""
        cls.send("enter", delay)

    @classmethod
    def esc(cls, delay: float = 0):
        """Send Escape."""
        cls.send("esc", delay)
