from random import Random

import pytest

from src.utils.input_motion import (
    generate_bezier_points,
    sample_bounded_delay,
    sample_centered_point,
)


def test_sample_centered_point_stays_in_bounds_and_clusters_near_center():
    rng = Random(7)
    bounds = (100, 200, 500, 600)
    points = [sample_centered_point(bounds, rng=rng) for _ in range(1000)]

    assert all(bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3] for x, y in points)

    mean_x = sum(x for x, _ in points) / len(points)
    mean_y = sum(y for _, y in points) / len(points)
    center_x = (bounds[0] + bounds[2]) / 2
    center_y = (bounds[1] + bounds[3]) / 2
    assert abs(mean_x - center_x) < 12
    assert abs(mean_y - center_y) < 12
    assert len(set(points)) > 100


def test_sample_bounded_delay_uses_centered_bounded_distribution():
    rng = Random(11)
    values = [sample_bounded_delay(2.0, rng=rng) for _ in range(1000)]

    assert all(1.0 <= value <= 4.0 for value in values)
    assert min(values) < 1.8
    assert max(values) > 2.2
    mean = sum(values) / len(values)
    assert 1.8 < mean < 2.3


def test_sample_bounded_delay_rejects_invalid_arguments():
    with pytest.raises(ValueError):
        sample_bounded_delay(0)
    with pytest.raises(ValueError):
        sample_bounded_delay(2, min_multiplier=2, max_multiplier=1)
    with pytest.raises(ValueError):
        sample_bounded_delay(2, min_multiplier=-1)


def test_generate_cubic_bezier_points_has_exact_endpoints_and_arc():
    points = generate_bezier_points((0, 0), (100, 0), steps=20, arc=40, jitter=0, rng=Random(3))

    assert len(points) == 21
    assert points[0] == (0, 0)
    assert points[-1] == (100, 0)
    assert any(y != 0 for _, y in points[1:-1])
    assert all(isinstance(value, int) for point in points for value in point)


def test_sample_bounded_delay_preserves_bounds_for_small_base_values():
    value = sample_bounded_delay(0.0001, rng=Random(2))

    assert 0.00005 <= value <= 0.0002


    class HugeJitter(Random):
        def gauss(self, mean, sigma):
            return mean + sigma * 1000

    straight = generate_bezier_points((0, 0), (100, 0), steps=20, arc=0, jitter=0, rng=Random(3))
    jittered = generate_bezier_points((0, 0), (100, 0), steps=20, arc=0, jitter=3, rng=HugeJitter(3))

    assert all(abs(x - base_x) <= 3 and abs(y - base_y) <= 3 for (x, y), (base_x, base_y) in zip(jittered, straight))


def test_generate_cubic_bezier_points_validates_steps():
    with pytest.raises(ValueError):
        generate_bezier_points((0, 0), (1, 1), steps=1)
