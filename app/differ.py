"""Чистая логика RSS-событий: RSS feed + старое состояние -> действия.

JSON Statuspage не создаёт события. Он используется только позже, при форматировании,
чтобы обогатить RSS item impact/status/icon.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.status_client import RssItem


@dataclass(frozen=True)
class Event:
    """Действие, которое поллер должен выполнить в Telegram."""

    action: str  # "send" | "edit" | "send_resolved"
    item: RssItem
    message_id: int | None = None


def _is_resolved(status: str | None) -> bool:
    return (status or "").strip().lower() == "resolved"


def _entry(item: RssItem, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = previous or {}
    return {
        "pub_date": item.pub_date,
        "message_id": previous.get("message_id"),
        "resolved_message_id": previous.get("resolved_message_id"),
    }


def diff(
    items: list[RssItem],
    state: dict[str, Any],
) -> tuple[list[Event], dict[str, Any]]:
    """Сравнить RSS items со state и вернуть (действия, новое состояние).

    Первый RSS-запуск засевает текущую ленту молча. Это важно для миграции со
    старого JSON-state: если в state нет rss_initialized, историю не рассылаем.
    """
    initialized = state.get("rss_initialized", False)
    previous_items: dict[str, dict[str, Any]] = state.get("rss_items", {})

    events: list[Event] = []
    new_items: dict[str, dict[str, Any]] = {}

    # RSS отдаёт новейшее первым; отправлять пачку новых событий лучше хронологически.
    for item in reversed(items):
        previous = previous_items.get(item.guid)
        new_items[item.guid] = _entry(item, previous)

        if not initialized:
            continue
        if previous is None:
            action = "send_resolved" if _is_resolved(item.latest_status) else "send"
            events.append(Event(action=action, item=item))
            continue
        if previous.get("pub_date") == item.pub_date:
            continue

        if _is_resolved(item.latest_status):
            if previous.get("resolved_message_id") is None:
                events.append(
                    Event(
                        action="send_resolved",
                        item=item,
                        message_id=previous.get("message_id"),
                    )
                )
        else:
            events.append(
                Event(
                    action="edit",
                    item=item,
                    message_id=previous.get("message_id"),
                )
            )

    new_state = {**state, "rss_initialized": True, "rss_items": new_items}
    return events, new_state
