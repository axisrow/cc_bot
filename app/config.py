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


def _get_optional_int(name: str) -> int | None:
    """Целое из env или None, если переменная пуста/не задана."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} должно быть целым числом, получено: {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    token: str
    chat_id: int | None
    admin_id: int | None
    poll_interval: int
    timezone: ZoneInfo


def load_config() -> Config:
    """Прочитать .env и собрать объект Config. Кидает ConfigError при проблемах."""
    load_dotenv()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("BOT_TOKEN не задан. Получите токен у @BotFather и впишите в .env.")

    chat_id = _get_optional_int("CHAT_ID")
    admin_id = _get_optional_int("ADMIN_ID")

    tz_name = os.getenv("DISPLAY_TIMEZONE", "UTC").strip() or "UTC"
    try:
        timezone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Неизвестная таймзона DISPLAY_TIMEZONE={tz_name!r}") from exc

    return Config(
        token=token,
        chat_id=chat_id,
        admin_id=admin_id,
        poll_interval=_get_int("POLL_INTERVAL", 120),
        timezone=timezone,
    )
