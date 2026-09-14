from types import SimpleNamespace

import pytest

import src.package.daoguantupo as daoguantupo_module
from src.package.daoguantupo import DaoGuanTuPo

from .utils import Package, check_package


class DaoGuanTuPoPackage(Package):
    resource_path = "daoguantupo"


def test_daoguantupo():
    check_package(DaoGuanTuPoPackage)


def _make_runner(monkeypatch, texts: list[str], flag_guanzhu: bool = True):
    """构造一个只带必要属性的道馆突破实例，OCR 返回给定文字。"""
    runner = object.__new__(DaoGuanTuPo)
    runner.flag_guanzhu = flag_guanzhu
    runner.flag_guanzhan = False
    runner.state = DaoGuanTuPo.STATE_IDLE
    runner.OCR_TITLE = SimpleNamespace(keyword="道馆突破")
    runner.OCR_DAOJISHI = SimpleNamespace(keyword="后开战")
    runner.OCR_REMAINTIME = SimpleNamespace(keyword="剩余突破时间")
    runner.OCR_GUANZHU = SimpleNamespace(keyword="馆主")
    runner.global_assets = SimpleNamespace(OCR_AUTO_FIGHT=SimpleNamespace(keyword="自动化战斗"))
    runner.IMAGE_TIAOZHAN = object()

    clicks = []

    monkeypatch.setattr(
        daoguantupo_module,
        "RuleOcr",
        lambda *args, **kwargs: SimpleNamespace(
            get_raw_result=lambda: [SimpleNamespace(text=text) for text in texts]
        ),
    )
    monkeypatch.setattr(daoguantupo_module, "sleep", lambda *args, **kwargs: None)
    runner.check_click = lambda *args, **kwargs: clicks.append(args[0] if args else None)
    return runner, clicks


def test_check_title_marks_owner_battle(monkeypatch):
    runner, _ = _make_runner(monkeypatch, ["馆主战"])

    runner.check_title()

    assert runner.state == DaoGuanTuPo.STATE_GUANZHU


def test_check_title_prefers_owner_over_remaining_time(monkeypatch):
    """馆主战那屏同时有「剩余突破时间」时，也要判成馆主战。"""
    runner, _ = _make_runner(monkeypatch, ["剩余突破时间", "馆主"])

    runner.check_title()

    assert runner.state == DaoGuanTuPo.STATE_GUANZHU


def test_check_title_marks_attackable_when_no_owner(monkeypatch):
    runner, _ = _make_runner(monkeypatch, ["剩余突破时间"])

    runner.check_title()

    assert runner.state == DaoGuanTuPo.STATE_WAIT_START


def test_owner_battle_skipped_when_disabled(monkeypatch):
    runner, clicks = _make_runner(monkeypatch, ["馆主"], flag_guanzhu=False)

    assert runner.check_and_enter_battle() is False
    assert clicks == []


def test_owner_battle_attacked_when_enabled(monkeypatch):
    runner, clicks = _make_runner(monkeypatch, ["馆主"], flag_guanzhu=True)

    assert runner.check_and_enter_battle() is True
    assert clicks == [runner.IMAGE_TIAOZHAN]


def test_normal_battle_attacked_regardless_of_owner_flag(monkeypatch):
    runner, clicks = _make_runner(monkeypatch, ["剩余突破时间"], flag_guanzhu=False)

    assert runner.check_and_enter_battle() is True
    assert clicks == [runner.IMAGE_TIAOZHAN]


def test_run_stops_after_skipping_owner(monkeypatch):
    runner, clicks = _make_runner(monkeypatch, ["馆主"], flag_guanzhu=False)
    runner.max = 3
    runner.n = 0
    called = []
    runner.wait_for_battle_ready = lambda: called.append("wait")

    monkeypatch.setattr(daoguantupo_module.logger, "ui", lambda *args, **kwargs: None)
    monkeypatch.setattr(daoguantupo_module.logger, "ui_warn", lambda *args, **kwargs: None)

    runner.run()

    assert clicks == []
    assert called == []
