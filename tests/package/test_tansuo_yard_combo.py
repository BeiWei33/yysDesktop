"""庭院识别改成组合判断（灯笼素材 + 封印锚点）。

背景（有日志实证）：绘卷跑到第 3 轮时，程序在庭院按了两次安卓返回键，第二次弹出
「确定退出游戏吗？」。阴阳师里只有庭院这一层按返回会问退出游戏，说明第一次返回后
**已经回到庭院**，但程序没认出庭院（认出来就会去点探索灯笼）。

原因：原来只靠单张 `yard_tansuo`（灯笼上的竖排「探索」）判定，实测同一庭院不同时刻
只有 0.7975（阈值 0.7，余量 0.1），而庭院有云雾动画、会随活动换入口，偶尔就掉到阈值以下。

改成组合判断：`yard_tansuo` 或 `yard_yinzhang`（封印入口锚点，实测庭院 1.0000、
40+ 张非庭院画面最高 0.4011）任一命中即视为庭院。
"""

from types import SimpleNamespace

import pytest

import src.package.tansuo as tansuo_module
from src.package.tansuo import TanSuo as ProductionTanSuo
from src.package.tansuo import TanSuoChapterUnavailable


class YardMachine:
    """模拟"是否在庭院"，并可控地让哪个素材命中

    Args:
        lantern_matches: yard_tansuo（灯笼）是否命中
        anchor_matches: yard_yinzhang（封印锚点）是否命中
        yard_sequence: 逐次覆盖 on_yard 的判定结果（用于模拟"判定过程中界面变了"），
            为空表示按素材命中情况判定
        emulator_enabled: 模拟器模式（决定能否按返回键）
    """

    def __init__(
        self,
        monkeypatch,
        *,
        lantern_matches: bool = True,
        anchor_matches: bool = True,
        yard_sequence: list[bool] | None = None,
        emulator_enabled: bool = True,
        quit_visible: bool = False,
    ):
        self.lantern_matches = lantern_matches
        self.anchor_matches = anchor_matches
        self.yard_sequence = list(yard_sequence or [])
        self.quit_visible = quit_visible
        self.clicks: list = []
        self.back_key_presses = 0
        self.yard_checks = 0

        runner = object.__new__(ProductionTanSuo)
        runner.IMAGE_YARD_TANSUO = SimpleNamespace(name="yard_tansuo")
        runner.IMAGE_YARD_YINZHANG = SimpleNamespace(name="yard_yinzhang")
        runner.IMAGE_QUIT = SimpleNamespace(name="quit")
        runner.yard_tansuo_point = (663, 225)
        runner.yard_click_count = 0
        runner.yard_click_fail_count = 0
        runner.last_retreat_layers = 0
        runner.chapter_miss_count = 0
        runner.chapter_fix_failures = 0
        runner.chapter_unknown_count = 0
        runner.back_key_count = 0
        runner.back_key_total_count = 0
        runner.chapter_fix_interval = 1
        runner.target_chapter = 28
        runner.chapter_list_visible = lambda: False
        runner.current_chapter = lambda: None
        self.runner = runner

        def yard_now() -> bool:
            self.yard_checks += 1
            if self.yard_sequence:
                return self.yard_sequence.pop(0) if len(self.yard_sequence) > 1 else self.yard_sequence[0]
            return self.lantern_matches or self.anchor_matches

        self.yard_now = yard_now
        # on_yard 是真实实现之外的一层：这里换成受控判定
        runner.on_yard = yard_now

        def match(asset, *args, **kwargs):
            if asset.name == "yard_tansuo":
                return self.lantern_matches
            if asset.name == "yard_yinzhang":
                return self.anchor_matches
            return self.quit_visible

        monkeypatch.setattr(
            tansuo_module,
            "RuleImage",
            lambda asset, *a, **k: SimpleNamespace(
                asset=asset,
                match=lambda *aa, **kk: match(asset),
                center_point=lambda: f"point-{asset.name}",
            ),
        )
        monkeypatch.setattr(
            tansuo_module,
            "RuleOcr",
            lambda *a, **k: SimpleNamespace(get_raw_result=lambda: []),
        )
        monkeypatch.setattr(
            tansuo_module,
            "ScreenShot",
            lambda *a, **k: SimpleNamespace(rect=None, get_image=lambda: object()),
        )
        monkeypatch.setattr(
            tansuo_module,
            "Mouse",
            SimpleNamespace(click=lambda point=None, **kw: self.clicks.append(point)),
        )
        monkeypatch.setattr(
            tansuo_module,
            "KeyBoard",
            SimpleNamespace(esc=lambda *a, **k: self._press_back_key()),
        )
        monkeypatch.setattr(tansuo_module, "emulator", SimpleNamespace(enabled=emulator_enabled))
        monkeypatch.setattr(tansuo_module, "wait_until", lambda predicate, **k: predicate())
        monkeypatch.setattr(tansuo_module, "sleep", lambda *a, **k: None)

    def _press_back_key(self):
        self.back_key_presses += 1


def test_lantern_asset_alone_means_yard(monkeypatch):
    """灯笼素材命中即可判定为庭院（不需要锚点）。"""
    m = YardMachine(monkeypatch, lantern_matches=True, anchor_matches=False)

    assert m.runner.on_yard() is True


def test_anchor_alone_means_yard_and_clicks_measured_position(monkeypatch):
    """灯笼素材认不出、但封印锚点命中时，也要判定为庭院，并用实测固定坐标点灯笼。"""
    m = YardMachine(monkeypatch, lantern_matches=False, anchor_matches=True)
    located = m.runner.locate_yard_tansuo()

    assert located is not None
    point, how = located
    assert how == "封印锚点"
    assert (point.client_x, point.client_y) == ProductionTanSuo.yard_tansuo_point

    assert m.runner.back_to_exploration_from_yard() is True
    assert len(m.clicks) == 1
    assert (m.clicks[0].client_x, m.clicks[0].client_y) == ProductionTanSuo.yard_tansuo_point


def test_neither_asset_means_not_yard(monkeypatch):
    m = YardMachine(monkeypatch, lantern_matches=False, anchor_matches=False)

    assert m.runner.on_yard() is False
    assert m.runner.locate_yard_tansuo() is None


def test_lantern_asset_position_is_used_when_it_matches(monkeypatch):
    """灯笼素材命中时用素材自己的位置，而不是固定坐标。"""
    m = YardMachine(monkeypatch, lantern_matches=True, anchor_matches=False)

    point, how = m.runner.locate_yard_tansuo()

    assert how == "灯笼素材"
    assert point == "point-yard_tansuo"


def test_back_key_is_not_pressed_when_recheck_finds_yard(monkeypatch):
    """按返回键前会重新判定庭院：刚回到庭院就不再按返回键（这是上次故障的引爆点）。"""
    # 第 1 次判定（层首）不算庭院 → 进入 retreat_once；第 2 次判定（按键前复查）算庭院
    m = YardMachine(monkeypatch, yard_sequence=[False, True])

    assert m.runner.return_home() is False  # 点了灯笼但仍判定在庭院
    assert m.back_key_presses == 0
    assert m.clicks == ["point-yard_tansuo"]  # 走的是庭院分支（点灯笼），不是返回键


def test_yard_click_without_effect_stops_after_limit(monkeypatch):
    """连续判定为庭院但点灯笼后界面没变化 → 达到上限就明确报错停止。"""
    m = YardMachine(monkeypatch, lantern_matches=True)
    limit = ProductionTanSuo.yard_click_fail_limit

    with pytest.raises(TanSuoChapterUnavailable) as excinfo:
        for _ in range(limit):
            m.runner.return_home()

    assert f"连续{limit}次判定为庭院" in str(excinfo.value)
    assert len(m.clicks) == limit  # 每层只点一次，没有对着同一点猛点
    assert m.back_key_presses == 0  # 在庭院绝不按返回键


def test_yard_click_fail_counter_resets_when_leaving_yard(monkeypatch):
    """点灯笼后离开庭院（不再是庭院）时，连续失败计数要清零。"""
    m = YardMachine(monkeypatch, yard_sequence=[True, False, False])
    m.runner.yard_click_fail_count = 1

    assert m.runner.back_to_exploration_from_yard() is True

    assert m.runner.yard_click_fail_count == 0


def test_yard_asset_thresholds_stay_at_measured_values():
    """锁住庭院素材阈值：灯具素材实测同一庭院不同时刻只有 0.7975，
    阈值一旦被调回 0.7 以上，余量就只剩 0.1，会重新出现"回到庭院却认不出"。
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for rel in ("src/resource/tansuo/assets.json", "src/resource_ja/tansuo/assets.json"):
        data = json.loads((root / rel).read_text(encoding="utf-8"))
        scores = {i["name"]: float(i["score"]) for i in data["image_data"]}
        assert scores["yard_tansuo"] == 0.65, rel
        assert scores["yard_yinzhang"] == 0.7, rel


def test_yard_anchor_asset_exists_in_both_resource_sets():
    """锚点素材要在国服/日服两份资源里都存在，否则日服会退回单素材判定。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for rel in ("src/resource/tansuo/yard_yinzhang.png", "src/resource_ja/tansuo/yard_yinzhang.png"):
        path = root / rel
        assert path.exists(), rel
        assert path.stat().st_size > 1000, f"{rel} 太小，可能是空图"
