from __future__ import annotations

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

from competitor_service import get_portfolio_priority_rows, load_all_competitor_snapshots, summarize_all_competitors
from config import CHAT_ID
from dynamics_report import create_portfolio_dynamics_report
from history_store import get_portfolio_history, upsert_weekly_snapshot
from portfolio_report import create_portfolio_report


MOSCOW_TZ = pytz.timezone("Europe/Moscow")


def _format_rub(value: float) -> str:
    if not value:
        return "нет"
    if abs(value - round(value)) < 1e-9:
        text = f"{int(round(value)):,}".replace(",", " ")
    else:
        text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} ₽"


def _render_summary_text(stats, priority_rows) -> str:
    lines = [
        "<b>Автоматическая сводка по всем конкурентам</b>",
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
    ]
    if priority_rows:
        lines.append("\n<b>Кого проверить в первую очередь:</b>")
        for row in priority_rows[:5]:
            if row.get("Балл", 0) <= 0:
                continue
            lines.append(f"• <b>{row['Конкурент']}</b> — {row['Приоритет']}: {row['Причины']}")
    return "\n".join(lines)


async def send_scheduled_summary(bot: Bot) -> None:
    if not CHAT_ID:
        return

    snapshots = load_all_competitor_snapshots(sync_state=True)
    for snapshot in snapshots:
        competitor = snapshot.get("competitor", {})
        upsert_weekly_snapshot(
            str(competitor.get("code", "")),
            str(competitor.get("name", "")),
            snapshot.get("stats", {}),
            lifecycle=snapshot.get("lifecycle", {}),
            freshness=(snapshot.get("freshness", {}) or {}).get("freshness_label", ""),
        )

    stats = summarize_all_competitors(snapshots)
    priority_rows = get_portfolio_priority_rows(snapshots)
    report_path = create_portfolio_report(snapshots)
    await bot.send_message(CHAT_ID, _render_summary_text(stats, priority_rows))
    with open(report_path, "rb") as report_file:
        await bot.send_document(CHAT_ID, report_file, caption="Автоматический Excel-отчет по всем конкурентам")


async def send_monday_dynamics(bot: Bot) -> None:
    if not CHAT_ID:
        return

    snapshots = load_all_competitor_snapshots(sync_state=True)
    for snapshot in snapshots:
        competitor = snapshot.get("competitor", {})
        upsert_weekly_snapshot(
            str(competitor.get("code", "")),
            str(competitor.get("name", "")),
            snapshot.get("stats", {}),
            lifecycle=snapshot.get("lifecycle", {}),
            freshness=(snapshot.get("freshness", {}) or {}).get("freshness_label", ""),
        )

    history = get_portfolio_history()
    report_path = create_portfolio_dynamics_report(history)
    with open(report_path, "rb") as report_file:
        await bot.send_document(CHAT_ID, report_file, caption="Динамика свободных площадей — все конкуренты")


async def send_call_priority_reminder(bot: Bot) -> None:
    if not CHAT_ID:
        return

    snapshots = load_all_competitor_snapshots(sync_state=True)
    priority_rows = [row for row in get_portfolio_priority_rows(snapshots) if int(row.get("Балл", 0) or 0) > 0]
    if not priority_rows:
        return

    lines = ["<b>Напоминание по ручной верификации</b>", "Ручные данные рекомендуется актуализировать раз в 2 недели.", ""]
    for row in priority_rows[:7]:
        lines.append(f"• <b>{row['Конкурент']}</b> — {row['Приоритет']}: {row['Причины']}")
    await bot.send_message(CHAT_ID, "\n".join(lines))


async def on_startup_scheduler(dispatcher) -> None:
    scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
    bot = dispatcher.bot

    scheduler.add_job(send_scheduled_summary, "cron", day_of_week="mon,thu", hour=10, minute=0, args=[bot], id="scheduled_summary", replace_existing=True)
    scheduler.add_job(send_monday_dynamics, "cron", day_of_week="mon", hour=10, minute=20, args=[bot], id="monday_dynamics", replace_existing=True)
    scheduler.add_job(send_call_priority_reminder, "cron", day_of_week="mon", hour=9, minute=40, args=[bot], id="call_priority_reminder", replace_existing=True)

    scheduler.start()
    dispatcher["scheduler"] = scheduler


async def on_shutdown_scheduler(dispatcher) -> None:
    scheduler = dispatcher.get("scheduler")
    if scheduler:
        scheduler.shutdown(wait=False)
