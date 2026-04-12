from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


DATA_DIR = Path("data")
MANUAL_COMPETITORS_PATH = DATA_DIR / "manual_competitors.json"
MANUAL_RECORDS_PATH = DATA_DIR / "manual_records.json"

SOURCE_OPTIONS = {
    "site": "Сайт",
    "cian": "ЦИАН",
    "yandex_realty": "Яндекс Недвижимость",
    "2gis": "2ГИС",
    "yandex_maps": "Яндекс Карты",
    "call": "Звонок",
    "broker": "Брокер",
    "sign": "Фото вывески",
    "other": "Другое",
}

STATUS_OPTIONS = {
    "free": "Есть свободные помещения",
    "no_free": "Нет свободных помещений",
    "no_data": "Нет данных",
}

RELIABILITY_OPTIONS = {
    "high": "Высокая",
    "medium": "Средняя",
    "low": "Низкая",
}


MANUAL_DEFAULTS = {
    "enabled": True,
    "mode": "manual",
}


def _ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not MANUAL_COMPETITORS_PATH.exists():
        MANUAL_COMPETITORS_PATH.write_text("[]", encoding="utf-8")
    if not MANUAL_RECORDS_PATH.exists():
        MANUAL_RECORDS_PATH.write_text("[]", encoding="utf-8")


def _read_json(path: Path) -> List[Dict]:
    _ensure_storage()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = []
    return data if isinstance(data, list) else []


def _write_json(path: Path, data: List[Dict]) -> None:
    _ensure_storage()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").replace("\xa0", " ")).strip()


def _slugify(text: str) -> str:
    text = _normalize_name(text).lower().replace("ё", "е")
    text = re.sub(r"[^0-9a-zа-я]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "competitor"


def load_manual_competitors() -> List[Dict]:
    competitors = _read_json(MANUAL_COMPETITORS_PATH)
    result: List[Dict] = []
    for item in competitors:
        name = _normalize_name(str(item.get("name", "")))
        code = str(item.get("code", "")).strip()
        if not name or not code:
            continue
        result.append(
            {
                "code": code,
                "name": name,
                "short_name": str(item.get("short_name") or name),
                "enabled": bool(item.get("enabled", True)),
                "mode": "manual",
            }
        )
    return result


def upsert_manual_competitor(name: str) -> Dict:
    name = _normalize_name(name)
    if not name:
        raise ValueError("Название конкурента не может быть пустым")

    competitors = load_manual_competitors()
    for item in competitors:
        if item["name"].lower() == name.lower():
            return item

    base_code = f"manual-{_slugify(name)}"
    code = base_code
    existing_codes = {item["code"] for item in competitors}
    index = 2
    while code in existing_codes:
        code = f"{base_code}-{index}"
        index += 1

    competitor = {
        "code": code,
        "name": name,
        "short_name": name,
        "enabled": True,
        "mode": "manual",
    }
    competitors.append(competitor)
    _write_json(MANUAL_COMPETITORS_PATH, competitors)
    return competitor


def load_manual_records() -> List[Dict]:
    records = _read_json(MANUAL_RECORDS_PATH)
    result: List[Dict] = []
    for item in records:
        competitor_code = str(item.get("competitor_code", "")).strip()
        competitor_name = _normalize_name(str(item.get("competitor_name", "")))
        if not competitor_code or not competitor_name:
            continue
        item["competitor_code"] = competitor_code
        item["competitor_name"] = competitor_name
        result.append(item)
    return result


def save_manual_record(record: Dict) -> Dict:
    competitor = upsert_manual_competitor(str(record.get("competitor_name", "")))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    free_area = float(record.get("free_area", 0) or 0)
    price_per_sqm = float(record.get("price_per_sqm", 0) or 0)
    total_price = float(record.get("total_price", 0) or 0)
    if total_price <= 0 and free_area > 0 and price_per_sqm > 0:
        total_price = round(free_area * price_per_sqm, 2)

    payload = {
        "competitor_code": competitor["code"],
        "competitor_name": competitor["name"],
        "source": str(record.get("source", "other")),
        "source_label": str(record.get("source_label") or SOURCE_OPTIONS.get(str(record.get("source", "other")), "Другое")),
        "source_url": str(record.get("source_url", "")).strip(),
        "status": str(record.get("status", "free")),
        "status_label": str(record.get("status_label") or STATUS_OPTIONS.get(str(record.get("status", "free")), "Есть свободные помещения")),
        "free_area": round(free_area, 2),
        "price_per_sqm": round(price_per_sqm, 2),
        "total_price": round(total_price, 2),
        "reliability": str(record.get("reliability", "medium")),
        "reliability_label": str(record.get("reliability_label") or RELIABILITY_OPTIONS.get(str(record.get("reliability", "medium")), "Средняя")),
        "comment": str(record.get("comment", "")).strip(),
        "checked_at": str(record.get("checked_at") or now),
    }

    records = load_manual_records()
    records.append(payload)
    _write_json(MANUAL_RECORDS_PATH, records)
    return payload


def get_latest_manual_record(competitor_code: str) -> Optional[Dict]:
    records = [item for item in load_manual_records() if item.get("competitor_code") == competitor_code]
    if not records:
        return None
    records.sort(key=lambda item: str(item.get("checked_at", "")))
    return records[-1]


def list_latest_manual_records() -> List[Dict]:
    latest: Dict[str, Dict] = {}
    for item in load_manual_records():
        code = str(item.get("competitor_code", ""))
        if not code:
            continue
        if code not in latest or str(item.get("checked_at", "")) > str(latest[code].get("checked_at", "")):
            latest[code] = item
    return sorted(latest.values(), key=lambda item: item.get("competitor_name", ""))



def delete_manual_competitor_data(competitor_code: str) -> Dict[str, int]:
    competitor_code = str(competitor_code or '').strip()
    if not competitor_code:
        return {'deleted_records': 0, 'deleted_competitors': 0}

    competitors = load_manual_competitors()
    filtered_competitors = [item for item in competitors if str(item.get('code', '')).strip() != competitor_code]
    deleted_competitors = len(competitors) - len(filtered_competitors)
    _write_json(MANUAL_COMPETITORS_PATH, filtered_competitors)

    records = load_manual_records()
    filtered_records = [item for item in records if str(item.get('competitor_code', '')).strip() != competitor_code]
    deleted_records = len(records) - len(filtered_records)
    _write_json(MANUAL_RECORDS_PATH, filtered_records)

    return {'deleted_records': deleted_records, 'deleted_competitors': deleted_competitors}


def list_manual_competitors_with_records() -> List[Dict]:
    competitors_by_code = {item['code']: item for item in load_manual_competitors()}
    latest_records = {item['competitor_code']: item for item in list_latest_manual_records()}
    result: List[Dict] = []

    for code, competitor in competitors_by_code.items():
        row = dict(competitor)
        row['latest_record'] = latest_records.get(code)
        result.append(row)

    result.sort(key=lambda item: str(item.get('name', '')).lower())
    return result

def build_items_from_manual_record(record: Optional[Dict]) -> List[Dict]:
    if not record:
        return []

    status = str(record.get("status", "free"))
    if status != "free":
        return []

    area = float(record.get("free_area", 0) or 0)
    price_per_sqm = float(record.get("price_per_sqm", 0) or 0)
    total_price = float(record.get("total_price", 0) or 0)
    if total_price <= 0 and area > 0 and price_per_sqm > 0:
        total_price = round(area * price_per_sqm, 2)

    title = str(record.get("comment") or "Ручная запись").strip() or "Ручная запись"
    return [
        {
            "company": record.get("competitor_name", ""),
            "type": "Ручной учет",
            "title": title,
            "area": round(area, 2),
            "price_value": round(price_per_sqm, 2),
            "price_per_sqm": round(price_per_sqm, 2),
            "price_m2": f"{int(price_per_sqm) if price_per_sqm.is_integer() else price_per_sqm} ₽/м²" if price_per_sqm > 0 else "нет",
            "total_price_value": round(total_price, 2),
            "total_price": f"{int(total_price) if total_price.is_integer() else total_price} ₽" if total_price > 0 else "нет",
            "url": record.get("source_url", ""),
            "source_url": record.get("source_url", ""),
            "source_label": record.get("source_label", "Другое"),
            "reliability_label": record.get("reliability_label", "Средняя"),
            "checked_at": record.get("checked_at", ""),
        }
    ]
