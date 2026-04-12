from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd


DATA_DIR = Path("data")
REGISTRY_PATH = DATA_DIR / "item_registry.csv"
CHANGELOG_PATH = DATA_DIR / "change_log.csv"
REGISTRY_COLUMNS = [
    "competitor_code",
    "competitor_name",
    "item_key",
    "title",
    "type",
    "source_url",
    "source_kind",
    "first_seen",
    "last_seen",
    "last_snapshot_at",
    "status",
    "area",
    "price_per_sqm",
    "total_price",
    "confidence",
    "comment",
]
CHANGELOG_COLUMNS = [
    "event_at",
    "event_date",
    "competitor_code",
    "competitor_name",
    "item_key",
    "title",
    "type",
    "event_type",
    "old_value",
    "new_value",
    "note",
]


def _ensure_file(path: Path, columns: List[str]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        pd.DataFrame(columns=columns).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def ensure_storage() -> None:
    _ensure_file(REGISTRY_PATH, REGISTRY_COLUMNS)
    _ensure_file(CHANGELOG_PATH, CHANGELOG_COLUMNS)


def _read_csv(path: Path, columns: List[str]) -> pd.DataFrame:
    _ensure_file(path, columns)
    df = pd.read_csv(path, encoding="utf-8-sig")
    if df.empty:
        return pd.DataFrame(columns=columns)
    for column in columns:
        if column not in df.columns:
            df[column] = ""
    return df[columns].copy()


def read_registry() -> pd.DataFrame:
    df = _read_csv(REGISTRY_PATH, REGISTRY_COLUMNS)
    for column in ("area", "price_per_sqm", "total_price"):
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    for column in ("competitor_code", "competitor_name", "item_key", "title", "type", "source_url", "source_kind", "first_seen", "last_seen", "last_snapshot_at", "status", "confidence", "comment"):
        df[column] = df[column].fillna("").astype(str)
    return df


def write_registry(df: pd.DataFrame) -> None:
    for column in REGISTRY_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df = df[REGISTRY_COLUMNS].copy()
    df.to_csv(REGISTRY_PATH, index=False, encoding="utf-8-sig")


def read_change_log() -> pd.DataFrame:
    df = _read_csv(CHANGELOG_PATH, CHANGELOG_COLUMNS)
    for column in CHANGELOG_COLUMNS:
        df[column] = df[column].fillna("").astype(str)
    return df


def write_change_log(df: pd.DataFrame) -> None:
    for column in CHANGELOG_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df = df[CHANGELOG_COLUMNS].copy()
    df.to_csv(CHANGELOG_PATH, index=False, encoding="utf-8-sig")


def _norm(value: object) -> str:
    return str(value or "").strip()


def _float(value: object) -> float:
    try:
        return round(float(value or 0), 2)
    except Exception:
        return 0.0


def _parse_date(value: str) -> Optional[datetime]:
    value = _norm(value)
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _append_event(events: List[Dict], observed_at: datetime, competitor: Dict, item: Dict, event_type: str, old_value: object = "", new_value: object = "", note: str = "") -> None:
    events.append(
        {
            "event_at": observed_at.strftime("%Y-%m-%d %H:%M:%S"),
            "event_date": observed_at.strftime("%Y-%m-%d"),
            "competitor_code": _norm(competitor.get("code")),
            "competitor_name": _norm(competitor.get("name")),
            "item_key": _norm(item.get("item_key")),
            "title": _norm(item.get("title")),
            "type": _norm(item.get("type")),
            "event_type": event_type,
            "old_value": _norm(old_value),
            "new_value": _norm(new_value),
            "note": _norm(note),
        }
    )


def _row_to_dict(row: pd.Series) -> Dict:
    return {column: row.get(column, "") for column in REGISTRY_COLUMNS}


def sync_competitor_items(competitor: Dict, items: Iterable[Dict], meta: Optional[Dict] = None, observed_at: Optional[datetime] = None, remove_missing_after_days: int = 14) -> Dict:
    ensure_storage()
    observed_at = observed_at or datetime.now()
    observed_date = observed_at.strftime("%Y-%m-%d")
    meta = meta or {}

    competitor_code = _norm(competitor.get("code"))
    competitor_name = _norm(competitor.get("name"))
    mode = _norm(competitor.get("mode") or "parsed")
    latest_record = meta.get("latest_record") or {}
    manual_status = _norm(latest_record.get("status"))
    manual_checked_at = _norm(latest_record.get("checked_at"))
    manual_comment = _norm(latest_record.get("comment"))
    manual_confidence = _norm(latest_record.get("reliability_label"))

    df = read_registry()
    own = df.loc[df["competitor_code"] == competitor_code].copy()
    others = df.loc[df["competitor_code"] != competitor_code].copy()

    existing_map = {}
    for _, row in own.iterrows():
        existing_map[_norm(row.get("item_key"))] = _row_to_dict(row)

    events: List[Dict] = []
    current_rows: List[Dict] = []
    current_keys = set()

    for raw_item in items:
        item = dict(raw_item)
        item_key = _norm(item.get("item_key"))
        if not item_key:
            continue
        current_keys.add(item_key)
        old = existing_map.get(item_key)
        row = {
            "competitor_code": competitor_code,
            "competitor_name": competitor_name,
            "item_key": item_key,
            "title": _norm(item.get("title")),
            "type": _norm(item.get("type")),
            "source_url": _norm(item.get("source_url") or item.get("url")),
            "source_kind": _norm(item.get("source_kind") or mode),
            "first_seen": _norm((old or {}).get("first_seen")) or observed_date,
            "last_seen": observed_date,
            "last_snapshot_at": observed_at.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "active",
            "area": _float(item.get("area")),
            "price_per_sqm": _float(item.get("price_value") or item.get("price_per_sqm")),
            "total_price": _float(item.get("total_price_value") or item.get("total_price")),
            "confidence": _norm(item.get("reliability_label") or manual_confidence),
            "comment": _norm(item.get("comment") or manual_comment),
        }
        if row["total_price"] <= 0 and row["area"] > 0 and row["price_per_sqm"] > 0:
            row["total_price"] = round(row["area"] * row["price_per_sqm"], 2)

        if old is None:
            _append_event(events, observed_at, competitor, row, "new", new_value=row["title"], note="Новое помещение")
        else:
            old_status = _norm(old.get("status"))
            if old_status and old_status != "active":
                _append_event(events, observed_at, competitor, row, "reactivated", old_value=old_status, new_value="active", note="Помещение снова найдено")
            if abs(_float(old.get("area")) - row["area"]) > 0.09:
                _append_event(events, observed_at, competitor, row, "area_changed", old_value=old.get("area"), new_value=row["area"], note="Изменилась площадь")
            if abs(_float(old.get("price_per_sqm")) - row["price_per_sqm"]) > 0.09:
                _append_event(events, observed_at, competitor, row, "price_changed", old_value=old.get("price_per_sqm"), new_value=row["price_per_sqm"], note="Изменилась ставка")
            if abs(_float(old.get("total_price")) - row["total_price"]) > 0.09:
                _append_event(events, observed_at, competitor, row, "total_changed", old_value=old.get("total_price"), new_value=row["total_price"], note="Изменилась общая стоимость")

        current_rows.append(row)

    missing_rows = []
    for key, old in existing_map.items():
        if key in current_keys:
            continue
        row = dict(old)
        row["last_snapshot_at"] = observed_at.strftime("%Y-%m-%d %H:%M:%S")
        last_seen_dt = _parse_date(_norm(old.get("last_seen"))) or observed_at
        days_missing = max((observed_at.date() - last_seen_dt.date()).days, 0)
        new_status = _norm(old.get("status")) or "active"

        if mode == "parsed":
            if days_missing >= remove_missing_after_days:
                new_status = "removed"
            elif new_status != "removed":
                new_status = "unconfirmed"
        else:
            if manual_status in ("no_free", "no_data"):
                new_status = "removed"
            elif manual_status == "free":
                new_status = _norm(old.get("status")) or "active"

        if _norm(old.get("status")) != new_status:
            note = "Помещение пропало из выдачи" if new_status == "unconfirmed" else "Помещение выбыло из экспозиции"
            event_type = "missing" if new_status == "unconfirmed" else "removed"
            _append_event(events, observed_at, competitor, row, event_type, old_value=old.get("status"), new_value=new_status, note=note)
        row["status"] = new_status
        missing_rows.append(row)

    combined = pd.DataFrame(current_rows + missing_rows)
    if combined.empty:
        combined = pd.DataFrame(columns=REGISTRY_COLUMNS)
    else:
        for column in REGISTRY_COLUMNS:
            if column not in combined.columns:
                combined[column] = ""
        combined = combined[REGISTRY_COLUMNS].copy()

    updated = pd.concat([others, combined], ignore_index=True)
    write_registry(updated)

    if events:
        change_df = read_change_log()
        change_df = pd.concat([change_df, pd.DataFrame(events)], ignore_index=True)
        write_change_log(change_df)

    rows = [dict(x) for x in combined.to_dict("records")]
    active_count = sum(1 for x in rows if _norm(x.get("status")) == "active")
    unconfirmed_count = sum(1 for x in rows if _norm(x.get("status")) == "unconfirmed")
    removed_count = sum(1 for x in rows if _norm(x.get("status")) == "removed")
    return {
        "rows": rows,
        "events": events,
        "active_count": active_count,
        "unconfirmed_count": unconfirmed_count,
        "removed_count": removed_count,
        "active_items": [x for x in rows if _norm(x.get("status")) == "active"],
        "archive_items": [x for x in rows if _norm(x.get("status")) != "active"],
        "observed_at": observed_at.strftime("%Y-%m-%d %H:%M:%S"),
        "manual_checked_at": manual_checked_at,
    }


def get_competitor_registry(competitor_code: str) -> List[Dict]:
    df = read_registry()
    df = df.loc[df["competitor_code"] == _norm(competitor_code)].copy()
    if df.empty:
        return []
    df = df.sort_values(["status", "title", "first_seen"], ascending=[True, True, True])
    return df.to_dict("records")


def get_archive_items(competitor_code: Optional[str] = None) -> List[Dict]:
    df = read_registry()
    if competitor_code:
        df = df.loc[df["competitor_code"] == _norm(competitor_code)].copy()
    df = df.loc[df["status"] != "active"].copy()
    if df.empty:
        return []
    df = df.sort_values(["competitor_name", "status", "last_seen", "title"], ascending=[True, True, False, True])
    return df.to_dict("records")


def get_recent_changes(days: int = 14, competitor_code: Optional[str] = None) -> List[Dict]:
    df = read_change_log()
    if df.empty:
        return []
    if competitor_code:
        df = df.loc[df["competitor_code"] == _norm(competitor_code)].copy()
    cutoff = datetime.now().date().toordinal() - max(int(days), 0)
    keep_rows = []
    for _, row in df.iterrows():
        dt = _parse_date(_norm(row.get("event_at"))) or _parse_date(_norm(row.get("event_date")))
        if not dt:
            continue
        if dt.date().toordinal() >= cutoff:
            keep_rows.append(dict(row))
    keep_rows.sort(key=lambda item: (item.get("event_at", ""), item.get("competitor_name", ""), item.get("title", "")), reverse=True)
    return keep_rows


def build_item_age_metrics(row: Dict, reference_dt: Optional[datetime] = None) -> Dict:
    reference_dt = reference_dt or datetime.now()
    first_seen_dt = _parse_date(_norm(row.get("first_seen")))
    last_seen_dt = _parse_date(_norm(row.get("last_seen")))
    age_days = (reference_dt.date() - first_seen_dt.date()).days if first_seen_dt else 0
    stale_days = (reference_dt.date() - last_seen_dt.date()).days if last_seen_dt else 0
    result = dict(row)
    result["age_days"] = age_days
    result["stale_days"] = stale_days
    return result
