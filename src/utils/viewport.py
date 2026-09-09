from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from .exception import ViewportDetectionError


CANONICAL_SIZE: tuple[int, int] = (1136, 640)
_ACTIVE_CHANNEL_THRESHOLD = 12
_ACTIVE_OCCUPANCY_THRESHOLD = 0.02
_ASPECT_RATIO_TOLERANCE = 0.02
_EDGE_CORRECTION = 4
_MAX_EDGE_TRANSITION_DENSITY = 0.05
_LUMA_TRANSITION_THRESHOLD = 12
_MIN_ACTIVE_SIZE = (384, 216)
_TARGET_ASPECT_RATIO = CANONICAL_SIZE[0] / CANONICAL_SIZE[1]


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


@dataclass(frozen=True)
class ViewportTransform:
    handle: int
    capture_size: tuple[int, int]
    active_capture_rect: tuple[int, int, int, int]
    screen_client_rect: tuple[int, int, int, int]

    @property
    def _active_size(self) -> tuple[int, int]:
        left, top, right, bottom = self.active_capture_rect
        return right - left, bottom - top

    def normalize(self, image: Image.Image) -> Image.Image:
        active = image.crop(self.active_capture_rect)
        if active.size == CANONICAL_SIZE:
            return active
        return active.resize(CANONICAL_SIZE, Image.Resampling.LANCZOS)

    def canonical_to_backend(self, point: tuple[float, float]) -> tuple[int, int]:
        """Map canonical coordinates to the active capture rectangle.

        Kept as a compatibility helper for capture-space callers. Win32 mouse
        messages must use :meth:`canonical_to_input` instead.
        """
        x = _clamp(point[0], 0, CANONICAL_SIZE[0] - 1)
        y = _clamp(point[1], 0, CANONICAL_SIZE[1] - 1)
        left, top, _, _ = self.active_capture_rect
        active_width, active_height = self._active_size
        return (
            round(left + x * (active_width - 1) / (CANONICAL_SIZE[0] - 1)),
            round(top + y * (active_height - 1) / (CANONICAL_SIZE[1] - 1)),
        )

    def backend_to_canonical(self, point: tuple[float, float]) -> tuple[int, int]:
        """Map active capture coordinates back to canonical space.

        Kept as a compatibility helper; Win32 input coordinates use the
        client-space pair returned by :meth:`input_to_canonical`.
        """
        left, top, right, bottom = self.active_capture_rect
        x = _clamp(point[0], left, right - 1)
        y = _clamp(point[1], top, bottom - 1)
        active_width, active_height = self._active_size
        return (
            round((x - left) * (CANONICAL_SIZE[0] - 1) / (active_width - 1)),
            round((y - top) * (CANONICAL_SIZE[1] - 1) / (active_height - 1)),
        )

    def canonical_to_input(self, point: tuple[float, float]) -> tuple[int, int]:
        """Map canonical coordinates to the native Win32 client input space."""
        x = _clamp(point[0], 0, CANONICAL_SIZE[0] - 1)
        y = _clamp(point[1], 0, CANONICAL_SIZE[1] - 1)
        _, _, width, height = self.screen_client_rect
        return (
            round(x * (width - 1) / (CANONICAL_SIZE[0] - 1)),
            round(y * (height - 1) / (CANONICAL_SIZE[1] - 1)),
        )

    def input_to_canonical(self, point: tuple[float, float]) -> tuple[int, int]:
        """Map native Win32 client input coordinates to canonical space."""
        _, _, width, height = self.screen_client_rect
        x = _clamp(point[0], 0, width - 1)
        y = _clamp(point[1], 0, height - 1)
        return (
            round(x * (CANONICAL_SIZE[0] - 1) / (width - 1)),
            round(y * (CANONICAL_SIZE[1] - 1) / (height - 1)),
        )

    def canonical_to_screen(self, point: tuple[float, float]) -> tuple[int, int]:
        x = _clamp(point[0], 0, CANONICAL_SIZE[0] - 1)
        y = _clamp(point[1], 0, CANONICAL_SIZE[1] - 1)
        left, top, width, height = self.screen_client_rect
        return (
            round(left + x * (width - 1) / (CANONICAL_SIZE[0] - 1)),
            round(top + y * (height - 1) / (CANONICAL_SIZE[1] - 1)),
        )

    def screen_to_canonical(self, point: tuple[float, float]) -> tuple[int, int]:
        left, top, width, height = self.screen_client_rect
        x = _clamp(point[0], left, left + width - 1)
        y = _clamp(point[1], top, top + height - 1)
        return (
            round((x - left) * (CANONICAL_SIZE[0] - 1) / (width - 1)),
            round((y - top) * (CANONICAL_SIZE[1] - 1) / (height - 1)),
        )

    def canonical_region_to_capture(
        self, rect: tuple[float, float, float, float]
    ) -> tuple[int, int, int, int]:
        x, y, width, height = rect
        canonical_left = _clamp(x, 0, CANONICAL_SIZE[0])
        canonical_top = _clamp(y, 0, CANONICAL_SIZE[1])
        canonical_right = _clamp(x + max(width, 0), 0, CANONICAL_SIZE[0])
        canonical_bottom = _clamp(y + max(height, 0), 0, CANONICAL_SIZE[1])
        canonical_right = max(canonical_left, canonical_right)
        canonical_bottom = max(canonical_top, canonical_bottom)

        active_left, active_top, _, _ = self.active_capture_rect
        active_width, active_height = self._active_size
        left = active_left + round(canonical_left * active_width / CANONICAL_SIZE[0])
        top = active_top + round(canonical_top * active_height / CANONICAL_SIZE[1])
        right = active_left + round(canonical_right * active_width / CANONICAL_SIZE[0])
        bottom = active_top + round(canonical_bottom * active_height / CANONICAL_SIZE[1])
        return left, top, right - left, bottom - top


GeometryKey = tuple[str, tuple[int, int], tuple[int, int, int, int]]


class ViewportRegistry:
    def __init__(self) -> None:
        self._entries: dict[int, tuple[GeometryKey, ViewportTransform]] = {}

    def get(
        self,
        handle: int,
        capture_method: str,
        capture_size: tuple[int, int],
        screen_client_rect: tuple[int, int, int, int],
    ) -> ViewportTransform | None:
        entry = self._entries.get(handle)
        if entry is None:
            return None
        geometry_key = (capture_method, capture_size, screen_client_rect)
        if entry[0] != geometry_key:
            self._entries.pop(handle, None)
            return None
        return entry[1]

    def set(self, transform: ViewportTransform, capture_method: str) -> None:
        geometry_key = (
            capture_method,
            transform.capture_size,
            transform.screen_client_rect,
        )
        self._entries[transform.handle] = (geometry_key, transform)

    def current(self, handle: int) -> ViewportTransform | None:
        """Return the currently registered transform for one window handle."""
        entry = self._entries.get(handle)
        return entry[1] if entry is not None else None

    def invalidate(self, handle: int) -> None:
        self._entries.pop(handle, None)

    def clear(self) -> None:
        self._entries.clear()


def _edge_transition_density(strip: np.ndarray, axis: int) -> float:
    luma = (
        strip[..., 0] * 0.2126
        + strip[..., 1] * 0.7152
        + strip[..., 2] * 0.0722
    )
    transitions = np.abs(np.diff(luma, axis=axis)) > _LUMA_TRANSITION_THRESHOLD
    if transitions.size == 0:
        return 0.0
    return float(np.mean(transitions))


def detect_active_rect(image: Image.Image) -> tuple[int, int, int, int]:
    """Return the trustworthy 16:9 content bounds within a raw capture."""
    pixels = np.asarray(image.convert("RGB"))
    active_pixels = np.any(pixels > _ACTIVE_CHANNEL_THRESHOLD, axis=2)
    active_rows = np.mean(active_pixels, axis=1) > _ACTIVE_OCCUPANCY_THRESHOLD
    active_columns = np.mean(active_pixels, axis=0) > _ACTIVE_OCCUPANCY_THRESHOLD

    row_indices = np.flatnonzero(active_rows)
    column_indices = np.flatnonzero(active_columns)
    if row_indices.size == 0 or column_indices.size == 0:
        raise ViewportDetectionError(image.size, (0, 0, 0, 0), "no active pixels")

    tight_left = int(column_indices[0])
    tight_top = int(row_indices[0])
    tight_right = int(column_indices[-1]) + 1
    tight_bottom = int(row_indices[-1]) + 1
    inactive_padding = (
        tight_left,
        tight_top,
        image.width - tight_right,
        image.height - tight_bottom,
    )
    left = 0 if inactive_padding[0] <= _EDGE_CORRECTION else tight_left
    top = 0 if inactive_padding[1] <= _EDGE_CORRECTION else tight_top
    right = image.width if inactive_padding[2] <= _EDGE_CORRECTION else tight_right
    bottom = image.height if inactive_padding[3] <= _EDGE_CORRECTION else tight_bottom
    base_rect = (left, top, right, bottom)

    candidates = {base_rect}
    for offset in range(1, _EDGE_CORRECTION + 1):
        if inactive_padding[0] > _EDGE_CORRECTION:
            strip = pixels[top:bottom, left : left + offset]
            if _edge_transition_density(strip, axis=0) <= _MAX_EDGE_TRANSITION_DENSITY:
                candidates.add((left + offset, top, right, bottom))
        if inactive_padding[1] > _EDGE_CORRECTION:
            strip = pixels[top : top + offset, left:right]
            if _edge_transition_density(strip, axis=1) <= _MAX_EDGE_TRANSITION_DENSITY:
                candidates.add((left, top + offset, right, bottom))
        if inactive_padding[2] > _EDGE_CORRECTION:
            strip = pixels[top:bottom, right - offset : right]
            if _edge_transition_density(strip, axis=0) <= _MAX_EDGE_TRANSITION_DENSITY:
                candidates.add((left, top, right - offset, bottom))
        if inactive_padding[3] > _EDGE_CORRECTION:
            strip = pixels[bottom - offset : bottom, left:right]
            if _edge_transition_density(strip, axis=1) <= _MAX_EDGE_TRANSITION_DENSITY:
                candidates.add((left, top, right, bottom - offset))

    plausible = []
    for candidate in candidates:
        width = candidate[2] - candidate[0]
        height = candidate[3] - candidate[1]
        if width < _MIN_ACTIVE_SIZE[0] or height < _MIN_ACTIVE_SIZE[1]:
            continue
        ratio_error = abs(width / height - _TARGET_ASPECT_RATIO) / _TARGET_ASPECT_RATIO
        if ratio_error <= _ASPECT_RATIO_TOLERANCE:
            plausible.append((ratio_error, -(width * height), candidate))

    if not plausible:
        raise ViewportDetectionError(image.size, base_rect, "no plausible 16:9 active rectangle")

    return min(plausible)[2]


viewport_registry = ViewportRegistry()
