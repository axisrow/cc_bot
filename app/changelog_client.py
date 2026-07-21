"""Асинхронный клиент к CHANGELOG.md репозитория claude-code (источник релизов)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

from app.http import get_text

logger = logging.getLogger(__name__)

CHANGELOG_URL = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"


@dataclass(frozen=True)
class Release:
    """Верхний релиз из CHANGELOG (только версия — этого хватает для уведомления)."""

    version: str  # "2.1.216"


def parse_top_release(text: str) -> Release | None:
    """Вернуть верхний релиз из CHANGELOG. Чистая, без сети.

    Первый заголовок вида '## <version>' задаёт версию. Если заголовка нет или
    он пустой — None. Буллеты changelog'а не собираем: уведомление содержит
    только версию + ссылку (полные notes превышают лимит Telegram sendMessage).
    """
    lines = text.splitlines()
    for line in lines:
        if line.startswith("## "):
            version = line[len("## "):].strip()
            if version:
                return Release(version=version)
            break
    return None


class ChangelogClient:
    """Тонкая обёртка над CHANGELOG.md репозитория claude-code."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def fetch_top_release(self) -> Release | None:
        """Получить верхний релиз из CHANGELOG. None, если источник не распарсен."""
        return parse_top_release(await get_text(self._session, CHANGELOG_URL))
