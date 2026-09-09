from .utils import Package, check_package


class TanSuo(Package):
    resource_path = "tansuo"


def test_tansuo_drag_bounds_are_canonical():
    from src.package.tansuo import TanSuo as ProductionTanSuo

    assert ProductionTanSuo.view_drag_bounds() == (568, 1022)


def test_tansuo():
    check_package(TanSuo)
