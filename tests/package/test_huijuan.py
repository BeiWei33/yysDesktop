from types import SimpleNamespace

import src.package.huijuan as huijuan_module
from src.package.huijuan import HuiJuan as HuiJuanTask

from .utils import Package, check_package


class HuiJuan(Package):
    resource_path = "huijuan"


def test_huijuan():
    check_package(HuiJuan)


def _make_runner(monkeypatch, texts: list[str]) -> HuiJuanTask:
    runner = object.__new__(HuiJuanTask)
    monkeypatch.setattr(
        huijuan_module,
        "RuleOcr",
        lambda *args, **kwargs: SimpleNamespace(
            get_raw_result=lambda: [SimpleNamespace(text=text) for text in texts]
        ),
    )
    monkeypatch.setattr(huijuan_module, "sleep", lambda *args, **kwargs: None)
    return runner


def test_get_current_number_reads_ticket_count(monkeypatch):
    runner = _make_runner(monkeypatch, ["500/500", "28/30"])

    assert runner.get_current_number() == 28


def test_get_current_number_falls_back_when_ticket_count_is_missing(monkeypatch):
    runner = _make_runner(monkeypatch, ["500/500", "开始"])

    assert runner.get_current_number() == -1


def test_get_current_number_falls_back_when_ticket_count_is_unparsable(monkeypatch):
    runner = _make_runner(monkeypatch, ["满/30"])

    assert runner.get_current_number() == -1


def test_get_current_number_retries_before_giving_up(monkeypatch):
    runner = object.__new__(HuiJuanTask)
    reads = []

    def get_raw_result():
        reads.append(True)
        # 第一次读到游戏时钟，第二次才读到突破券数量
        texts = ["17:30"] if len(reads) == 1 else ["17:30", "22/30"]
        return [SimpleNamespace(text=text) for text in texts]

    monkeypatch.setattr(
        huijuan_module,
        "RuleOcr",
        lambda *args, **kwargs: SimpleNamespace(get_raw_result=get_raw_result),
    )
    monkeypatch.setattr(huijuan_module, "sleep", lambda *args, **kwargs: None)

    assert runner.get_current_number() == 22
    assert len(reads) == 2
