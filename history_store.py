from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


HISTORY_DIR = Path("data")
HISTORY_PATH = HISTORY_DIR / "history.csv"
HISTORY_COLUMNS = [
    "snapshot_date",
    "snapshot_datetime",
    "competitor_code",
    "competitor_name",
    "count",
    "total_area",
    "avg_price",
    "total_price",
    "unconfirmed_count",
    "removed_count",
    "data_freshness",
    "last_checked_at",
]


def ensure_history_storage() -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    if not HISTORY_PATH.exists():
        pd.DataFrame(columns=HISTORY_COLUMNS).to_csv(HISTORY_PATH, index=False, encoding="utf-8-sig")
    return HISTORY_PATH


def read_history() -> pd.DataFrame:
    path = ensure_history_storage()
    df = pd.read_csv(path, encoding="utf-8-sig")
    if df.empty:
        return pd.DataFrame(columns=HISTORY_COLUMNS)

    for column in ("count", "total_area", "avg_price", "total_price", "unconfirmed_count", "removed_count"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    for column in ("data_freshness", "last_checked_at", "competitor_code", "competitor_name", "snapshot_date", "snapshot_datetime"):
        if column not in df.columns:
            df[column] = ""
        df[column] = df[column].fillna("")
    return df


def upsert_weekly_snapshot(competitor_code: str, competitor_name: str, stats: Dict, lifecycle: Optional[Dict] = None, freshness: str = "") -> Dict:
    now = datetime.now()
    snapshot_date = now.strftime("%Y-%m-%d")
    snapshot_datetime = now.strftime("%Y-%m-%d %H:%M:%S")
    lifecycle = lifecycle or {}

    record = {
        "snapshot_date": snapshot_date,
        "snapshot_datetime": snapshot_datetime,
        "competitor_code": competitor_code,
        "competitor_name": competitor_name,
        "count": int(stats.get("count", 0) or 0),
        "total_area": float(stats.get("total_area", 0) or 0),
        "avg_price": float(stats.get("avg_price", 0) or 0),
        "total_price": float(stats.get("total_price", 0) or 0),
        "unconfirmed_count": int(lifecycle.get("unconfirmed_count", 0) or 0),
        "removed_count": int(lifecycle.get("removed_count", 0) or 0),
        "data_freshness": str(freshness or ""),
        "last_checked_at": str(lifecycle.get("manual_checked_at") or snapshot_datetime),
    }

    df = read_history()
    if not df.empty:
        mask = (df["snapshot_date"] == snapshot_date) & (df["competitor_code"] == competitor_code)
        df = df.loc[~mask].copy()

    df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
    df = df.sort_values(["competitor_code", "snapshot_date", "snapshot_datetime"], ascending=[True, True, True])
    ensure_history_storage()
    df.to_csv(HISTORY_PATH, index=False, encoding="utf-8-sig")
    return record


def get_competitor_history(competitor_code: str) -> List[Dict]:
    df = read_history()
    if df.empty:
        return []

    df = df.loc[df["competitor_code"] == competitor_code].copy()
    if df.empty:
        return []

    df = df.sort_values(["snapshot_date", "snapshot_datetime"])
    return df.to_dict("records")


def get_portfolio_history() -> List[Dict]:
    df = read_history()
    if df.empty:
        return []

    def join_freshness(values):
        values = [str(x) for x in values if str(x)]
        return ", ".join(sorted(set(values)))

    grouped = (
        df.groupby("snapshot_date", as_index=False)
        .agg(
            {
                "count": "sum",
                "total_area": "sum",
                "total_price": "sum",
                "competitor_code": "nunique",
                "unconfirmed_count": "sum",
                "removed_count": "sum",
                "data_freshness": join_freshness,
            }
        )
        .rename(columns={"competitor_code": "competitors_included"})
    )

    grouped["avg_price"] = 0.0
    mask = grouped["total_area"] > 0
    grouped.loc[mask, "avg_price"] = grouped.loc[mask, "total_price"] / grouped.loc[mask, "total_area"]
    grouped["competitor_name"] = "Все конкуренты"
    grouped = grouped[
        [
            "snapshot_date",
            "count",
            "total_area",
            "avg_price",
            "total_price",
            "competitors_included",
            "unconfirmed_count",
            "removed_count",
            "data_freshness",
            "competitor_name",
        ]
    ]
    grouped = grouped.sort_values("snapshot_date")
    return grouped.to_dict("records")
