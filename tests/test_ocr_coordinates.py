from types import SimpleNamespace

import src.utils.paddleocr as paddleocr_module
from src.utils.paddleocr import OcrData, OcrDetector, get_ocrdata_from_result


def _raw_result():
    return {
        "rec_texts": ["开始"],
        "rec_scores": [0.99],
        "rec_boxes": [[10, 20, 30, 40]],
    }


def test_ocr_detector_zero_region_defaults_to_canonical_full_region(monkeypatch):
    monkeypatch.setattr(
        paddleocr_module.window_manager,
        "current",
        SimpleNamespace(client_rect=(0, 0, 753, 424)),
    )

    detector = OcrDetector(region=(0, 0, 0, 0))

    assert detector.region == (0, 0, 1136, 640)


def test_ocr_result_keeps_crop_coordinates_without_offset():
    item = get_ocrdata_from_result(_raw_result())[0]

    assert (item["BoxPoints"][0]["X"], item["BoxPoints"][0]["Y"]) == (10, 20)


def test_ocr_data_applies_region_offset_to_click_coordinates():
    item = get_ocrdata_from_result(_raw_result(), offset=(100, 200))[0]
    data = OcrData(item)

    assert (data.x1, data.y1, data.x2, data.y2) == (110, 220, 130, 240)
    assert (data.center.client_x, data.center.client_y) == (120, 230)
    assert data.center.click_bounds == (110, 220, 130, 240)
