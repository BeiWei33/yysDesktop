import json
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
RESOURCE = ROOT / "src" / "resource" / "jiejietupo"


def _asset(name: str) -> dict:
    data = json.loads((RESOURCE / "assets.json").read_text(encoding="utf-8"))
    return next(item for item in data["image_data"] if item["name"] == name)


def _score(fixture_name: str, asset_name: str) -> float:
    asset = _asset(asset_name)
    screenshot = cv2.imread(str(FIXTURES / fixture_name), cv2.IMREAD_COLOR)
    template = cv2.imread(str(RESOURCE / asset["file"]), cv2.IMREAD_COLOR)
    x, y, width, height = asset["region"]
    crop = screenshot[y : y + height, x : x + width]
    result = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(result)[1])


def test_current_locked_lineup_fixture_matches_configured_lock_asset():
    asset = _asset("lock")
    assert _score("jiejietupo_lineup_locked.png", "lock") >= float(asset["score"])


def test_current_locked_lineup_fixture_does_not_match_configured_unlock_asset():
    asset = _asset("unlock")
    assert _score("jiejietupo_lineup_locked.png", "unlock") < float(asset["score"])


def test_current_unlocked_lineup_fixture_matches_configured_unlock_asset():
    asset = _asset("unlock")
    assert _score("jiejietupo_lineup_unlocked.png", "unlock") >= float(asset["score"])


def test_current_unlocked_lineup_fixture_does_not_match_configured_lock_asset():
    asset = _asset("lock")
    assert _score("jiejietupo_lineup_unlocked.png", "lock") < float(asset["score"])
