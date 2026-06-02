"""Загрузка и валидация конфигурации из переменных окружения / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Ошибка конфигурации (отсутствует обязательный параметр и т.п.)."""


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} должно быть целым числом, получено: {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    token: str
    chat_id: int | None
    poll_interval: int
    timezone: ZoneInfo


def load_config() -> Config:
    """Прочитать .env и собрать объект Config. Кидает ConfigError при проблемах."""
    load_dotenv()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("BOT_TOKEN не задан. Получите токен у @BotFather и впишите в .env.")

    chat_id_raw = os.getenv("CHAT_ID", "").strip()
    chat_id: int | None = None
    if chat_id_raw:
        try:
            chat_id = int(chat_id_raw)
        except ValueError as exc:
            raise ConfigError(f"CHAT_ID должен быть числом, получено: {chat_id_raw!r}") from exc

    tz_name = os.getenv("DISPLAY_TIMEZONE", "UTC").strip() or "UTC"
    try:
        timezone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Неизвестная таймзона DISPLAY_TIMEZONE={tz_name!r}") from exc

    return Config(
        token=token,
        chat_id=chat_id,
        poll_interval=_get_int("POLL_INTERVAL", 120),
        timezone=timezone,
    )
