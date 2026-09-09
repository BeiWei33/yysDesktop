from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import src.package.baiguiyexing as baigui_module
from src.package.baiguiyexing import BaiGuiYeXing
from src.utils.point import Point
from src.utils.viewport import CANONICAL_SIZE, ViewportTransform, detect_active_rect

FIXTURE = Path(__file__).parent / "fixtures" / "baigui_dpi_padded.png"
TITLE = Path("src/resource/baiguiyexing/title.png")


def _match_score(image: Image.Image, template_path: Path) -> tuple[float, tuple[int, int]]:
    source = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    template = cv2.imread(str(template_path))
    result = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(result)
    return float(score), (int(location[0]), int(location[1]))


def test_baigui_title_matches_after_viewport_normalization():
    raw = Image.open(FIXTURE)
    active_rect = detect_active_rect(raw)
    assert active_rect[0:3] == (0, 0, 753)
    assert 424 <= active_rect[3] <= 427

    transform = ViewportTransform(
        handle=1,
        capture_size=raw.size,
        active_capture_rect=active_rect,
        screen_client_rect=(0, 0, active_rect[2], active_rect[3]),
    )
    raw_score, _ = _match_score(raw, TITLE)
    normalized = transform.normalize(raw)
    normalized_score, location = _match_score(normalized, TITLE)

    assert raw_score < 0.7, f"raw title score={raw_score:.4f}"
    assert normalized.size == CANONICAL_SIZE
    assert normalized_score >= 0.7, f"normalized title score={normalized_score:.4f}"
    assert 0 <= location[0] < CANONICAL_SIZE[0]
    assert 0 <= location[1] < CANONICAL_SIZE[1]


def _package_for_info(count: int, flag: bool = True):
    package = BaiGuiYeXing.__new__(BaiGuiYeXing)
    package.flag_screenshot = flag
    package.saved_screenshot_count = count
    return package


def test_task_finish_info_only_reports_saved_screenshot(monkeypatch):
    calls = []
    monkeypatch.setattr(baigui_module.logger, "ui", calls.append)

    _package_for_info(0).task_finish_info()
    assert calls == []

    _package_for_info(1).task_finish_info()
    assert len(calls) == 1
    assert "截图保存在" in calls[0]


def test_finish_increments_screenshot_count_after_successful_save(monkeypatch):
    package = _package_for_info(0)
    package.IMAGE_FINISH = object()
    package.IMAGE_JINRU = object()

    class FinishRule:
        def __init__(self, _asset):
            pass

        def match(self):
            return True

        def random_point(self):
            return Point(10, 10)

    monkeypatch.setattr(baigui_module, "RuleImage", FinishRule)
    monkeypatch.setattr(package, "screenshot", lambda: None)
    monkeypatch.setattr(baigui_module, "sleep", lambda *_args: None)
    monkeypatch.setattr(baigui_module.Mouse, "click", lambda *_args, **_kwargs: None)

    package.finish()

    assert package.saved_screenshot_count == 1


def test_finish_does_not_count_failed_screenshot(monkeypatch):
    package = _package_for_info(0)
    package.IMAGE_FINISH = object()
    package.IMAGE_JINRU = object()

    class FinishRule:
        def __init__(self, _asset):
            pass

        def match(self):
            return True

        def random_point(self):
            return Point(10, 10)

    monkeypatch.setattr(baigui_module, "RuleImage", FinishRule)
    monkeypatch.setattr(package, "screenshot", lambda: (_ for _ in ()).throw(OSError("save failed")))
    monkeypatch.setattr(baigui_module, "sleep", lambda *_args: None)

    try:
        package.finish()
    except OSError:
        pass
    else:
        raise AssertionError("expected screenshot failure")

    assert package.saved_screenshot_count == 0
