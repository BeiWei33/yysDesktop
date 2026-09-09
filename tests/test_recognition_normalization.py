from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

import src.utils.image as image_module
import src.utils.paddleocr as paddleocr_module
from src.utils.image import RuleImage
from src.utils.paddleocr import OcrDetector, RuleOcr


def _template_image() -> Image.Image:
    image = Image.new("RGB", (60, 40), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 29, 19), fill="red")
    draw.rectangle((30, 0, 59, 19), fill="blue")
    draw.rectangle((0, 20, 29, 39), fill="green")
    draw.rectangle((30, 20, 59, 39), fill="black")
    return image


def test_rule_image_defaults_to_canonical_region(tmp_path, monkeypatch):
    monkeypatch.setattr(
        image_module.window_manager,
        "current",
        SimpleNamespace(client_width=753, client_height=424),
    )
    template_path = tmp_path / "template.png"
    _template_image().save(template_path)

    rule = RuleImage(file=template_path, score=0.9)

    assert rule.region == (0, 0, 1136, 640)


def test_rule_image_zero_region_defaults_to_canonical_region(tmp_path, monkeypatch):
    monkeypatch.setattr(
        image_module.window_manager,
        "current",
        SimpleNamespace(client_width=753, client_height=424),
    )
    template_path = tmp_path / "template.png"
    _template_image().save(template_path)

    rule = RuleImage(file=template_path, region=(0, 0, 0, 0), score=0.9)

    assert rule.region == (0, 0, 1136, 640)


def test_rule_image_crops_full_canonical_screenshot_before_matching(tmp_path, monkeypatch):
    template = _template_image()
    template_path = tmp_path / "template.png"
    template.save(template_path)

    canonical = Image.new("RGB", (1136, 640), "gray")
    canonical.paste(template, (200, 100))

    class FakeScreenShot:
        def __init__(self, image, rect=None):
            self._image = image
            self.rect = rect

        def get_image(self):
            return self._image

    monkeypatch.setattr(image_module, "ScreenShot", FakeScreenShot)
    screenshot = FakeScreenShot(canonical, rect=None)
    rule = RuleImage(file=template_path, region=(180, 80, 200, 120), score=0.9)

    assert rule.match(screenshot, normal=False, logger_lever="NONE") is True
    assert rule.match_result == (200, 100, 260, 140)


def test_rule_image_does_not_crop_region_screenshot_twice(tmp_path, monkeypatch):
    template = _template_image()
    template_path = tmp_path / "template.png"
    template.save(template_path)
    region = (180, 80, 200, 120)
    cropped = Image.new("RGB", (region[2], region[3]), "gray")
    cropped.paste(template, (20, 20))

    class FakeScreenShot:
        def __init__(self, image, rect):
            self._image = image
            self.rect = rect

        def get_image(self):
            return self._image

    monkeypatch.setattr(image_module, "ScreenShot", FakeScreenShot)
    screenshot = FakeScreenShot(cropped, rect=region)
    rule = RuleImage(file=template_path, region=region, score=0.9)

    assert rule.match(screenshot, normal=False, logger_lever="NONE") is True
    assert rule.match_result == (200, 100, 260, 140)


def test_rule_ocr_defaults_to_canonical_region(monkeypatch):
    monkeypatch.setattr(
        paddleocr_module.window_manager,
        "current",
        SimpleNamespace(client_rect=(0, 0, 753, 424)),
    )

    rule = RuleOcr(keyword="开始")

    assert rule.region == (0, 0, 1136, 640)
    assert rule.detector.region == (0, 0, 1136, 640)


def test_ocr_detector_adds_canonical_region_offset(monkeypatch):
    requested = {}

    class FakeScreenShot:
        def __init__(self, rect=None):
            requested["rect"] = rect

        def get_image(self):
            return Image.new("RGB", (200, 100), "white")

    def fake_detect(image):
        requested["image_size"] = image.size
        return [
            {
                "rec_texts": ["开始"],
                "rec_scores": [0.99],
                "rec_boxes": np.array([[10, 20, 30, 40]]),
            }
        ]

    monkeypatch.setattr(paddleocr_module, "ScreenShot", FakeScreenShot)
    monkeypatch.setattr(paddleocr_module.ocr_manager, "detect", fake_detect)

    result = OcrDetector(region=(100, 50, 200, 100)).get_raw_result()

    assert requested["rect"] == (100, 50, 200, 100)
    assert requested["image_size"] == (200, 100)
    assert len(result) == 1
    assert (result[0].x1, result[0].y1, result[0].x2, result[0].y2) == (
        110,
        70,
        130,
        90,
    )
    assert result[0].center.click_bounds == (110, 70, 130, 90)
