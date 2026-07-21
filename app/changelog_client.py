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
    """Один релиз из верхнего блока CHANGELOG."""

    version: str  # "2.1.216"
    notes_md: str  # буллеты верхнего блока до следующего "## "


def parse_top_release(text: str) -> Release | None:
    """Вернуть верхний релиз из CHANGELOG. Чистая, без сети.

    Первый заголовок вида '## <version>' задаёт версию; notes — строки от него
    до следующего '## '. Если заголовка нет или он пустой — None.
    """
    lines = text.splitlines()
    headers = [i for i, line in enumerate(lines) if line.startswith("## ")]
    if not headers:
        return None
    start = headers[0]
    end = headers[1] if len(headers) > 1 else len(lines)
    version = lines[start][len("## "):].strip()
    if not version:
        return None
    notes_md = "\n".join(lines[start + 1:end]).strip()
    return Release(version=version, notes_md=notes_md)


class ChangelogClient:
    """Тонкая обёртка над CHANGELOG.md репозитория claude-code."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def fetch_top_release(self) -> Release | None:
        """Получить верхний релиз из CHANGELOG. None, если источник не распарсен."""
        return parse_top_release(await get_text(self._session, CHANGELOG_URL))
