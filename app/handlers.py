"""Команды бота: /start и /test.

Бот автономен — сам опрашивает статус-страницу и шлёт уведомления (см. poller.py).
На произвольные сообщения он не реагирует; ручная проверка — только через /test.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramForbiddenError
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
        "присылаю RSS-уведомления об инцидентах; промежуточные статусы редактируют "
        "исходное сообщение, resolved приходит отдельной зелёной галкой.\n\n"
        "Команда /test — прислать текущее состояние прямо сейчас."
    )


@router.message(Command("test"))
async def cmd_test(
    message: Message, bot: Bot, config: Config, status_client: StatusClient
) -> None:
    """Прислать текущий статус status.claude.com.

    В личке отвечает прямо там; в группе ничего не пишет в чат, а шлёт ответ
    в личку вызвавшему (если у того открыт диалог с ботом).
    """
    try:
        snapshot = await status_client.fetch()
    except Exception:
        logger.exception("Не удалось получить статус для /test")
        text = "⚠️ Не удалось получить данные со status.claude.com. Попробуйте позже."
    else:
        text = format_overall(snapshot, config.timezone)

    if message.chat.type == ChatType.PRIVATE:
        await message.answer(text)
        return

    user = message.from_user
    if user is None:
        return
    try:
        await bot.send_message(user.id, text)
    except TelegramForbiddenError:
        logger.info("Не могу ответить на /test в личку %s — диалог с ботом не открыт", user.id)
