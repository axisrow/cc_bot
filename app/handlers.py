"""Команды бота: /start, /status, /id."""

from __future__ import annotations

import logging

from aiogram import F, Router
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
        "Команды:\n"
        "• /status — текущее состояние\n"
        "• /id — узнать ID этого чата (для настройки CHAT_ID)"
    )


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    chat = message.chat
    await message.answer(
        f"Chat ID: <code>{chat.id}</code>\n"
        f"Type: <code>{chat.type}</code>\n\n"
        "Впишите этот ID в переменную <code>CHAT_ID</code> в .env, чтобы получать уведомления сюда."
    )


@router.message(Command("status"))
async def cmd_status(message: Message, config: Config, status_client: StatusClient) -> None:
    await _reply_status(message, config, status_client, log_label="/status")


# Тестовый хендлер: на ЛЮБОЕ сообщение в личке с ботом отдаём результат парсинга.
# Зарегистрирован после команд, поэтому /start, /status, /id имеют приоритет.
# Фильтр по private — чтобы не отвечать в групповом чате уведомлений.
@router.message(F.chat.type == "private")
async def any_message(message: Message, config: Config, status_client: StatusClient) -> None:
    await _reply_status(message, config, status_client, log_label="any-message")


async def _reply_status(
    message: Message, config: Config, status_client: StatusClient, log_label: str
) -> None:
    try:
        snapshot = await status_client.fetch()
    except Exception:
        logger.exception("Не удалось получить статус для %s", log_label)
        await message.answer("⚠️ Не удалось получить данные со status.claude.com. Попробуйте позже.")
        return

    await message.answer(format_overall(snapshot, config.timezone))
