"""Команды бота: /start и /test.

Бот автономен — сам опрашивает статус-страницу и шлёт уведомления (см. poller.py).
На произвольные сообщения он не реагирует; ручная проверка — только через /test.
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Config
from app.formatter import format_overall
from app.status_client import StatusClient

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 <b>Claude Status Bot</b>\n\n"
        "Я слежу за <a href=\"https://status.claude.com\">status.claude.com</a> и "
        "присылаю уведомления об инцидентах, плановых работах и изменениях статусов сервисов.\n\n"
        "Команда /test — прислать текущее состояние прямо сейчас."
    )


@router.message(Command("test"))
async def cmd_test(message: Message, config: Config, status_client: StatusClient) -> None:
    """Прислать текущий статус status.claude.com тому, кто отправил команду."""
    try:
        snapshot = await status_client.fetch()
    except Exception:
        logger.exception("Не удалось получить статус для /test")
        await message.answer("⚠️ Не удалось получить данные со status.claude.com. Попробуйте позже.")
        return

    await message.answer(format_overall(snapshot, config.timezone))
