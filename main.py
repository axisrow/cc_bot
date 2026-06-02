"""Точка входа: запуск Telegram-бота и фонового поллера статус-страницы."""

from __future__ import annotations

import asyncio
import logging

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app import handlers
from app.config import ConfigError, load_config
from app.poller import run_poller
from app.status_client import StatusClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("cc_bot")


async def main() -> None:
    try:
        config = load_config()
    except ConfigError as exc:
        logger.error("Ошибка конфигурации: %s", exc)
        raise SystemExit(1) from exc

    bot = Bot(
        token=config.token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True,
        ),
    )
    dp = Dispatcher()
    dp.include_router(handlers.router)

    # Одна общая HTTP-сессия на поллер и команду /status (переиспользование соединений).
    async with aiohttp.ClientSession() as session:
        client = StatusClient(session)

        # Фоновый опрос статус-страницы рядом с long-polling Telegram.
        poller_task = asyncio.create_task(run_poller(bot, config, client))

        logger.info("Запускаю polling…")
        try:
            # config и status_client прокидываются в хендлеры как контекстные kwargs
            await dp.start_polling(bot, config=config, status_client=client)
        finally:
            poller_task.cancel()
            try:
                await poller_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
