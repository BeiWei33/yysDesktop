import time
from ctypes import windll

import win32con
import win32gui
import win32ui
from PIL import Image, ImageGrab

from .config import InteractionMode, ScreenshotMethod, config
from .exception import CaptureUnavailableError, ViewportDetectionError
from .log import logger
from .viewport import (
    CANONICAL_SIZE,
    ViewportTransform,
    detect_active_rect,
    viewport_registry,
)
from .window import GameWindow, window_manager


class ScreenShot:
    """Capture a complete client frame and expose canonical-size images."""

    _MAX_ATTEMPTS = 10
    _RETRY_DELAY = 0.1

    def __init__(
        self,
        rect: tuple[int, int, int, int] | None = None,
        handle: int | GameWindow | None = None,
        _log: bool = False,
        debug: bool = False,
    ) -> None:
        """
        Args:
            rect: Optional canonical client rectangle ``(x, y, width, height)``.
            handle: Window handle, GameWindow, or the current window when omitted.
            _log: Whether to log capture timing.
            debug: Whether to display each raw capture.
        """
        if handle is None:
            self.gamewindow = window_manager.current
        elif hasattr(handle, "handle") and not isinstance(handle, (int, str)):
            self.gamewindow = handle
        else:
            self.gamewindow = GameWindow(handle)
        if self.gamewindow is None:
            raise CaptureUnavailableError(None, 0, "no game window selected")

        self.hwnd = int(self.gamewindow.handle)
        self.rect = rect
        self._log = _log
        self._debug = debug
        self._raw_image: Image.Image | None = None
        self._image: Image.Image | None = None
        self._transform: ViewportTransform | None = None
        self.time_cost = 0.0

        self._capture_and_normalize()

    def _screen_client_rect(self) -> tuple[int, int, int, int]:
        screen_rect = getattr(self.gamewindow, "screen_client_rect", None)
        if screen_rect is not None:
            return tuple(int(value) for value in screen_rect)

        client_rect = self.gamewindow.client_rect
        width = int(client_rect[2] - client_rect[0])
        height = int(client_rect[3] - client_rect[1])
        left = int(getattr(self.gamewindow, "client_left", 0))
        top = int(getattr(self.gamewindow, "client_top", 0))
        return left, top, width, height

    @staticmethod
    def _method_key(method) -> str:
        return str(getattr(method, "value", method))

    def _backend_method(self):
        return config.user.interaction_mode.backend.screenshot_method

    def _refresh_client_geometry(self) -> None:
        refresh = getattr(self.gamewindow, "refresh_client_geometry", None)
        if not callable(refresh):
            return
        instance_refresh = "refresh_client_geometry" in getattr(self.gamewindow, "__dict__", {})
        if getattr(self.gamewindow, "_geometry_refresh_enabled", False) or instance_refresh:
            refresh()

    def _normalize_raw(self, raw: Image.Image, capture_method: str) -> None:
        if raw is None:
            raise TypeError("capture returned None")
        if not isinstance(raw, Image.Image):
            raise TypeError("capture did not return a PIL image")

        self._raw_image = raw
        screen_rect = self._screen_client_rect()
        transform = viewport_registry.get(
            self.hwnd,
            capture_method,
            raw.size,
            screen_rect,
        )
        if transform is None:
            active_rect = detect_active_rect(raw)
            transform = ViewportTransform(
                handle=self.hwnd,
                capture_size=raw.size,
                active_capture_rect=active_rect,
                screen_client_rect=screen_rect,
            )
            viewport_registry.set(transform, capture_method)
        self._transform = transform

        normalized = transform.normalize(raw)
        if self.rect is None:
            self._image = normalized
        else:
            x, y, width, height = self.rect
            self._image = normalized.crop((x, y, x + width, y + height))

    def _capture_and_normalize(self) -> None:
        last_failure: Exception | None = None
        last_reason = "capture returned None"
        backend = config.user.interaction_mode.mode == InteractionMode.BACKEND
        backend_method = self._backend_method() if backend else None
        capture_method = (
            f"backend:{self._method_key(backend_method)}"
            if backend
            else "front"
        )

        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            try:
                self._refresh_client_geometry()
                if backend:
                    raw = self._capture_raw_backend(backend_method)
                else:
                    raw = self._capture_raw_front()

                if raw is None:
                    last_failure = None
                    last_reason = "capture returned None"
                else:
                    self._normalize_raw(raw, capture_method)
                    return
            except ViewportDetectionError as error:
                last_failure = error
                last_reason = str(error)
            except Exception as error:
                last_failure = error
                last_reason = str(error)

            if attempt < self._MAX_ATTEMPTS:
                time.sleep(self._RETRY_DELAY)

        if isinstance(last_failure, ViewportDetectionError):
            raise last_failure
        error = CaptureUnavailableError(self.hwnd, self._MAX_ATTEMPTS, last_reason)
        if last_failure is not None:
            raise error from last_failure
        raise error

    def _capture_raw_front(self) -> Image.Image:
        left, top, width, height = self._screen_client_rect()
        start = time.perf_counter()
        image = ImageGrab.grab((left, top, left + width, top + height))
        self._record_capture(image, start, f"front {(left, top, width, height)}")
        return image

    def _capture_raw_backend(self, method=None) -> Image.Image:
        """Capture the complete native client buffer without normalization."""
        method = self._backend_method() if method is None else method
        client_rect = self.gamewindow.client_rect
        client_width = int(client_rect[2] - client_rect[0])
        client_height = int(client_rect[3] - client_rect[1])
        start = time.perf_counter()

        h_wnd_dc = None
        mfc_dc = None
        save_dc = None
        save_bitmap = None
        image = None
        capture_error = None
        try:
            h_wnd_dc = win32gui.GetDC(self.hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(h_wnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            save_bitmap = win32ui.CreateBitmap()
            save_bitmap.CreateCompatibleBitmap(mfc_dc, client_width, client_height)
            save_dc.SelectObject(save_bitmap)

            if method == ScreenshotMethod.BITBLT or self._method_key(method) == self._method_key(ScreenshotMethod.BITBLT):
                save_dc.BitBlt(
                    (0, 0),
                    (client_width, client_height),
                    mfc_dc,
                    (int(client_rect[0]), int(client_rect[1])),
                    win32con.SRCCOPY,
                )
            elif method == ScreenshotMethod.PRINTWINDOW or self._method_key(method) == self._method_key(ScreenshotMethod.PRINTWINDOW):
                windll.user32.PrintWindow(self.hwnd, save_dc.GetSafeHdc(), 3)
            else:
                raise ValueError("method must be ScreenshotMethod.BITBLT or ScreenshotMethod.PRINTWINDOW")

            bmpinfo = save_bitmap.GetInfo()
            bmpstr = save_bitmap.GetBitmapBits(True)
            image = Image.frombuffer(
                "RGB",
                (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
                bmpstr,
                "raw",
                "BGRX",
                0,
                1,
            ).convert("RGB")

            if method == ScreenshotMethod.PRINTWINDOW or self._method_key(method) == self._method_key(ScreenshotMethod.PRINTWINDOW):
                image = image.crop(
                    (
                        int(client_rect[0]),
                        int(client_rect[1]),
                        int(client_rect[0]) + client_width,
                        int(client_rect[1]) + client_height,
                    )
                )
        except BaseException as error:
            capture_error = error
        finally:
            try:
                if save_bitmap is not None:
                    win32gui.DeleteObject(save_bitmap.GetHandle())
            except BaseException:
                pass
            try:
                if save_dc is not None:
                    save_dc.DeleteDC()
            except BaseException:
                pass
            try:
                if mfc_dc is not None:
                    mfc_dc.DeleteDC()
            except BaseException:
                pass
            try:
                if h_wnd_dc is not None:
                    win32gui.ReleaseDC(self.hwnd, h_wnd_dc)
            except BaseException:
                pass

        if capture_error is not None:
            raise capture_error
        if image is None:
            raise RuntimeError("capture produced no image")

        self._record_capture(image, start, f"backend [{method}] {client_rect}")
        return image

    def _record_capture(self, image: Image.Image, start: float, description: str) -> None:
        end = time.perf_counter()
        self.time_cost = round((end - start) * 1000, 2)
        if self._log:
            logger.info(f"screenshot {description} cost {self.time_cost} ms")
        if self._debug:
            image.show()

    # Compatibility wrappers retained for existing callers and tests.
    def _screenshot_front(self, window_rect=None) -> Image.Image:
        self._refresh_client_geometry()
        image = self._capture_raw_front()
        self._normalize_raw(image, "front")
        return image

    def _screenshot_backend(self, client_rect=None, method=None) -> Image.Image:
        method = self._backend_method() if method is None else method
        self._refresh_client_geometry()
        image = self._capture_raw_backend(method)
        self._normalize_raw(image, f"backend:{self._method_key(method)}")
        return image

    def save(self, file, *args, **kwargs) -> None:
        self._image.save(file, *args, **kwargs)
        logger.info(f"screenshot cost {self.time_cost} ms, at {file}")

    def get_raw_image(self) -> Image.Image:
        return self._raw_image

    def get_transform(self) -> ViewportTransform:
        return self._transform

    def get_image(self) -> Image.Image:
        return self._image
