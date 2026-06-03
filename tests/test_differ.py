"""Офлайн-тесты RSS-first логики уведомлений (без Telegram и сети)."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.differ import Event, diff
from app.formatter import format_event, format_overall
from app.poller import poll_once
from app.state import empty_state
from app.status_client import RssItem, StatusSnapshot, parse_rss_items

UTC = ZoneInfo("UTC")


def rss_item(
    *,
    guid: str = "https://status.claude.com/incidents/inc_1",
    title: str = "Elevated API error rates",
    pub_date: str = "Wed, 03 Jun 2026 07:10:01 +0000",
    status: str = "Investigating",
    body: str = "We are currently investigating this issue.",
    incident_id: str = "inc_1",
) -> RssItem:
    return RssItem(
        guid=guid,
        link=guid,
        title=title,
        pub_date=pub_date,
        description="",
        incident_id=incident_id,
        latest_status=status,
        latest_body=body,
    )


def snapshot(incident: dict | None = None, components: list[dict] | None = None) -> StatusSnapshot:
    return StatusSnapshot(
        indicator="none",
        description="All Systems Operational",
        components=components or [],
        incidents=[incident] if incident else [],
        maintenances=[],
    )


def json_incident(status: str = "investigating", impact: str = "major") -> dict:
    return {
        "id": "inc_1",
        "name": "Elevated API error rates",
        "status": status,
        "impact": impact,
        "shortlink": "https://stspg.io/abc",
        "incident_updates": [],
    }


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Elevated errors on Opus 4.7</title>
      <description>
        &lt;p&gt; &lt;small&gt;Jun &lt;var data-var='date'&gt;3&lt;/var&gt;, &lt;var data-var='time'&gt;07:28&lt;/var&gt; UTC&lt;/small&gt;&lt;br&gt; &lt;strong&gt;Monitoring&lt;/strong&gt; - A fix has been implemented and we are monitoring the results. &lt;/p&gt;
        &lt;p&gt; &lt;small&gt;Jun &lt;var data-var='date'&gt;3&lt;/var&gt;, &lt;var data-var='time'&gt;07:10&lt;/var&gt; UTC&lt;/small&gt;&lt;br&gt; &lt;strong&gt;Investigating&lt;/strong&gt; - We are currently investigating this issue. &lt;/p&gt;
      </description>
      <pubDate>Wed, 03 Jun 2026 07:28:39 +0000</pubDate>
      <link>https://status.claude.com/incidents/thp2kyjx60qn</link>
      <guid>https://status.claude.com/incidents/thp2kyjx60qn</guid>
    </item>
  </channel>
</rss>
"""


def seed_state(item: RssItem) -> dict:
    _, state = diff([item], empty_state())
    return state


# --- RSS parsing -------------------------------------------------------------


def test_parse_rss_item_uses_latest_description_block():
    items = parse_rss_items(SAMPLE_RSS)

    assert len(items) == 1
    item = items[0]
    assert item.incident_id == "thp2kyjx60qn"
    assert item.latest_status == "Monitoring"
    assert item.latest_body == "A fix has been implemented and we are monitoring the results."
    assert item.pub_date == "Wed, 03 Jun 2026 07:28:39 +0000"


# --- RSS diff ----------------------------------------------------------------


def test_first_rss_run_seeds_without_events():
    item = rss_item()
    events, state = diff([item], empty_state())

    assert events == []
    assert state["rss_initialized"] is True
    assert state["rss_items"][item.guid]["pub_date"] == item.pub_date
    assert state["rss_items"][item.guid]["message_id"] is None


def test_legacy_json_state_is_seeded_without_rss_history_spam():
    item = rss_item()
    legacy_state = {"initialized": True, "incidents": {"old": "u1"}}
    events, state = diff([item], legacy_state)

    assert events == []
    assert state["rss_initialized"] is True
    assert state["incidents"] == {"old": "u1"}


def test_new_rss_guid_emits_send():
    old_item = rss_item()
    state = seed_state(old_item)
    new_item = rss_item(
        guid="https://status.claude.com/incidents/inc_2",
        title="Login failures",
        incident_id="inc_2",
    )

    events, _ = diff([new_item, old_item], state)

    assert events == [Event(action="send", item=new_item)]


def test_new_resolved_rss_guid_emits_send_resolved():
    old_item = rss_item()
    state = seed_state(old_item)
    resolved_item = rss_item(
        guid="https://status.claude.com/incidents/inc_2",
        title="Login failures",
        incident_id="inc_2",
        status="Resolved",
        pub_date="Wed, 03 Jun 2026 08:00:00 +0000",
        body="This incident has been resolved.",
    )

    events, _ = diff([resolved_item, old_item], state)

    assert events == [Event(action="send_resolved", item=resolved_item)]


def test_non_resolved_update_emits_edit_with_message_id():
    old_item = rss_item()
    state = seed_state(old_item)
    state["rss_items"][old_item.guid]["message_id"] = 42
    updated = rss_item(
        pub_date="Wed, 03 Jun 2026 07:28:39 +0000",
        status="Monitoring",
        body="A fix has been implemented.",
    )

    events, new_state = diff([updated], state)

    assert events == [Event(action="edit", item=updated, message_id=42)]
    assert new_state["rss_items"][updated.guid]["message_id"] == 42
    assert new_state["rss_items"][updated.guid]["pub_date"] == updated.pub_date


def test_resolved_update_emits_new_green_message_once():
    old_item = rss_item()
    state = seed_state(old_item)
    state["rss_items"][old_item.guid]["message_id"] = 42
    resolved = rss_item(
        pub_date="Wed, 03 Jun 2026 08:00:00 +0000",
        status="Resolved",
        body="This incident has been resolved.",
    )

    events, new_state = diff([resolved], state)
    assert events == [Event(action="send_resolved", item=resolved, message_id=42)]

    new_state["rss_items"][resolved.guid]["resolved_message_id"] = 99
    repeat_events, _ = diff([resolved], new_state)
    assert repeat_events == []


# --- Formatting --------------------------------------------------------------


def test_format_event_uses_json_impact_icon_and_rss_body():
    item = rss_item(body="We are <looking> into errors.")
    event = Event(action="send", item=item)

    text = format_event(event, UTC, snapshot(json_incident(impact="critical")))

    assert "🔴" in text
    assert "[New incident]" in text
    assert "Impact: <b>critical</b>" in text
    assert "&lt;looking&gt;" in text
    assert "https://stspg.io/abc" in text


def test_format_resolved_is_green_even_if_json_lags():
    item = rss_item(
        pub_date="Wed, 03 Jun 2026 08:00:00 +0000",
        status="Resolved",
        body="This incident has been resolved.",
    )
    event = Event(action="send_resolved", item=item, message_id=42)

    text = format_event(event, UTC, snapshot(json_incident(status="monitoring", impact="major")))

    assert "✅" in text
    assert "[Incident resolved]" in text
    assert "Status: <b>Resolved</b>" in text
    assert "This incident has been resolved." in text


def test_format_overall_lists_active_json_incidents_for_test_command():
    snap = snapshot(json_incident(status="investigating", impact="major"))

    text = format_overall(snap, UTC)

    assert "Partial System Outage" in text
    assert "Elevated API error rates" in text


# --- Poller send/edit behavior ----------------------------------------------


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.edited: list[tuple[int, int, str]] = []

    async def send_message(self, chat_id: int, text: str):
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=100 + len(self.sent))

    async def edit_message_text(self, text: str, *, chat_id: int, message_id: int):
        self.edited.append((chat_id, message_id, text))
        return True


class FakeClient:
    def __init__(self, items: list[RssItem], snap: StatusSnapshot) -> None:
        self.items = items
        self.snap = snap
        self.fetch_count = 0

    async def fetch_rss(self) -> list[RssItem]:
        return self.items

    async def fetch(self) -> StatusSnapshot:
        self.fetch_count += 1
        return self.snap


@pytest.mark.asyncio
async def test_poller_edits_non_resolved_update(monkeypatch):
    old_item = rss_item()
    state = seed_state(old_item)
    state["rss_items"][old_item.guid]["message_id"] = 42
    updated = rss_item(
        pub_date="Wed, 03 Jun 2026 07:28:39 +0000",
        status="Monitoring",
        body="A fix has been implemented.",
    )
    saved: list[dict] = []
    monkeypatch.setattr("app.poller.save_state", lambda state: saved.append(copy.deepcopy(state)))

    bot = FakeBot()
    new_state = await poll_once(
        bot,
        FakeClient([updated], snapshot(json_incident(status="monitoring", impact="minor"))),
        SimpleNamespace(chat_id=1, timezone=UTC),
        state,
    )

    assert bot.sent == []
    assert len(bot.edited) == 1
    assert bot.edited[0][1] == 42
    assert "Incident update" in bot.edited[0][2]
    assert new_state["rss_items"][updated.guid]["message_id"] == 42
    assert saved


@pytest.mark.asyncio
async def test_poller_sends_resolved_as_new_message(monkeypatch):
    old_item = rss_item()
    state = seed_state(old_item)
    state["rss_items"][old_item.guid]["message_id"] = 42
    resolved = rss_item(
        pub_date="Wed, 03 Jun 2026 08:00:00 +0000",
        status="Resolved",
        body="This incident has been resolved.",
    )
    saved: list[dict] = []
    monkeypatch.setattr("app.poller.save_state", lambda state: saved.append(copy.deepcopy(state)))

    bot = FakeBot()
    new_state = await poll_once(
        bot,
        FakeClient([resolved], snapshot(json_incident(status="resolved", impact="minor"))),
        SimpleNamespace(chat_id=1, timezone=UTC),
        state,
    )

    assert bot.edited == []
    assert len(bot.sent) == 1
    assert "✅" in bot.sent[0][1]
    assert "Incident resolved" in bot.sent[0][1]
    assert new_state["rss_items"][resolved.guid]["resolved_message_id"] == 101
    assert saved


@pytest.mark.asyncio
async def test_poller_ignores_json_component_changes_without_rss_event(monkeypatch):
    item = rss_item()
    state = seed_state(item)
    state["rss_items"][item.guid]["message_id"] = 42
    saved: list[dict] = []
    monkeypatch.setattr("app.poller.save_state", lambda state: saved.append(copy.deepcopy(state)))
    client = FakeClient(
        [item],
        snapshot(
            json_incident(),
            components=[{"id": "comp_api", "name": "API", "status": "major_outage"}],
        ),
    )

    bot = FakeBot()
    await poll_once(bot, client, SimpleNamespace(chat_id=1, timezone=UTC), state)

    assert bot.sent == []
    assert bot.edited == []
    assert client.fetch_count == 0
    assert saved == []
