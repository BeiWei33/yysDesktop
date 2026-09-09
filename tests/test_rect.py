import pytest

from src.utils.point import Rectangle


def test_x_y_width_height():
    rect = Rectangle(10, 20, 100, 200)
    assert rect.x1 == 10
    assert rect.y1 == 20
    assert rect.width == 100
    assert rect.height == 200
    assert rect.x2 == 110
    assert rect.y2 == 220
    assert (rect.x1, rect.y1, rect.x2, rect.y2) == (10, 20, 110, 220)
    assert rect.get_box() == (10, 20, 100, 200)
    center = rect.get_center_point()
    assert (center.client_x, center.client_y) == (60, 120)


def test_x_y_x2_y2():
    rect = Rectangle(10, 20, x2=30, y2=60)
    assert rect.x1 == 10
    assert rect.y1 == 20
    assert rect.width == 20
    assert rect.height == 40
    assert rect.x2 == 30
    assert rect.y2 == 60
    assert (rect.x1, rect.y1, rect.x2, rect.y2) == (10, 20, 30, 60)
    assert rect.get_box() == (10, 20, 20, 40)
    center = rect.get_center_point()
    assert (center.client_x, center.client_y) == (20, 40)


def test_no_args():
    with pytest.raises(ValueError):
        Rectangle()


def test_assert_x2_width():
    with pytest.raises(ValueError):
        Rectangle(10, 20, x2=30, width=25)


def test_assert_x2_height():
    with pytest.raises(ValueError):
        Rectangle(10, 20, x2=30, height=25)


def test_assert_x2_without_width_height():
    with pytest.raises(ValueError):
        Rectangle(10, 20)


def test_assert_x2_width_height():
    with pytest.raises(ValueError):
        Rectangle(10, 20, x2=30, width=25, height=25)
