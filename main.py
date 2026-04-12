from aiogram import executor

from bot_app import dp
from scheduler_jobs import on_shutdown_scheduler, on_startup_scheduler


if __name__ == "__main__":
    executor.start_polling(
        dp,
        skip_updates=True,
        on_startup=on_startup_scheduler,
        on_shutdown=on_shutdown_scheduler,
    )
