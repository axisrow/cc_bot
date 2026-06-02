"""Асинхронный клиент к Atlassian Statuspage API (status.claude.com)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

API_BASE = "https://status.claude.com/api/v2"
_TIMEOUT = aiohttp.ClientTimeout(total=30)


def latest_update(item: dict) -> dict | None:
    """Последнее (новейшее) обновление инцидента/работы. API отдаёт его первым."""
    updates = item.get("incident_updates") or []
    return updates[0] if updates else None


@dataclass
class StatusSnapshot:
    """Срез данных статус-страницы за один опрос."""

    indicator: str  # общий индикатор: none / minor / major / critical
    description: str  # человекочитаемое описание общего статуса
    components: list[dict]
    incidents: list[dict]
    maintenances: list[dict]


class StatusClient:
    """Тонкая обёртка над тремя эндпоинтами Statuspage."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._base = API_BASE
        self._session = session

    async def _get_json(self, path: str) -> dict:
        url = f"{self._base}/{path}"
        async with self._session.get(url, timeout=_TIMEOUT) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def fetch(self) -> StatusSnapshot:
        """Получить компоненты, инциденты и работы за один опрос.

        Компоненты и общий статус берём из summary.json; инциденты и работы —
        из выделенных эндпоинтов, чтобы видеть resolved/completed события.
        """
        summary, incidents_data, maintenances_data = await asyncio.gather(
            self._get_json("summary.json"),
            self._get_json("incidents.json"),
            self._get_json("scheduled-maintenances.json"),
        )

        status = summary.get("status") or {}
        return StatusSnapshot(
            indicator=status.get("indicator", "unknown"),
            description=status.get("description", ""),
            components=summary.get("components", []),
            incidents=incidents_data.get("incidents", []),
            maintenances=maintenances_data.get("scheduled_maintenances", []),
        )
