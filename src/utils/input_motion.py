"""Small, deterministic-friendly helpers for bounded input motion.

The helpers in this module do not interact with Windows or the game.  They only
produce bounded coordinates, delays, and paths so that the platform-specific
input adapter can execute them safely.
"""

from __future__ import annotations

from math import hypot
from random import Random
from typing import TypeAlias

Point2D: TypeAlias = tuple[int, int]
Bounds: TypeAlias = tuple[int, int, int, int]


def _rng_or_default(rng: Random | None) -> Random:
    return rng if rng is not None else _DEFAULT_RNG


def _validate_bounds(bounds: Bounds) -> None:
    if len(bounds) != 4:
        raise ValueError("bounds must contain left, top, right, bottom")
    left, top, right, bottom = bounds
    if right < left or bottom < top:
        raise ValueError("bounds must have right >= left and bottom >= top")


def _sample_truncated_normal(
    lower: float,
    upper: float,
    mean: float,
    standard_deviation: float,
    rng: Random,
) -> int:
    if lower == upper:
        return int(round(lower))

    # Rejection sampling preserves the center-weighted shape while guaranteeing
    # that a click never leaves the supplied safe rectangle.
    for _ in range(64):
        value = rng.gauss(mean, standard_deviation)
        if lower <= value <= upper:
            return int(round(value))

    # A pathological random source should still produce a safe point.
    return int(round(min(upper, max(lower, mean))))


def sample_centered_point(
    bounds: Bounds,
    *,
    rng: Random | None = None,
    sigma_ratio: float = 1 / 6,
) -> Point2D:
    """Sample a point from independent, center-weighted normal distributions.

    ``bounds`` uses ``(left, top, right, bottom)`` coordinates.  Samples are
    truncated to the rectangle, so the result is always safe to click.
    """
    _validate_bounds(bounds)
    if sigma_ratio <= 0:
        raise ValueError("sigma_ratio must be greater than zero")

    random_source = _rng_or_default(rng)
    left, top, right, bottom = bounds
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    sigma_x = max((right - left) * sigma_ratio, 0.5)
    sigma_y = max((bottom - top) * sigma_ratio, 0.5)
    return (
        _sample_truncated_normal(left, right, center_x, sigma_x, random_source),
        _sample_truncated_normal(top, bottom, center_y, sigma_y, random_source),
    )


def sample_bounded_delay(
    base_delay: float,
    *,
    min_multiplier: float = 0.5,
    max_multiplier: float = 2.0,
    rng: Random | None = None,
) -> float:
    """Return a center-weighted delay constrained by multipliers of a base.

    For example, ``sample_bounded_delay(2)`` always returns a value in
    ``[1, 4]``.  The normal distribution is truncated rather than clipped so
    values near the base delay remain the most common.
    """
    if base_delay <= 0:
        raise ValueError("base_delay must be greater than zero")
    if min_multiplier <= 0 or max_multiplier < min_multiplier:
        raise ValueError("delay multipliers must be positive and ordered")

    lower = base_delay * min_multiplier
    upper = base_delay * max_multiplier
    if lower == upper:
        return lower

    random_source = _rng_or_default(rng)
    # Center on the requested base where possible.  For unusual custom
    # multiplier ranges that exclude the base, use the nearest valid bound.
    mean = min(upper, max(lower, base_delay))
    standard_deviation = max(base_delay * 0.35, 0.001)
    for _ in range(64):
        candidate = random_source.gauss(mean, standard_deviation)
        if lower <= candidate <= upper:
            return candidate
    return min(upper, max(lower, mean))


def generate_bezier_points(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    steps: int = 24,
    arc: float = 0.0,
    jitter: float = 0.0,
    rng: Random | None = None,
) -> list[Point2D]:
    """Generate integer samples along a cubic Bézier path.

    ``arc`` offsets both control points along the perpendicular to the direct
    line.  ``jitter`` adds bounded Gaussian noise to interior samples only;
    endpoints remain exact.  The output contains ``steps + 1`` points.
    """
    if steps < 2:
        raise ValueError("steps must be at least 2")
    if jitter < 0:
        raise ValueError("jitter must not be negative")

    x0, y0 = start
    x3, y3 = end
    dx = x3 - x0
    dy = y3 - y0
    distance = hypot(dx, dy)

    if distance == 0:
        return [(int(round(x0)), int(round(y0))) for _ in range(steps + 1)]

    # Unit perpendicular vector.  Positive arc bends consistently to one side;
    # callers can pass a negative arc for the other side.
    perpendicular_x = -dy / distance
    perpendicular_y = dx / distance
    x1 = x0 + dx / 3 + perpendicular_x * arc
    y1 = y0 + dy / 3 + perpendicular_y * arc
    x2 = x0 + dx * 2 / 3 + perpendicular_x * arc
    y2 = y0 + dy * 2 / 3 + perpendicular_y * arc

    random_source = _rng_or_default(rng)
    points: list[Point2D] = []
    for index in range(steps + 1):
        t = index / steps
        inverse = 1 - t
        x = inverse**3 * x0 + 3 * inverse**2 * t * x1 + 3 * inverse * t**2 * x2 + t**3 * x3
        y = inverse**3 * y0 + 3 * inverse**2 * t * y1 + 3 * inverse * t**2 * y2 + t**3 * y3
        if 0 < index < steps and jitter:
            noise_x = max(-jitter, min(jitter, random_source.gauss(0, jitter)))
            noise_y = max(-jitter, min(jitter, random_source.gauss(0, jitter)))
            x += noise_x
            y += noise_y
        points.append((int(round(x)), int(round(y))))

    points[0] = (int(round(x0)), int(round(y0)))
    points[-1] = (int(round(x3)), int(round(y3)))
    return points


_DEFAULT_RNG = Random()
