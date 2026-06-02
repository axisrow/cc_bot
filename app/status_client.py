"""Асинхронный клиент к Atlassian Statuspage API (status.claude.com)."""

from __future__ import annotations

import asyncio
import hashlib
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


def build_snapshot(
    summary: dict, incidents: list[dict], maintenances: list[dict]
) -> StatusSnapshot:
    """Собрать снапшот из summary.json и выделенных эндпоинтов."""
    status = summary.get("status") or {}
    return StatusSnapshot(
        indicator=status.get("indicator", "unknown"),
        description=status.get("description", ""),
        components=summary.get("components", []),
        incidents=incidents,
        maintenances=maintenances,
    )


def summary_marker(summary: dict) -> str:
    """Стабильная подпись summary.json — меняется только при реальном событии.

    Основа — page.updated_at (это время последнего события, а не запроса), плюс
    индикатор и статусы компонентов/активных инцидентов и работ как подстраховка.
    Поллер сравнивает подпись с прошлой, чтобы не дёргать тяжёлые эндпоинты зря.
    """
    page = summary.get("page") or {}
    status = summary.get("status") or {}
    parts = [str(page.get("updated_at")), str(status.get("indicator"))]
    for c in summary.get("components", []):
        parts.append(f"c:{c.get('id')}={c.get('status')}")
    for i in summary.get("incidents", []):
        parts.append(f"i:{i.get('id')}={(latest_update(i) or {}).get('id')}:{i.get('status')}")
    for m in summary.get("scheduled_maintenances", []):
        parts.append(f"m:{m.get('id')}={(latest_update(m) or {}).get('id')}:{m.get('status')}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


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

    async def fetch_summary(self) -> dict:
        """Лёгкий запрос: только summary.json (компоненты + общий статус, ~2 КБ).

        Поллер опрашивает его каждый цикл и по summary_marker решает, нужно ли
        вообще тянуть тяжёлые эндпоинты.
        """
        return await self._get_json("summary.json")

    async def fetch_details(self) -> tuple[list[dict], list[dict]]:
        """Тяжёлые эндпоинты: инциденты и работы (видны resolved/completed)."""
        incidents_data, maintenances_data = await asyncio.gather(
            self._get_json("incidents.json"),
            self._get_json("scheduled-maintenances.json"),
        )
        return (
            incidents_data.get("incidents", []),
            maintenances_data.get("scheduled_maintenances", []),
        )

    async def fetch(self) -> StatusSnapshot:
        """Полный опрос (summary + детали) без гейта. Используется командой /test.

        Компоненты и общий статус берём из summary.json; инциденты и работы —
        из выделенных эндпоинтов, чтобы видеть resolved/completed события.
        Summary и детали тянем параллельно — латентность как у одного round-trip.
        """
        summary, (incidents, maintenances) = await asyncio.gather(
            self.fetch_summary(),
            self.fetch_details(),
        )
        return build_snapshot(summary, incidents, maintenances)
