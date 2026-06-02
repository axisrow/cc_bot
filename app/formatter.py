"""Форматирование событий в HTML-сообщения для Telegram."""

from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from app.differ import Event
from app.status_client import StatusSnapshot, latest_update

# Эмодзи по серьёзности инцидента
_IMPACT_EMOJI = {
    "critical": "🔴",
    "major": "🟠",
    "minor": "🟡",
    "maintenance": "🛠",
    "none": "🔵",
}

# Эмодзи по статусу компонента
_COMPONENT_EMOJI = {
    "operational": "✅",
    "degraded_performance": "🟡",
    "partial_outage": "🟠",
    "major_outage": "🔴",
    "under_maintenance": "🛠",
}

# Эмодзи общего индикатора статус-страницы
_INDICATOR_EMOJI = {
    "none": "✅",
    "minor": "🟡",
    "major": "🟠",
    "critical": "🔴",
    "maintenance": "🛠",
}

# Серьёзность impact/индикатора для сравнения (чем больше — тем хуже).
_SEVERITY_RANK = {"none": 0, "maintenance": 0, "minor": 1, "major": 2, "critical": 3}
_RANK_INDICATOR = {1: "minor", 2: "major", 3: "critical"}
# Подписи, когда заголовок выводим сами (индикатор страницы недооценил ситуацию).
_INDICATOR_LABEL = {
    "minor": "Minor Service Issues",
    "major": "Partial System Outage",
    "critical": "Major System Outage",
}


def _esc(text: str | None) -> str:
    return html.escape(text or "")


def _pretty_status(status: str | None) -> str:
    """under_maintenance -> 'Under maintenance'."""
    if not status:
        return ""
    return status.replace("_", " ").capitalize()


def _fmt_time(value: str | None, tz: ZoneInfo) -> str:
    """ISO 8601 -> 'YYYY-MM-DD HH:MM TZ'. При ошибке вернуть исходную строку."""
    if not value:
        return ""
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
    except (ValueError, TypeError):
        return value


def _latest_update_body(item: dict) -> tuple[str, str]:
    """Вернуть (текст последнего обновления, его время)."""
    update = latest_update(item)
    if not update:
        return "", ""
    return update.get("body", ""), update.get("created_at", "")


def _format_incident(event: Event, tz: ZoneInfo) -> str:
    item = event.obj
    impact = item.get("impact", "none")
    emoji = _IMPACT_EMOJI.get(impact, "🔵")
    prefix = "New incident" if event.action == "new" else "Incident update"

    body, when = _latest_update_body(item)
    lines = [
        f"{emoji} <b>[{prefix}] {_esc(item.get('name'))}</b>",
        f"Impact: <b>{_esc(impact)}</b> · Status: <b>{_esc(_pretty_status(item.get('status')))}</b>",
    ]
    if body:
        lines.append("")
        lines.append(_esc(body))
    if when:
        lines.append("")
        lines.append(f"🕒 {_esc(_fmt_time(when, tz))}")
    shortlink = item.get("shortlink")
    if shortlink:
        lines.append(f"🔗 {_esc(shortlink)}")
    return "\n".join(lines)


def _format_maintenance(event: Event, tz: ZoneInfo) -> str:
    item = event.obj
    prefix = "New maintenance" if event.action == "new" else "Maintenance update"

    body, _ = _latest_update_body(item)
    lines = [
        f"🛠 <b>[{prefix}] {_esc(item.get('name'))}</b>",
        f"Status: <b>{_esc(_pretty_status(item.get('status')))}</b>",
    ]
    scheduled_for = _fmt_time(item.get("scheduled_for"), tz)
    scheduled_until = _fmt_time(item.get("scheduled_until"), tz)
    if scheduled_for or scheduled_until:
        lines.append(f"🗓 {_esc(scheduled_for)} → {_esc(scheduled_until)}")
    if body:
        lines.append("")
        lines.append(_esc(body))
    shortlink = item.get("shortlink")
    if shortlink:
        lines.append(f"🔗 {_esc(shortlink)}")
    return "\n".join(lines)


def _format_component(event: Event) -> str:
    item = event.obj
    old_emoji = _COMPONENT_EMOJI.get(event.old_status or "", "•")
    new_emoji = _COMPONENT_EMOJI.get(event.new_status or "", "•")
    return (
        f"⚙️ <b>{_esc(item.get('name'))}</b>\n"
        f"{old_emoji} {_esc(_pretty_status(event.old_status))} "
        f"→ {new_emoji} {_esc(_pretty_status(event.new_status))}"
    )


def format_event(event: Event, tz: ZoneInfo) -> str:
    """Сформировать HTML-сообщение для одного события."""
    if event.kind == "incident":
        return _format_incident(event, tz)
    if event.kind == "maintenance":
        return _format_maintenance(event, tz)
    if event.kind == "component":
        return _format_component(event)
    return _esc(str(event.obj.get("name", "")))


def format_overall(snapshot: StatusSnapshot, tz: ZoneInfo) -> str:
    """Сводка текущего состояния для команды /status."""
    active_incidents = [
        i for i in snapshot.incidents if i.get("status") != "resolved"
    ]
    active_maintenances = [
        m for m in snapshot.maintenances if m.get("status") != "completed"
    ]

    emoji = _INDICATOR_EMOJI.get(snapshot.indicator, "ℹ️")
    description = snapshot.description or "Status unknown"
    # Statuspage иногда держит общий индикатор зелёным ("none"), пока инцидент
    # ещё не задел компоненты. Если есть активные инциденты, не показываем
    # «All Systems Operational» — иначе заголовок противоречит списку ниже.
    if active_incidents and _SEVERITY_RANK.get(snapshot.indicator, 0) == 0:
        worst = max(
            (_SEVERITY_RANK.get(i.get("impact", "none"), 0) for i in active_incidents),
            default=0,
        )
        effective = _RANK_INDICATOR[max(worst, _SEVERITY_RANK["minor"])]
        emoji = _INDICATOR_EMOJI[effective]
        description = _INDICATOR_LABEL[effective]

    lines = [f"{emoji} <b>{_esc(description)}</b>"]

    if active_incidents:
        lines.append("")
        lines.append("<b>Active incidents:</b>")
        for inc in active_incidents:
            lines.append(
                f"• {_esc(inc.get('name'))} — {_esc(_pretty_status(inc.get('status')))}"
            )

    if active_maintenances:
        lines.append("")
        lines.append("<b>Scheduled / active maintenance:</b>")
        for m in active_maintenances:
            window = _fmt_time(m.get("scheduled_for"), tz)
            lines.append(
                f"• {_esc(m.get('name'))} — {_esc(_pretty_status(m.get('status')))}"
                + (f" ({_esc(window)})" if window else "")
            )

    if not active_incidents and not active_maintenances:
        lines.append("")
        lines.append("No active incidents or maintenance. ✅")

    return "\n".join(lines)
