from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Tuple

from analytics import summarize
from competitors import get_competitor, list_enabled_competitors
from lifecycle_store import get_archive_items, get_recent_changes, sync_competitor_items
from manual_store import build_items_from_manual_record, get_latest_manual_record


FRESHNESS_LABELS = {
    "fresh": "свежие",
    "aging": "требуют проверки скоро",
    "stale": "требуют прозвона",
}

PRIORITY_LABELS = {
    "high": "Высокий",
    "medium": "Средний",
    "low": "Низкий",
}


def _slug(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def make_item_key(competitor_code: str, item: Dict) -> str:
    explicit = str(item.get("item_key") or "").strip()
    if explicit:
        return explicit
    base = [competitor_code, str(item.get("type") or ""), str(item.get("title") or ""), str(item.get("source_url") or item.get("url") or "")]
    token = "|".join(_slug(x) for x in base if str(x).strip())
    return token or f"{competitor_code}|manual-summary"


def _ensure_company(items: List[Dict], competitor: Dict[str, object], latest_record: Dict = None) -> List[Dict]:
    competitor_name = str(competitor.get("name") or "")
    competitor_code = str(competitor.get("code") or "")
    prepared: List[Dict] = []
    for item in items:
        row = dict(item)
        row.setdefault("company", competitor_name)
        row.setdefault("competitor_code", competitor_code)
        row.setdefault("source_kind", str(competitor.get("mode") or "parsed"))
        if latest_record:
            row.setdefault("checked_at", latest_record.get("checked_at", ""))
            row.setdefault("comment", latest_record.get("comment", ""))
            row.setdefault("reliability_label", latest_record.get("reliability_label", ""))
            row.setdefault("source_label", latest_record.get("source_label", ""))
        row["item_key"] = make_item_key(competitor_code, row)
        prepared.append(row)
    return prepared


def _parse_checked_at(value: str):
    value = str(value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def get_freshness_info(competitor: Dict, latest_record: Dict = None) -> Dict:
    mode = str(competitor.get("mode") or "parsed")
    now = datetime.now()
    if mode == "parsed":
        return {
            "freshness": "fresh",
            "freshness_label": FRESHNESS_LABELS["fresh"],
            "days_since_update": 0,
            "last_checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

    checked_at = _parse_checked_at((latest_record or {}).get("checked_at", ""))
    if not checked_at:
        return {
            "freshness": "stale",
            "freshness_label": "нет актуальной ручной проверки",
            "days_since_update": 999,
            "last_checked_at": "",
        }

    days = (now.date() - checked_at.date()).days
    if days <= 7:
        freshness = "fresh"
    elif days <= 14:
        freshness = "aging"
    else:
        freshness = "stale"
    return {
        "freshness": freshness,
        "freshness_label": FRESHNESS_LABELS[freshness],
        "days_since_update": max(days, 0),
        "last_checked_at": checked_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


def load_items_for_competitor(code: str) -> Tuple[Dict[str, object], List[Dict], Dict]:
    competitor = get_competitor(code)
    mode = str(competitor.get("mode", "parsed"))

    if mode == "manual":
        latest_record = get_latest_manual_record(str(competitor["code"]))
        items = build_items_from_manual_record(latest_record)
        items = _ensure_company(items, competitor, latest_record=latest_record or {})
        return competitor, items, {"latest_record": latest_record}

    parser = competitor["parser"]
    items = parser()
    items = _ensure_company(items, competitor)
    return competitor, items, {"latest_record": None}


def evaluate_priority(snapshot: Dict) -> Dict:
    competitor = snapshot.get("competitor", {})
    stats = snapshot.get("stats", {})
    lifecycle = snapshot.get("lifecycle", {})
    freshness = snapshot.get("freshness", {})
    score = 0
    reasons: List[str] = []

    if snapshot.get("error"):
        score += 100
        reasons.append("ошибка загрузки")
    if freshness.get("freshness") == "stale":
        score += 80
        reasons.append("ручные данные устарели более 14 дней")
    elif freshness.get("freshness") == "aging":
        score += 35
        reasons.append("скоро нужна ручная проверка")

    unconfirmed = int(lifecycle.get("unconfirmed_count", 0) or 0)
    if unconfirmed > 0:
        score += 50 + unconfirmed * 5
        reasons.append(f"неподтвержденных объектов: {unconfirmed}")

    if int(stats.get("count", 0) or 0) == 0 and str(competitor.get("mode")) == "manual":
        score += 20
        reasons.append("нет активных свободных площадей по ручным данным")

    if score >= 80:
        level = "high"
    elif score >= 35:
        level = "medium"
    else:
        level = "low"

    return {
        "priority": level,
        "priority_label": PRIORITY_LABELS[level],
        "priority_score": score,
        "priority_reasons": reasons,
    }


def build_competitor_snapshot(code: str, sync_state: bool = True) -> Dict:
    competitor = get_competitor(code)
    competitor_code = str(competitor["code"])
    competitor_name = str(competitor["name"])
    try:
        competitor_obj, items, meta = load_items_for_competitor(competitor_code)
        stats = summarize(items)
        latest_record = meta.get("latest_record")
        freshness = get_freshness_info(competitor_obj, latest_record)
        lifecycle = sync_competitor_items(competitor_obj, items, meta=meta) if sync_state else {
            "rows": [],
            "events": [],
            "active_count": stats.get("count", 0),
            "unconfirmed_count": 0,
            "removed_count": 0,
            "active_items": items,
            "archive_items": [],
            "manual_checked_at": freshness.get("last_checked_at", ""),
        }
        archive_items = lifecycle.get("archive_items") or get_archive_items(competitor_code)
        snapshot = {
            "competitor": competitor_obj,
            "items": items,
            "stats": stats,
            "latest_record": latest_record,
            "error": None,
            "checked_at": freshness.get("last_checked_at", ""),
            "lifecycle": lifecycle,
            "archive_items": archive_items,
            "freshness": freshness,
            "recent_changes": get_recent_changes(days=14, competitor_code=competitor_code),
        }
        snapshot.update(evaluate_priority(snapshot))
        return snapshot
    except Exception as exc:
        latest_record = get_latest_manual_record(competitor_code)
        freshness = get_freshness_info(competitor, latest_record)
        snapshot = {
            "competitor": competitor,
            "items": [],
            "stats": summarize([]),
            "latest_record": latest_record,
            "error": str(exc),
            "checked_at": freshness.get("last_checked_at", ""),
            "lifecycle": {"rows": [], "events": [], "active_count": 0, "unconfirmed_count": 0, "removed_count": 0, "active_items": [], "archive_items": []},
            "archive_items": get_archive_items(competitor_code),
            "freshness": freshness,
            "recent_changes": get_recent_changes(days=14, competitor_code=competitor_code),
        }
        snapshot.update(evaluate_priority(snapshot))
        return snapshot


def load_all_competitor_snapshots(sync_state: bool = True) -> List[Dict]:
    return [build_competitor_snapshot(str(competitor["code"]), sync_state=sync_state) for competitor in list_enabled_competitors()]


def flatten_snapshot_items(snapshots: List[Dict]) -> List[Dict]:
    items: List[Dict] = []
    for snapshot in snapshots:
        items.extend(snapshot.get("items", []))
    return items


def summarize_all_competitors(snapshots: List[Dict]) -> Dict:
    items = flatten_snapshot_items(snapshots)
    stats = summarize(items)
    stats["competitors_total"] = len(snapshots)
    stats["competitors_with_free"] = sum(1 for x in snapshots if (x.get("stats") or {}).get("count", 0) > 0)
    stats["competitors_with_errors"] = sum(1 for x in snapshots if x.get("error"))
    stats["competitors_without_data"] = sum(
        1
        for x in snapshots
        if (x.get("stats") or {}).get("count", 0) == 0 and not x.get("error")
    )
    stats["stale_competitors"] = sum(1 for x in snapshots if (x.get("freshness") or {}).get("freshness") == "stale")
    stats["aging_competitors"] = sum(1 for x in snapshots if (x.get("freshness") or {}).get("freshness") == "aging")
    stats["unconfirmed_count"] = sum(int((x.get("lifecycle") or {}).get("unconfirmed_count", 0) or 0) for x in snapshots)
    stats["removed_count"] = sum(int((x.get("lifecycle") or {}).get("removed_count", 0) or 0) for x in snapshots)
    return stats


def get_portfolio_priority_rows(snapshots: List[Dict]) -> List[Dict]:
    rows = []
    for snapshot in snapshots:
        competitor = snapshot.get("competitor", {})
        freshness = snapshot.get("freshness", {})
        lifecycle = snapshot.get("lifecycle", {})
        rows.append(
            {
                "competitor_code": competitor.get("code", ""),
                "Конкурент": competitor.get("name", ""),
                "Приоритет": snapshot.get("priority_label", "Низкий"),
                "Балл": snapshot.get("priority_score", 0),
                "Причины": "; ".join(snapshot.get("priority_reasons") or []) or "—",
                "Последняя проверка": freshness.get("last_checked_at", ""),
                "Свежесть": freshness.get("freshness_label", ""),
                "Неподтверждено": lifecycle.get("unconfirmed_count", 0),
                "Свободных помещений": (snapshot.get("stats") or {}).get("count", 0),
                "Свободная площадь, м²": (snapshot.get("stats") or {}).get("total_area", 0),
            }
        )
    rows.sort(key=lambda item: (int(item.get("Балл", 0)), float(item.get("Свободная площадь, м²", 0))), reverse=True)
    return rows
