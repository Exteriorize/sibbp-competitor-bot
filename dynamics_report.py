from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


AREA_FORMAT = '#,##0.0 "м²"'
RUB_FORMAT = '#,##0 "₽"'
RUB_M2_FORMAT = '#,##0.00 "₽/м²"'


def _apply_header_style(ws):
    fill = PatternFill(fill_type="solid", fgColor="D9EAD3")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.fill = fill


def _autowidth(ws):
    for column_cells in ws.columns:
        max_len = 0
        col_idx = column_cells[0].column
        col_letter = get_column_letter(col_idx)
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            if len(value) > max_len:
                max_len = len(value)
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, 14), 36)


def _write_history_sheet(writer, df: pd.DataFrame, sheet_name: str) -> None:
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    ws = writer.book[sheet_name]
    _apply_header_style(ws)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    header_map = {str(ws.cell(row=1, column=col).value): col for col in range(1, ws.max_column + 1)}
    for row in range(2, ws.max_row + 1):
        for header, fmt in {
            "Свободная площадь, м²": AREA_FORMAT,
            "Средняя цена, ₽/м²": RUB_M2_FORMAT,
            "Суммарная стоимость, ₽": RUB_FORMAT,
        }.items():
            col = header_map.get(header)
            if col:
                ws.cell(row=row, column=col).number_format = fmt
    _autowidth(ws)


def _add_chart(writer, source_sheet: str, chart_sheet: str, title: str, data_col_name: str, y_title: str, position: str) -> None:
    wb = writer.book
    ws = wb[source_sheet]
    chart_ws = wb[chart_sheet] if chart_sheet in wb.sheetnames else wb.create_sheet(chart_sheet)

    header_map = {str(ws.cell(row=1, column=col).value): col for col in range(1, ws.max_column + 1)}
    data_col = header_map.get(data_col_name)
    if not data_col:
        chart_ws[position] = f"Нет данных для графика: {data_col_name}"
        return

    if chart_ws["A1"].value is None:
        chart_ws["A1"] = title
        chart_ws["A1"].font = Font(bold=True, size=14)
        chart_ws.column_dimensions["A"].width = 26

    if ws.max_row >= 2:
        chart = LineChart()
        chart.title = data_col_name
        chart.y_axis.title = y_title
        chart.x_axis.title = "Дата"
        chart.height = 9
        chart.width = 22

        data = Reference(ws, min_col=data_col, min_row=1, max_row=ws.max_row)
        categories = Reference(ws, min_col=1, min_row=2, max_row=ws.max_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(categories)
        chart_ws.add_chart(chart, position)
    else:
        chart_ws[position] = "Для построения графика пока недостаточно данных."


def create_dynamics_report(records: Iterable[dict], competitor_name: str, output_path: Optional[str] = None) -> str:
    records = list(records)
    if output_path is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        safe_name = "".join(ch for ch in competitor_name if ch.isalnum() or ch in ("_", "-", " ")).strip() or "competitor"
        output_path = str(Path("reports") / f"dynamic_{safe_name}_{timestamp}.xlsx")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=["snapshot_date", "count", "total_area", "avg_price", "total_price", "unconfirmed_count", "removed_count", "data_freshness", "competitor_name"])

    for column in ["snapshot_date", "count", "total_area", "avg_price", "total_price", "unconfirmed_count", "removed_count", "data_freshness", "competitor_name"]:
        if column not in df.columns:
            df[column] = ""

    df = df[["snapshot_date", "count", "total_area", "avg_price", "total_price", "unconfirmed_count", "removed_count", "data_freshness", "competitor_name"]].copy()
    df = df.rename(
        columns={
            "snapshot_date": "Дата",
            "count": "Найдено помещений",
            "total_area": "Свободная площадь, м²",
            "avg_price": "Средняя цена, ₽/м²",
            "total_price": "Суммарная стоимость, ₽",
            "unconfirmed_count": "Неподтвержденных объектов",
            "removed_count": "Объектов в архиве",
            "data_freshness": "Свежесть данных",
            "competitor_name": "Конкурент",
        }
    )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        _write_history_sheet(writer, df, "История")
        _add_chart(writer, "История", "Графики", f"Динамика — {competitor_name}", "Свободная площадь, м²", "Площадь, м²", "A3")
        _add_chart(writer, "История", "Графики", f"Динамика — {competitor_name}", "Найдено помещений", "Количество", "A22")
        _add_chart(writer, "История", "Графики", f"Динамика — {competitor_name}", "Неподтвержденных объектов", "Количество", "A41")

    return output_path


def create_portfolio_dynamics_report(records: Iterable[dict], output_path: Optional[str] = None) -> str:
    records = list(records)
    if output_path is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        output_path = str(Path("reports") / f"portfolio_dynamics_{timestamp}.xlsx")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=["snapshot_date", "competitors_included", "count", "total_area", "avg_price", "total_price", "unconfirmed_count", "removed_count", "data_freshness"])

    for column in ["snapshot_date", "competitors_included", "count", "total_area", "avg_price", "total_price", "unconfirmed_count", "removed_count", "data_freshness"]:
        if column not in df.columns:
            df[column] = ""

    df = df[["snapshot_date", "competitors_included", "count", "total_area", "avg_price", "total_price", "unconfirmed_count", "removed_count", "data_freshness"]].copy()
    df = df.rename(
        columns={
            "snapshot_date": "Дата",
            "competitors_included": "Конкурентов в расчете",
            "count": "Найдено помещений",
            "total_area": "Свободная площадь, м²",
            "avg_price": "Средняя цена, ₽/м²",
            "total_price": "Суммарная стоимость, ₽",
            "unconfirmed_count": "Неподтвержденных объектов",
            "removed_count": "Объектов в архиве",
            "data_freshness": "Свежесть данных",
        }
    )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        _write_history_sheet(writer, df, "История")
        _add_chart(writer, "История", "Графики", "Динамика — все конкуренты", "Свободная площадь, м²", "Площадь, м²", "A3")
        _add_chart(writer, "История", "Графики", "Динамика — все конкуренты", "Найдено помещений", "Количество", "A22")
        _add_chart(writer, "История", "Графики", "Динамика — все конкуренты", "Неподтвержденных объектов", "Количество", "A41")

    return output_path
