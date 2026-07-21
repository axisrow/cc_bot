"""Общие HTTP-хелперы для клиентов статус-страницы и CHANGELOG."""

from __future__ import annotations

import aiohttp

_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def get_text(session: aiohttp.ClientSession, url: str) -> str:
    """GET url и вернуть тело как текст. Пробрасывает сетевые ошибки наружу."""
    async with session.get(url, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        return await resp.text()
