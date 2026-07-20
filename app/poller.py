"""Фоновый цикл опроса статус-страницы и рассылки уведомлений."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from app.config import Config
from app.differ import Event, diff
from app.formatter import find_json_incident, format_event
from app.state import load_state, save_state
from app.status_client import StatusClient, StatusSnapshot

logger = logging.getLogger(__name__)

# Небольшая пауза между сообщениями, чтобы не упереться в лимиты Telegram
_SEND_DELAY = 0.5


async def _send(bot: Bot, chat_id: int, text: str, thread_id: int | None = None) -> int:
    """Отправить сообщение с обработкой rate-limit (429).

    thread_id направляет сообщение в топик форум-группы; None — в General/личку.
    """
    try:
        message = await bot.send_message(chat_id, text, message_thread_id=thread_id)
    except TelegramRetryAfter as exc:
        logger.warning("Rate limit, ждём %s c", exc.retry_after)
        await asyncio.sleep(exc.retry_after)
        message = await bot.send_message(chat_id, text, message_thread_id=thread_id)
    return message.message_id


async def _edit(bot: Bot, chat_id: int, message_id: int, text: str) -> bool:
    """Отредактировать сообщение. False означает, что нужен fallback send.

    message_thread_id для edit не нужен — message_id уже однозначно адресует
    сообщение в его топике.
    """
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
        return True
    except TelegramRetryAfter as exc:
        logger.warning("Rate limit на edit, ждём %s c", exc.retry_after)
        await asyncio.sleep(exc.retry_after)
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return True
        logger.warning("Не удалось отредактировать message_id=%s: %s", message_id, exc)
        return False


async def _fetch_enrichment(client: StatusClient) -> StatusSnapshot | None:
    try:
        return await client.fetch()
    except Exception:
        logger.exception("Не удалось получить JSON enrichment, отправляю RSS-only")
        return None


def _record_message_id(state: dict, event: Event, message_id: int) -> None:
    entry = state.setdefault("rss_items", {}).setdefault(event.item.guid, {})
    if event.action == "send_resolved":
        entry["resolved_message_id"] = message_id
    else:
        entry["message_id"] = message_id


def _event_impact(event: Event, snapshot: StatusSnapshot | None) -> str:
    """impact инцидента из JSON snapshot; 'unknown' если snapshot/инцидент недоступен."""
    json_item = find_json_incident(event.item, snapshot)
    return (json_item or {}).get("impact") or "unknown"


async def poll_once(
    bot: Bot,
    client: StatusClient,
    config: Config,
    state: dict,
) -> dict:
    """Один цикл опроса: RSS -> diff -> send/edit -> новое состояние."""
    rss_items = await client.fetch_rss()
    was_initialized = state.get("rss_initialized", False)
    events, new_state = diff(rss_items, state)

    if not was_initialized:
        # Первый RSS-запуск: молча засеваем ленту, в чат ничего не шлём.
        save_state(new_state)
        logger.info(
            "Первый RSS-запуск: засеяно %d item-ов",
            len(new_state["rss_items"]),
        )
        return new_state

    if events and config.chat_id is not None:
        snapshot = await _fetch_enrichment(client)
        logger.info("Обрабатываю %d RSS-событий", len(events))
        for event in events:
            impact = _event_impact(event, snapshot)
            # Минорные инциденты и none — шум, пропускаем. Но событие для инцидента, уже
            # отправленного в чат (есть message_id), шлём всегда — даже если Statuspage
            # пересчитал JSON impact вниз. Иначе edit/resolved потеряется, pub_date в state
            # сдвинется, и Telegram зависнет на устаревшем статусе.
            already_in_chat = event.message_id is not None
            if impact in ("none", "minor") and not already_in_chat:
                logger.info("Скип %s-инцидента %s", impact, event.item.guid)
                continue
            text = format_event(event, config.timezone, snapshot)
            message_id = event.message_id
            # edit с известным message_id правит исходник; иначе (send/send_resolved/critical
            # или провал edit) шлём новое и запоминаем id. critical всегда идёт новым сообщением.
            can_edit = impact != "critical" and event.action == "edit"
            if not (
                can_edit
                and message_id is not None
                and await _edit(bot, config.chat_id, message_id, text)
            ):
                new_message_id = await _send(
                    bot, config.chat_id, text, config.message_thread_id
                )
                _record_message_id(new_state, event, new_message_id)
            await asyncio.sleep(_SEND_DELAY)
    elif events:
        logger.warning("Есть %d событий, но CHAT_ID не задан — не отправляю", len(events))

    if new_state != state:
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

    # Служебный пинг админу при запуске поллер-таски (heartbeat «бот перезапустился»).
    # Шлётся в личку ADMIN_ID, не в чат CHAT_ID, и не зависит от состояния data/state.json.
    if config.admin_id is not None:
        try:
            await _send(
                bot,
                config.admin_id,
                "✅ <b>Monitoring started</b>\nWatching status.claude.com for "
                "RSS incident updates.",
            )
        except Exception:
            logger.exception("Не удалось отправить стартовый пинг админу")

    while True:
        try:
            state = await poll_once(bot, client, config, state)
        except asyncio.CancelledError:
            logger.info("Поллер остановлен")
            raise
        except Exception:
            logger.exception("Ошибка во время опроса")
        await asyncio.sleep(config.poll_interval)
