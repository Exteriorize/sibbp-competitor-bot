from __future__ import annotations

from typing import Dict, List

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from analytics import summarize
from competitor_service import (
    build_competitor_snapshot,
    get_portfolio_priority_rows,
    load_all_competitor_snapshots,
    summarize_all_competitors,
)
from competitors import DEFAULT_COMPETITOR_CODE, get_competitor, refresh_competitors
from config import BOT_TOKEN
from dynamics_report import create_dynamics_report, create_portfolio_dynamics_report
from history_store import get_competitor_history, get_portfolio_history, upsert_weekly_snapshot
from manual_store import (
    RELIABILITY_OPTIONS,
    SOURCE_OPTIONS,
    STATUS_OPTIONS,
    delete_manual_competitor_data,
    list_manual_competitors_with_records,
    save_manual_record,
    upsert_manual_competitor,
)
from portfolio_report import create_portfolio_report
from report import create_report
from sib_parser import ParserError


if not BOT_TOKEN:
    raise RuntimeError(
        "Не указан BOT_TOKEN. Добавь токен в переменную окружения BOT_TOKEN."
    )


bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

CHAT_COMPETITOR: Dict[int, str] = {}
MANUAL_FLOW: Dict[int, Dict[str, object]] = {}
MAIN_BUTTONS = {
    "Выбор конкурента",
    "Проверить текущую сводку",
    "Выгрузить Excel",
    "Динамика",
    "Сводка по всем конкурентам",
    "Добавить/обновить вручную",
    "Удалить ручную запись",
    "Изменения",
    "Приоритет прозвона",
    "Архив",
}


def _escape(value) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_rub(value: float) -> str:
    if not value:
        return "нет"
    if abs(value - round(value)) < 1e-9:
        text = f"{int(round(value)):,}".replace(",", " ")
    else:
        text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} ₽"


def _format_rub_m2(value: float) -> str:
    if not value:
        return "нет"
    if abs(value - round(value)) < 1e-9:
        text = f"{int(round(value)):,}".replace(",", " ")
    else:
        text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} ₽/м²"


def _main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(KeyboardButton("Выбор конкурента"), KeyboardButton("Сводка по всем конкурентам"))
    keyboard.row(KeyboardButton("Проверить текущую сводку"), KeyboardButton("Выгрузить Excel"))
    keyboard.row(KeyboardButton("Динамика"), KeyboardButton("Изменения"), KeyboardButton("Архив"))
    keyboard.row(KeyboardButton("Приоритет прозвона"), KeyboardButton("Добавить/обновить вручную"))
    keyboard.row(KeyboardButton("Удалить ручную запись"))
    return keyboard


def _competitor_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    for code, competitor in refresh_competitors().items():
        if not competitor.get("enabled"):
            continue
        keyboard.add(InlineKeyboardButton(str(competitor["name"]), callback_data=f"competitor:{code}"))
    return keyboard


def _source_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=2)
    for code, name in SOURCE_OPTIONS.items():
        keyboard.insert(InlineKeyboardButton(name, callback_data=f"manual_source:{code}"))
    return keyboard


def _status_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    for code, name in STATUS_OPTIONS.items():
        keyboard.add(InlineKeyboardButton(name, callback_data=f"manual_status:{code}"))
    return keyboard


def _reliability_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=3)
    for code, name in RELIABILITY_OPTIONS.items():
        keyboard.insert(InlineKeyboardButton(name, callback_data=f"manual_reliability:{code}"))
    return keyboard


def _manual_delete_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    rows = list_manual_competitors_with_records()
    for row in rows:
        latest_record = row.get("latest_record") or {}
        status = str((latest_record.get("status_label") or "нет данных")).strip()
        button_text = f"{row['name']} — {status}"
        keyboard.add(InlineKeyboardButton(button_text[:64], callback_data=f"manual_delete:{row['code']}"))
    return keyboard


def _manual_delete_confirm_keyboard(code: str) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("Да, удалить", callback_data=f"manual_delete_confirm:{code}"),
        InlineKeyboardButton("Отмена", callback_data="manual_delete_cancel"),
    )
    return keyboard


def _get_selected_competitor(chat_id: int) -> Dict[str, object]:
    code = CHAT_COMPETITOR.get(chat_id, DEFAULT_COMPETITOR_CODE)
    competitors = refresh_competitors()
    if code not in competitors:
        code = DEFAULT_COMPETITOR_CODE
        CHAT_COMPETITOR[chat_id] = code
    return competitors[code]


def _render_items(items, limit: int = 20) -> str:
    if not items:
        return "Ничего не найдено."

    lines: List[str] = []
    for item in items[:limit]:
        title = _escape(item.get("title", "Без названия"))
        area = item.get("area", 0) or 0
        room_type = _escape(item.get("type", "Не указан"))
        price_value = item.get("price_value") or item.get("price_per_sqm") or 0
        total_value = item.get("total_price_value") or item.get("total_price") or 0
        source_url = str(item.get("source_url") or item.get("url") or "").strip()

        line = (
            f"• <b>{room_type}</b> — {title}\n"
            f"   Площадь: {area} м² | Цена/м²: {_format_rub_m2(float(price_value) if isinstance(price_value, (int, float)) else 0)} | "
            f"Всего: {_format_rub(float(total_value) if isinstance(total_value, (int, float)) else 0)}"
        )
        if source_url:
            line += f"\n   Ссылка: {_escape(source_url)}"
        lines.append(line)

    if len(items) > limit:
        lines.append(f"\n… и ещё {len(items) - limit} помещений")

    return "\n".join(lines)


def _render_manual_meta(meta: Dict) -> str:
    if not meta:
        return ""
    parts = [
        f"Статус: {meta.get('status_label', '—')}",
        f"Источник: {meta.get('source_label', '—')}",
    ]
    if meta.get("checked_at"):
        parts.append(f"Дата проверки: {meta['checked_at']}")
    if meta.get("reliability_label"):
        parts.append(f"Достоверность: {meta['reliability_label']}")
    if meta.get("comment"):
        parts.append(f"Комментарий: {_escape(meta['comment'])}")
    if meta.get("source_url"):
        parts.append(f"Ссылка: {_escape(meta['source_url'])}")
    return "\n".join(parts)


def _render_changes(changes: List[Dict], limit: int = 12) -> str:
    if not changes:
        return "Изменений за последние 14 дней пока нет."
    lines = []
    for row in changes[:limit]:
        lines.append(
            f"• <b>{_escape(row.get('title', 'Без названия'))}</b> [{_escape(row.get('type', ''))}]\n"
            f"   {row.get('event_at', '')} — {_escape(row.get('event_type', ''))}"
            f" | {_escape(row.get('note', ''))}"
        )
    if len(changes) > limit:
        lines.append(f"\n… и ещё {len(changes) - limit} изменений")
    return "\n".join(lines)


def _render_archive(archive_items: List[Dict], limit: int = 12) -> str:
    if not archive_items:
        return "Архив пуст."
    lines = []
    for row in archive_items[:limit]:
        lines.append(
            f"• <b>{_escape(row.get('title', 'Без названия'))}</b> [{_escape(row.get('type', ''))}]\n"
            f"   Статус: {_escape(row.get('status', ''))} | Последний раз найдено: {_escape(row.get('last_seen', ''))}"
        )
    if len(archive_items) > limit:
        lines.append(f"\n… и ещё {len(archive_items) - limit} записей в архиве")
    return "\n".join(lines)


def _render_priority_rows(rows: List[Dict], limit: int = 8) -> str:
    if not rows:
        return "Сейчас нет конкурентов, которым срочно нужен прозвон."
    lines = []
    for row in rows[:limit]:
        if int(row.get("Балл", 0) or 0) <= 0:
            continue
        lines.append(
            f"• <b>{_escape(row.get('Конкурент', ''))}</b> — {_escape(row.get('Приоритет', ''))}\n"
            f"   Причины: {_escape(row.get('Причины', '—'))}\n"
            f"   Свежесть: {_escape(row.get('Свежесть', ''))} | Последняя проверка: {_escape(row.get('Последняя проверка', ''))}"
        )
    return "\n".join(lines) if lines else "Сейчас нет конкурентов, которым срочно нужен прозвон."


def _render_all_summary_text(snapshots: List[Dict]) -> str:
    stats = summarize_all_competitors(snapshots)
    priority_rows = get_portfolio_priority_rows(snapshots)
    lines = [
        "<b>Сводка по всем конкурентам</b>",
        f"Конкурентов в базе: {stats['competitors_total']}",
        f"Со свободными помещениями: {stats['competitors_with_free']}",
        f"Без данных: {stats['competitors_without_data']}",
        f"Ошибок загрузки: {stats['competitors_with_errors']}",
        f"Найдено помещений: {stats['count']}",
        f"Суммарная площадь: {stats['total_area']} м²",
        f"Средневзвешенная цена: {stats['avg_price']} ₽/м²",
        f"Суммарная стоимость: {_format_rub(stats['total_price'])}",
        f"Неподтвержденных объектов: {stats['unconfirmed_count']}",
        f"Конкурентов с устаревшими ручными данными: {stats['stale_competitors']}",
        "",
        "<b>По конкурентам:</b>",
    ]

    for snapshot in snapshots:
        competitor = snapshot.get("competitor", {})
        name = _escape(competitor.get("name", "Без названия"))
        stats_row = snapshot.get("stats", {})
        latest_record = snapshot.get("latest_record") or {}
        freshness = snapshot.get("freshness", {})
        lifecycle = snapshot.get("lifecycle", {})
        error = snapshot.get("error")
        mode_label = "сайт" if competitor.get("mode") == "parsed" else "ручной"

        if error:
            lines.append(f"• <b>{name}</b> [{mode_label}] — ошибка: {_escape(error)}")
            continue

        if stats_row.get("count", 0) > 0:
            lines.append(
                f"• <b>{name}</b> [{mode_label}] — {stats_row['count']} помещ., {stats_row['total_area']} м², {stats_row['avg_price']} ₽/м²"
                f" | свежесть: {_escape(freshness.get('freshness_label', ''))}"
                f" | неподтв.: {lifecycle.get('unconfirmed_count', 0)}"
            )
        elif latest_record.get("status_label"):
            suffix = f" | источник: {latest_record.get('source_label', '')}" if latest_record.get("source_label") else ""
            lines.append(f"• <b>{name}</b> [{mode_label}] — {latest_record['status_label']}{suffix}")
        else:
            lines.append(f"• <b>{name}</b> [{mode_label}] — нет данных")

    lines.append("\n<b>Приоритет прозвона:</b>")
    lines.append(_render_priority_rows(priority_rows, limit=5))
    lines.append("\nКоманда /allreport — Excel по всем конкурентам")
    return "\n".join(lines)


def _parse_number(text: str) -> float:
    value = str(text).strip().replace(" ", "").replace(",", ".")
    return round(float(value), 2)


async def _load_selected(chat_id: int) -> Dict:
    competitor = _get_selected_competitor(chat_id)
    return build_competitor_snapshot(str(competitor["code"]), sync_state=True)


@dp.message_handler(commands=["start", "menu"])
async def start(message: types.Message):
    competitor = _get_selected_competitor(message.chat.id)
    text = (
        "Бот аналитики конкурентов запущен.\n\n"
        f"Текущий конкурент: <b>{_escape(competitor['name'])}</b>\n\n"
        "Что умеет бот:\n"
        "/check — проверить текущие помещения\n"
        "/report — Excel по выбранному конкуренту\n"
        "/all — сводка по всем конкурентам\n"
        "/allreport — Excel по всем конкурентам\n"
        "/dynamic — динамика по выбранному конкуренту\n"
        "/changes — что изменилось за 14 дней\n"
        "/priority — кого пора прозванивать\n"
        "/archive — архив и неподтвержденные объекты\n"
        "Кнопка «Добавить/обновить вручную» — ручной учет без сайта\n"
        "Кнопка «Удалить ручную запись» — удалить ошибочно внесенного конкурента"
    )
    await message.answer(text, reply_markup=_main_keyboard())


@dp.message_handler(commands=["cancel"])
async def cancel_manual_flow(message: types.Message):
    if MANUAL_FLOW.pop(message.chat.id, None) is not None:
        await message.answer("Ручной ввод отменен.", reply_markup=_main_keyboard())
    else:
        await message.answer("Сейчас нет активного ручного ввода.", reply_markup=_main_keyboard())


@dp.message_handler(lambda message: message.text == "Выбор конкурента")
async def choose_competitor(message: types.Message):
    await message.answer("Выбери конкурента:", reply_markup=_competitor_keyboard())


@dp.callback_query_handler(lambda callback: callback.data.startswith("competitor:"))
async def competitor_selected(callback: types.CallbackQuery):
    code = callback.data.split(":", 1)[1]
    competitors = refresh_competitors()
    if code not in competitors:
        await callback.answer("Неизвестный конкурент", show_alert=True)
        return

    CHAT_COMPETITOR[callback.message.chat.id] = code
    competitor = competitors[code]
    await callback.answer("Конкурент выбран")
    await callback.message.answer(
        f"Текущий конкурент: <b>{_escape(competitor['name'])}</b>",
        reply_markup=_main_keyboard(),
    )


@dp.message_handler(lambda message: message.text == "Удалить ручную запись")
@dp.message_handler(commands=["delete_manual"])
async def manual_delete_start(message: types.Message):
    rows = list_manual_competitors_with_records()
    if not rows:
        await message.answer("Пока нет ручных конкурентов для удаления.", reply_markup=_main_keyboard())
        return

    await message.answer(
        "Выбери ручного конкурента, которого нужно удалить:",
        reply_markup=_manual_delete_keyboard(),
    )


@dp.callback_query_handler(lambda callback: callback.data == "manual_delete_cancel")
async def manual_delete_cancel(callback: types.CallbackQuery):
    await callback.answer("Удаление отменено")
    await callback.message.answer("Удаление отменено.", reply_markup=_main_keyboard())


@dp.callback_query_handler(lambda callback: callback.data.startswith("manual_delete:"))
async def manual_delete_selected(callback: types.CallbackQuery):
    code = callback.data.split(":", 1)[1]
    rows = {item["code"]: item for item in list_manual_competitors_with_records()}
    row = rows.get(code)
    if not row:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    latest_record = row.get("latest_record") or {}
    details = []
    if latest_record.get("free_area"):
        details.append(f"Площадь: {latest_record['free_area']} м²")
    if latest_record.get("price_per_sqm"):
        details.append(f"Ставка: {_format_rub_m2(float(latest_record['price_per_sqm']))}")
    if latest_record.get("checked_at"):
        details.append(f"Дата: {latest_record['checked_at']}")

    text = f"Удалить ручную запись по конкуренту <b>{_escape(row['name'])}</b>?"
    if details:
        text += "\n" + "\n".join(details)
    text += "\n\nЭто удалит ручные данные и уберет конкурента из ручного списка."

    await callback.answer()
    await callback.message.answer(text, reply_markup=_manual_delete_confirm_keyboard(code))


@dp.callback_query_handler(lambda callback: callback.data.startswith("manual_delete_confirm:"))
async def manual_delete_confirm(callback: types.CallbackQuery):
    code = callback.data.split(":", 1)[1]
    rows = {item["code"]: item for item in list_manual_competitors_with_records()}
    row = rows.get(code)
    if not row:
        await callback.answer("Запись уже удалена", show_alert=True)
        await callback.message.answer("Запись уже удалена.", reply_markup=_main_keyboard())
        return

    result = delete_manual_competitor_data(code)
    if CHAT_COMPETITOR.get(callback.message.chat.id) == code:
        CHAT_COMPETITOR[callback.message.chat.id] = DEFAULT_COMPETITOR_CODE

    await callback.answer("Удалено")
    await callback.message.answer(
        f"Удалено: <b>{_escape(row['name'])}</b>\n"
        f"Удаленных ручных записей: {result['deleted_records']}",
        reply_markup=_main_keyboard(),
    )


@dp.message_handler(lambda message: message.text == "Добавить/обновить вручную")
@dp.message_handler(commands=["manual"])
async def manual_entry_start(message: types.Message):
    MANUAL_FLOW[message.chat.id] = {"state": "await_name", "data": {}}
    await message.answer(
        "Введи название конкурента для ручного учета.\n"
        "Можно указать существующего конкурента или нового.\n"
        "Для отмены отправь /cancel",
        reply_markup=_main_keyboard(),
    )


@dp.callback_query_handler(lambda callback: callback.data.startswith("manual_source:"))
async def manual_source_selected(callback: types.CallbackQuery):
    state = MANUAL_FLOW.get(callback.message.chat.id)
    if not state:
        await callback.answer("Сначала начни ручной ввод", show_alert=True)
        return

    code = callback.data.split(":", 1)[1]
    if code not in SOURCE_OPTIONS:
        await callback.answer("Неизвестный источник", show_alert=True)
        return

    state["data"]["source"] = code
    state["data"]["source_label"] = SOURCE_OPTIONS[code]
    state["state"] = "await_link"
    await callback.answer("Источник выбран")
    await callback.message.answer("Отправь ссылку на источник или поставь '-' если ссылки нет.")


@dp.callback_query_handler(lambda callback: callback.data.startswith("manual_status:"))
async def manual_status_selected(callback: types.CallbackQuery):
    state = MANUAL_FLOW.get(callback.message.chat.id)
    if not state:
        await callback.answer("Сначала начни ручной ввод", show_alert=True)
        return

    code = callback.data.split(":", 1)[1]
    if code not in STATUS_OPTIONS:
        await callback.answer("Неизвестный статус", show_alert=True)
        return

    state["data"]["status"] = code
    state["data"]["status_label"] = STATUS_OPTIONS[code]
    await callback.answer("Статус выбран")

    if code == "free":
        state["state"] = "await_area"
        await callback.message.answer("Введи свободную площадь в м². Например: 1250,5")
    else:
        state["data"]["free_area"] = 0.0
        state["data"]["price_per_sqm"] = 0.0
        state["data"]["total_price"] = 0.0
        state["state"] = "await_comment"
        await callback.message.answer("Добавь комментарий или отправь '-' если комментария нет.")


@dp.callback_query_handler(lambda callback: callback.data.startswith("manual_reliability:"))
async def manual_reliability_selected(callback: types.CallbackQuery):
    state = MANUAL_FLOW.get(callback.message.chat.id)
    if not state:
        await callback.answer("Сначала начни ручной ввод", show_alert=True)
        return

    code = callback.data.split(":", 1)[1]
    if code not in RELIABILITY_OPTIONS:
        await callback.answer("Неизвестный уровень достоверности", show_alert=True)
        return

    data = state.get("data", {})
    data["reliability"] = code
    data["reliability_label"] = RELIABILITY_OPTIONS[code]

    record = save_manual_record(data)
    competitor = upsert_manual_competitor(record["competitor_name"])
    CHAT_COMPETITOR[callback.message.chat.id] = competitor["code"]
    MANUAL_FLOW.pop(callback.message.chat.id, None)

    area = float(record.get("free_area", 0) or 0)
    rate = float(record.get("price_per_sqm", 0) or 0)
    total = float(record.get("total_price", 0) or 0)
    text = (
        "Ручная запись сохранена.\n\n"
        f"Конкурент: <b>{_escape(record['competitor_name'])}</b>\n"
        f"Статус: {record['status_label']}\n"
        f"Источник: {record['source_label']}\n"
        f"Площадь: {area} м²\n"
        f"Ставка: {_format_rub_m2(rate)}\n"
        f"Суммарная стоимость: {_format_rub(total)}"
    )
    if record.get("comment"):
        text += f"\nКомментарий: {_escape(record['comment'])}"
    await callback.answer("Сохранено")
    await callback.message.answer(text, reply_markup=_main_keyboard())


@dp.message_handler(lambda message: message.text == "Сводка по всем конкурентам")
@dp.message_handler(commands=["all"])
async def all_summary(message: types.Message):
    await message.answer("Собираю сводку по всем конкурентам...")
    snapshots = load_all_competitor_snapshots(sync_state=True)
    await message.answer(_render_all_summary_text(snapshots), reply_markup=_main_keyboard())


@dp.message_handler(commands=["allreport"])
async def all_report(message: types.Message):
    await message.answer("Готовлю Excel по всем конкурентам...")
    try:
        snapshots = load_all_competitor_snapshots(sync_state=True)
        report_path = create_portfolio_report(snapshots)
    except Exception as exc:
        await message.answer(f"Не удалось собрать общий отчет: {exc}", reply_markup=_main_keyboard())
        return

    with open(report_path, "rb") as f:
        await message.answer_document(f, caption="Excel-отчет по всем конкурентам", reply_markup=_main_keyboard())


@dp.message_handler(lambda message: message.text == "Проверить текущую сводку")
@dp.message_handler(commands=["check"])
async def check(message: types.Message):
    await message.answer("Проверяю данные...")
    try:
        snapshot = await _load_selected(message.chat.id)
    except ParserError as exc:
        await message.answer(f"Парсер не смог получить помещения: {exc}", reply_markup=_main_keyboard())
        return
    except Exception as exc:
        await message.answer(f"Ошибка парсинга: {exc}", reply_markup=_main_keyboard())
        return

    competitor = snapshot["competitor"]
    items = snapshot["items"]
    meta = {"latest_record": snapshot.get("latest_record")}
    stats = snapshot["stats"]
    freshness = snapshot.get("freshness", {})
    lifecycle = snapshot.get("lifecycle", {})
    text = (
        f"<b>{_escape(competitor['short_name'])}</b>\n"
        f"Найдено помещений: {stats['count']}\n"
        f"Суммарная площадь: {stats['total_area']} м²\n"
        f"Средневзвешенная цена: {stats['avg_price']} ₽/м²\n"
        f"Суммарная стоимость: {_format_rub(stats['total_price'])}\n"
        f"Свежесть данных: {_escape(freshness.get('freshness_label', ''))}\n"
        f"Неподтвержденных объектов: {lifecycle.get('unconfirmed_count', 0)}\n"
        f"Приоритет прозвона: {_escape(snapshot.get('priority_label', 'Низкий'))}"
    )

    latest_record = meta.get("latest_record")
    if latest_record and not items:
        text += "\n\n<b>Ручные данные:</b>\n" + _render_manual_meta(latest_record)
    else:
        text += f"\n\n<b>Примеры:</b>\n{_render_items(items)}"
        if latest_record:
            text += "\n\n<b>Источник ручной записи:</b>\n" + _render_manual_meta(latest_record)

    await message.answer(text, reply_markup=_main_keyboard())


@dp.message_handler(lambda message: message.text == "Выгрузить Excel")
@dp.message_handler(commands=["report"])
async def report(message: types.Message):
    await message.answer("Готовлю Excel...")
    try:
        snapshot = await _load_selected(message.chat.id)
        report_path = create_report(snapshot["items"], competitor=snapshot["competitor"], lifecycle=snapshot.get("lifecycle"))
    except ParserError as exc:
        await message.answer(f"Парсер не смог получить помещения: {exc}", reply_markup=_main_keyboard())
        return
    except Exception as exc:
        await message.answer(f"Не удалось собрать отчет: {exc}", reply_markup=_main_keyboard())
        return

    caption = f"Excel-отчет по {snapshot['competitor']['name']}"
    if snapshot.get("latest_record") and not snapshot["items"]:
        caption += " (по ручной записи)"
    with open(report_path, "rb") as f:
        await message.answer_document(f, caption=caption, reply_markup=_main_keyboard())


@dp.message_handler(lambda message: message.text == "Динамика")
@dp.message_handler(commands=["dynamic"])
async def dynamic_report(message: types.Message):
    competitor = _get_selected_competitor(message.chat.id)
    competitor_code = str(competitor["code"])
    competitor_name = str(competitor["name"])

    await message.answer("Готовлю Excel с динамикой...")
    try:
        snapshot = await _load_selected(message.chat.id)
        upsert_weekly_snapshot(
            competitor_code,
            competitor_name,
            snapshot.get("stats", {}),
            lifecycle=snapshot.get("lifecycle", {}),
            freshness=(snapshot.get("freshness", {}) or {}).get("freshness_label", ""),
        )
        history = get_competitor_history(competitor_code)
        report_path = create_dynamics_report(history, competitor_name)
    except Exception as exc:
        await message.answer(f"Не удалось собрать динамику: {exc}", reply_markup=_main_keyboard())
        return

    with open(report_path, "rb") as f:
        await message.answer_document(f, caption=f"Динамика свободных площадей — {competitor_name}", reply_markup=_main_keyboard())


@dp.message_handler(commands=["portfolio_dynamic"])
async def portfolio_dynamic_report(message: types.Message):
    await message.answer("Готовлю общую динамику по всем конкурентам...")
    try:
        history = get_portfolio_history()
        report_path = create_portfolio_dynamics_report(history)
    except Exception as exc:
        await message.answer(f"Не удалось собрать общую динамику: {exc}", reply_markup=_main_keyboard())
        return

    with open(report_path, "rb") as f:
        await message.answer_document(f, caption="Динамика свободных площадей — все конкуренты", reply_markup=_main_keyboard())


@dp.message_handler(lambda message: message.text == "Изменения")
@dp.message_handler(commands=["changes"])
async def changes(message: types.Message):
    snapshot = await _load_selected(message.chat.id)
    await message.answer(
        f"<b>Изменения за 14 дней — {_escape(snapshot['competitor']['name'])}</b>\n" + _render_changes(snapshot.get("recent_changes") or []),
        reply_markup=_main_keyboard(),
    )


@dp.message_handler(lambda message: message.text == "Архив")
@dp.message_handler(commands=["archive"])
async def archive(message: types.Message):
    snapshot = await _load_selected(message.chat.id)
    await message.answer(
        f"<b>Архив / неподтвержденные объекты — {_escape(snapshot['competitor']['name'])}</b>\n" + _render_archive(snapshot.get("archive_items") or []),
        reply_markup=_main_keyboard(),
    )


@dp.message_handler(lambda message: message.text == "Приоритет прозвона")
@dp.message_handler(commands=["priority"])
async def priority(message: types.Message):
    snapshots = load_all_competitor_snapshots(sync_state=True)
    rows = get_portfolio_priority_rows(snapshots)
    await message.answer(
        "<b>Приоритет прозвона</b>\n" + _render_priority_rows(rows),
        reply_markup=_main_keyboard(),
    )


@dp.message_handler(commands=["debug"])
async def debug(message: types.Message):
    competitor = _get_selected_competitor(message.chat.id)
    try:
        snapshot = await _load_selected(message.chat.id)
    except Exception as exc:
        await message.answer(f"Ошибка парсинга: {exc}", reply_markup=_main_keyboard())
        return

    items = snapshot["items"]
    stats = summarize(items)
    lifecycle = snapshot.get("lifecycle", {})
    type_lines = []
    for room_type, data in stats["by_type"].items():
        type_lines.append(
            f"• {room_type}: {data['count']} шт., {data['area']} м², {_format_rub(data['total_price'])}, {_format_rub_m2(data['avg_price'])}"
        )

    if not type_lines:
        type_lines.append("• Нет данных по типам помещений")

    text = (
        f"<b>DEBUG — {_escape(competitor['name'])}</b>\n"
        f"Записей: {len(items)}\n"
        f"Площадь: {stats['total_area']} м²\n"
        f"Средневзвешенная цена: {stats['avg_price']} ₽/м²\n"
        f"Суммарная стоимость: {_format_rub(stats['total_price'])}\n"
        f"Неподтверждено: {lifecycle.get('unconfirmed_count', 0)}\n"
        f"В архиве: {lifecycle.get('removed_count', 0)}\n\n"
        f"<b>По типам:</b>\n" + "\n".join(type_lines)
    )
    latest_record = snapshot.get("latest_record")
    if latest_record:
        text += "\n\n<b>Ручная запись:</b>\n" + _render_manual_meta(latest_record)
    await message.answer(text, reply_markup=_main_keyboard())


@dp.message_handler(lambda message: message.chat.id in MANUAL_FLOW)
async def manual_flow_text(message: types.Message):
    state = MANUAL_FLOW.get(message.chat.id)
    if not state:
        return

    text = (message.text or "").strip()
    if text in MAIN_BUTTONS:
        await message.answer("Сначала заверши ручной ввод или отправь /cancel.")
        return

    data = state.setdefault("data", {})
    current_state = state.get("state")

    try:
        if current_state == "await_name":
            competitor = upsert_manual_competitor(text)
            data["competitor_name"] = competitor["name"]
            state["state"] = "await_source"
            await message.answer("Выбери источник данных:", reply_markup=_source_keyboard())
            return

        if current_state == "await_link":
            data["source_url"] = "" if text == "-" else text
            state["state"] = "await_status"
            await message.answer("Укажи статус конкурента:", reply_markup=_status_keyboard())
            return

        if current_state == "await_area":
            data["free_area"] = _parse_number(text)
            state["state"] = "await_rate"
            await message.answer("Введи ставку за м² в рублях. Если ставки нет, отправь 0.")
            return

        if current_state == "await_rate":
            data["price_per_sqm"] = _parse_number(text)
            data["total_price"] = round(float(data.get("free_area", 0)) * float(data.get("price_per_sqm", 0)), 2)
            state["state"] = "await_comment"
            await message.answer("Добавь комментарий или отправь '-' если комментария нет.")
            return

        if current_state == "await_comment":
            data["comment"] = "" if text == "-" else text
            state["state"] = "await_reliability"
            await message.answer("Оцени достоверность данных:", reply_markup=_reliability_keyboard())
            return
    except ValueError:
        await message.answer("Не смог распознать число. Попробуй ещё раз, например: 1250,5")
        return

    await message.answer("Сначала выбери вариант на кнопках или отправь /cancel.")
