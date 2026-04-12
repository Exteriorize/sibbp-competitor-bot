from __future__ import annotations

from typing import Dict, List

from manual_store import load_manual_competitors
from sib_parser import parse_sibbp


STATIC_COMPETITORS: Dict[str, Dict[str, object]] = {
    "sibbp": {
        "code": "sibbp",
        "name": "Сибирский бизнес парк",
        "short_name": "SibBP",
        "parser": parse_sibbp,
        "enabled": True,
        "mode": "parsed",
    },
}

DEFAULT_COMPETITOR_CODE = "sibbp"


def list_all_competitors() -> Dict[str, Dict[str, object]]:
    competitors: Dict[str, Dict[str, object]] = dict(STATIC_COMPETITORS)
    for item in load_manual_competitors():
        competitors[item["code"]] = {
            "code": item["code"],
            "name": item["name"],
            "short_name": item.get("short_name") or item["name"],
            "enabled": item.get("enabled", True),
            "mode": "manual",
            "parser": None,
        }
    return competitors


COMPETITORS = list_all_competitors()


def refresh_competitors() -> Dict[str, Dict[str, object]]:
    global COMPETITORS
    COMPETITORS = list_all_competitors()
    return COMPETITORS


def get_competitor(code: str) -> Dict[str, object]:
    competitors = refresh_competitors()
    return competitors[code]


def list_enabled_competitors() -> List[Dict[str, object]]:
    competitors = refresh_competitors()
    return [item for item in competitors.values() if item.get("enabled")]
