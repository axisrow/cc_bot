"""Асинхронный клиент к Atlassian Statuspage API (status.claude.com)."""

from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass
from xml.etree import ElementTree

import aiohttp

from app.http import _TIMEOUT, get_text

logger = logging.getLogger(__name__)

API_BASE = "https://status.claude.com/api/v2"
RSS_URL = "https://status.claude.com/history.rss"
_INCIDENT_ID_RE = re.compile(r"/incidents/([^/?#]+)")
_RSS_UPDATE_RE = re.compile(
    r"<p>\s*<small>(?P<when>.*?)</small>\s*<br>\s*"
    r"<strong>(?P<status>.*?)</strong>\s*-\s*(?P<body>.*?)\s*</p>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class StatusSnapshot:
    """Срез данных статус-страницы за один опрос."""

    indicator: str  # общий индикатор: none / minor / major / critical
    description: str  # человекочитаемое описание общего статуса
    components: list[dict]
    incidents: list[dict]
    maintenances: list[dict]


@dataclass(frozen=True)
class RssItem:
    """Один item из Statuspage RSS: именно он создаёт Telegram-событие."""

    guid: str
    link: str
    title: str
    pub_date: str
    description: str
    incident_id: str | None
    latest_status: str
    latest_body: str


def _text(node: ElementTree.Element, name: str) -> str:
    child = node.find(name)
    return (child.text or "").strip() if child is not None else ""


def _strip_html(value: str) -> str:
    return html.unescape(_HTML_TAG_RE.sub("", value)).strip()


def _incident_id_from_url(value: str) -> str | None:
    match = _INCIDENT_ID_RE.search(value)
    return match.group(1) if match else None


def _latest_rss_update(description: str) -> tuple[str, str]:
    """Вернуть (status, body) из первого блока RSS description.

    RSS item хранит историю обновлений целиком, новейший блок идёт первым.
    """
    match = _RSS_UPDATE_RE.search(description)
    if not match:
        return "", _strip_html(description)
    return _strip_html(match.group("status")), _strip_html(match.group("body"))


def parse_rss_items(xml_text: str) -> list[RssItem]:
    """Разобрать Statuspage RSS в список item-ов без сетевых зависимостей."""
    root = ElementTree.fromstring(xml_text)
    items: list[RssItem] = []
    for node in root.findall("./channel/item"):
        guid = _text(node, "guid")
        link = _text(node, "link")
        title = _text(node, "title")
        pub_date = _text(node, "pubDate")
        description = _text(node, "description")
        status, body = _latest_rss_update(description)
        item_id = _incident_id_from_url(guid) or _incident_id_from_url(link)
        if not guid:
            guid = link or title
        if not guid:
            continue
        items.append(
            RssItem(
                guid=guid,
                link=link,
                title=title,
                pub_date=pub_date,
                description=description,
                incident_id=item_id,
                latest_status=status,
                latest_body=body,
            )
        )
    return items


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

    async def fetch_rss(self) -> list[RssItem]:
        """Получить RSS history feed. RSS — единственный источник событий."""
        return parse_rss_items(await get_text(self._session, RSS_URL))

    async def fetch_summary(self) -> dict:
        """Лёгкий запрос: summary.json для текущей сводки и JSON enrichment."""
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
