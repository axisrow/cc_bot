"""Фоновый цикл опроса статус-страницы и рассылки уведомлений."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter

from app.config import Config
from app.differ import diff
from app.formatter import format_event
from app.state import load_state, save_state
from app.status_client import StatusClient

logger = logging.getLogger(__name__)

# Небольшая пауза между сообщениями, чтобы не упереться в лимиты Telegram
_SEND_DELAY = 0.5


async def _send(bot: Bot, chat_id: int, text: str) -> None:
    """Отправить сообщение с обработкой rate-limit (429)."""
    try:
        await bot.send_message(chat_id, text)
    except TelegramRetryAfter as exc:
        logger.warning("Rate limit, ждём %s c", exc.retry_after)
        await asyncio.sleep(exc.retry_after)
        await bot.send_message(chat_id, text)


async def poll_once(
    bot: Bot,
    client: StatusClient,
    config: Config,
    state: dict,
) -> dict:
    """Один цикл опроса: fetch -> diff -> отправка -> возврат нового состояния."""
    snapshot = await client.fetch()
    was_initialized = state.get("initialized", False)

    events, new_state = diff(snapshot, state)

    if not was_initialized:
        # Первый запуск: молча засеваем состояние, один стартовый пинг.
        save_state(new_state)
        logger.info(
            "Первый запуск: засеяно %d инцидентов, %d работ, %d компонентов",
            len(new_state["incidents"]),
            len(new_state["maintenances"]),
            len(new_state["components"]),
        )
        if config.chat_id is not None:
            await _send(
                bot,
                config.chat_id,
                "✅ <b>Monitoring started</b>\nWatching status.claude.com for "
                "incidents, maintenance and component changes.",
            )
        return new_state

    if events and config.chat_id is not None:
        logger.info("Отправляю %d уведомлений", len(events))
        for event in events:
            await _send(bot, config.chat_id, format_event(event, config.timezone))
            await asyncio.sleep(_SEND_DELAY)
    elif events:
        logger.warning("Есть %d событий, но CHAT_ID не задан — не отправляю", len(events))

    save_state(new_state)
    return new_state


async def run_poller(bot: Bot, config: Config, client: StatusClient) -> None:
    """Бесконечный цикл опроса. Запускается как фоновая задача рядом с polling."""
    state = load_state()
    logger.info(
        "Поллер запущен: интервал %d c, цель %s",
        config.poll_interval,
        config.chat_id if config.chat_id is not None else "(CHAT_ID не задан)",
    )

    while True:
        try:
            state = await poll_once(bot, client, config, state)
        except asyncio.CancelledError:
            logger.info("Поллер остановлен")
            raise
        except Exception:
            logger.exception("Ошибка во время опроса")
        await asyncio.sleep(config.poll_interval)
