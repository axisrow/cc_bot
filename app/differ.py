"""Чистая логика сравнения: снимок API + старое состояние -> список событий.

Не зависит ни от Telegram, ни от сети — легко тестируется офлайн.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.status_client import StatusSnapshot, latest_update


@dataclass
class Event:
    """Одно событие, о котором нужно уведомить."""

    kind: str  # "incident" | "maintenance" | "component"
    action: str  # "new" | "update" (для incident/maintenance); "changed" (для component)
    obj: dict[str, Any] = field(default_factory=dict)
    old_status: str | None = None  # только для component
    new_status: str | None = None  # только для component


def _latest_update_id(item: dict[str, Any]) -> str | None:
    update = latest_update(item)
    if update is None:
        # запасной ключ изменения, если обновлений нет
        return item.get("updated_at")
    return update.get("id")


def diff(
    snapshot: StatusSnapshot,
    state: dict[str, Any],
) -> tuple[list[Event], dict[str, Any]]:
    """Сравнить снимок со state и вернуть (события, новое_состояние).

    На первом запуске (в state нет ключа "initialized") события не генерируются —
    мы лишь засеваем текущие id/статусы, чтобы не спамить историей.
    """
    initialized = state.get("initialized", False)

    prev_incidents: dict[str, Any] = state.get("incidents", {})
    prev_maintenances: dict[str, Any] = state.get("maintenances", {})
    prev_components: dict[str, Any] = state.get("components", {})

    new_incidents: dict[str, Any] = {}
    new_maintenances: dict[str, Any] = {}
    new_components: dict[str, Any] = {}

    events: list[Event] = []

    def process(items: list[dict], prev: dict, new: dict, kind: str) -> None:
        # API отдаёт новейшее первым; идём в обратном порядке -> хронологически
        for item in reversed(items):
            item_id = item.get("id")
            if not item_id:
                continue
            update_id = _latest_update_id(item)
            new[item_id] = update_id
            if not initialized:
                continue
            if item_id not in prev:
                events.append(Event(kind=kind, action="new", obj=item))
            elif prev[item_id] != update_id:
                events.append(Event(kind=kind, action="update", obj=item))

    process(snapshot.incidents, prev_incidents, new_incidents, "incident")
    process(snapshot.maintenances, prev_maintenances, new_maintenances, "maintenance")

    # Компоненты: следим за сменой статуса. Контейнеры-группы пропускаем.
    for component in snapshot.components:
        if component.get("group"):
            continue
        comp_id = component.get("id")
        if not comp_id:
            continue
        status = component.get("status", "operational")
        new_components[comp_id] = status
        if not initialized:
            continue
        old = prev_components.get(comp_id)
        if old is not None and old != status:
            events.append(
                Event(
                    kind="component",
                    action="changed",
                    obj=component,
                    old_status=old,
                    new_status=status,
                )
            )

    new_state = {
        "initialized": True,
        "incidents": new_incidents,
        "maintenances": new_maintenances,
        "components": new_components,
    }
    return events, new_state
