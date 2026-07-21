"""Форматирование событий в HTML-сообщения для Telegram."""

from __future__ import annotations

import html
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from app.changelog_client import CHANGELOG_URL, Release
from app.differ import Event
from app.status_client import RssItem, StatusSnapshot

# Эмодзи по серьёзности инцидента
_IMPACT_EMOJI = {
    "critical": "🔴",
    "major": "🟠",
    "minor": "🟡",
    "maintenance": "🛠",
    "none": "🔵",
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


def _fmt_rss_time(value: str | None, tz: ZoneInfo) -> str:
    """RFC 2822 pubDate -> 'YYYY-MM-DD HH:MM TZ'."""
    if not value:
        return ""
    try:
        dt = parsedate_to_datetime(value)
        return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
    except (ValueError, TypeError):
        return value


def find_json_incident(item: RssItem, snapshot: StatusSnapshot | None) -> dict | None:
    """Найти JSON-инцидент для RSS item по incident_id. Общий lookup для poller и formatter."""
    if snapshot is None or item.incident_id is None:
        return None
    for incident in snapshot.incidents:
        if incident.get("id") == item.incident_id:
            return incident
    return None


def _json_or_rss_status(item: RssItem, json_item: dict | None) -> str:
    # RSS owns the resolved transition; JSON can briefly lag behind it.
    rss = (item.latest_status or "").strip()
    if rss.lower() == "resolved":
        return "resolved"
    return (json_item or {}).get("status") or rss.lower()


def _format_incident(event: Event, tz: ZoneInfo, snapshot: StatusSnapshot | None = None) -> str:
    item = event.item
    json_item = find_json_incident(item, snapshot)
    impact = (json_item or {}).get("impact") or "unknown"
    status = _json_or_rss_status(item, json_item)
    resolved = status == "resolved"

    if resolved:
        emoji = "✅"
        prefix = "Incident resolved"
    else:
        emoji = _IMPACT_EMOJI.get(impact, "🔵")
        prefix = "New incident" if event.action == "send" else "Incident update"

    lines = [
        f"{emoji} <b>[{prefix}] {_esc(item.title)}</b>",
        f"Impact: <b>{_esc(impact)}</b> · Status: <b>{_esc(_pretty_status(status))}</b>",
    ]
    if item.latest_body:
        lines.append("")
        lines.append(_esc(item.latest_body))
    tail = []
    if item.pub_date:
        tail.append(f"🕒 {_esc(_fmt_rss_time(item.pub_date, tz))}")
    if tail:
        lines.append("")
        lines.extend(tail)
    link = (json_item or {}).get("shortlink") or item.link
    if link:
        lines.append(f"🔗 {_esc(link)}")
    return "\n".join(lines)


def format_event(event: Event, tz: ZoneInfo, snapshot: StatusSnapshot | None = None) -> str:
    """Сформировать HTML-сообщение для одного события.

    RSS создаёт событие, snapshot нужен только для JSON enrichment.
    """
    return _format_incident(event, tz, snapshot)


def format_release(release: Release) -> str:
    """HTML-сообщение о новом релизе Claude Code.

    notes_md эскейпится: внутри markdown-инлайнов могут быть <, >, &.
    """
    lines = [f"🚀 <b>Claude Code {_esc(release.version)}</b>"]
    if release.notes_md:
        lines.append("")
        lines.append(_esc(release.notes_md))
    lines.append("")
    lines.append(f"🔗 {_esc(CHANGELOG_URL)}")
    return "\n".join(lines)


def _overall_header(snapshot: StatusSnapshot) -> tuple[str, str]:
    """Эмодзи и описание общего статуса страницы.

    Statuspage иногда держит общий индикатор зелёным ("none"), пока инцидент
    ещё не задел компоненты. Если есть активные инциденты, не показываем
    «All Systems Operational» — иначе заголовок противоречит реальности.
    """
    active_incidents = [
        i for i in snapshot.incidents if i.get("status") != "resolved"
    ]
    emoji = _INDICATOR_EMOJI.get(snapshot.indicator, "ℹ️")
    description = snapshot.description or "Status unknown"
    if active_incidents and _SEVERITY_RANK.get(snapshot.indicator, 0) == 0:
        worst = max(
            (_SEVERITY_RANK.get(i.get("impact", "none"), 0) for i in active_incidents),
            default=0,
        )
        effective = _RANK_INDICATOR[max(worst, _SEVERITY_RANK["minor"])]
        emoji = _INDICATOR_EMOJI[effective]
        description = _INDICATOR_LABEL[effective]
    return emoji, description


def format_overall(snapshot: StatusSnapshot, tz: ZoneInfo) -> str:
    """Сводка текущего состояния для команды /test."""
    active_incidents = [
        i for i in snapshot.incidents if i.get("status") != "resolved"
    ]
    active_maintenances = [
        m for m in snapshot.maintenances if m.get("status") != "completed"
    ]

    emoji, description = _overall_header(snapshot)
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
