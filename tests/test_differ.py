"""Офлайн-тесты логики диффа и форматтера (без Telegram и сети)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.differ import Event, diff
from app.formatter import format_event, format_overall
from app.state import empty_state
from app.status_client import StatusSnapshot

FIXTURE = Path(__file__).parent / "fixtures" / "sample.json"
UTC = ZoneInfo("UTC")


def load_snapshot() -> StatusSnapshot:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return StatusSnapshot(
        indicator=data["indicator"],
        description=data["description"],
        components=data["components"],
        incidents=data["incidents"],
        maintenances=data["maintenances"],
    )


def seed_state(snapshot: StatusSnapshot) -> dict:
    """Получить состояние после первого (засевающего) опроса."""
    _, state = diff(snapshot, empty_state())
    return state


# --- Первый запуск -----------------------------------------------------------

def test_first_run_seeds_without_events():
    snapshot = load_snapshot()
    events, state = diff(snapshot, empty_state())

    assert events == []  # на первом запуске не спамим историей
    assert state["initialized"] is True
    assert state["incidents"] == {"inc_1": "upd_2"}  # новейшее обновление
    assert state["maintenances"] == {"mnt_1": "mupd_1"}
    # группа grp_root отфильтрована, остались только листовые компоненты
    assert state["components"] == {
        "comp_api": "operational",
        "comp_web": "degraded_performance",
    }


def test_no_changes_no_events():
    snapshot = load_snapshot()
    state = seed_state(snapshot)
    events, _ = diff(snapshot, state)
    assert events == []


# --- Инциденты ----------------------------------------------------------------

def test_new_incident_emits_event():
    snapshot = load_snapshot()
    state = seed_state(snapshot)

    new = copy.deepcopy(snapshot)
    new.incidents = new.incidents + [
        {
            "id": "inc_2",
            "name": "Login failures",
            "status": "identified",
            "impact": "critical",
            "incident_updates": [
                {"id": "u9", "status": "identified", "body": "Root cause found.",
                 "created_at": "2026-06-02T11:00:00Z"}
            ],
        }
    ]

    events, _ = diff(new, state)
    assert len(events) == 1
    assert events[0].kind == "incident"
    assert events[0].action == "new"
    assert events[0].obj["id"] == "inc_2"


def test_incident_update_emits_event():
    snapshot = load_snapshot()
    state = seed_state(snapshot)

    new = copy.deepcopy(snapshot)
    new.incidents[0]["status"] = "monitoring"
    new.incidents[0]["incident_updates"].insert(
        0,
        {"id": "upd_3", "status": "monitoring", "body": "Fix deployed, monitoring.",
         "created_at": "2026-06-02T10:30:00Z"},
    )

    events, _ = diff(new, state)
    assert len(events) == 1
    assert events[0].kind == "incident"
    assert events[0].action == "update"


# --- Работы -------------------------------------------------------------------

def test_maintenance_update_emits_event():
    snapshot = load_snapshot()
    state = seed_state(snapshot)

    new = copy.deepcopy(snapshot)
    new.maintenances[0]["status"] = "in_progress"
    new.maintenances[0]["incident_updates"].insert(
        0,
        {"id": "mupd_2", "status": "in_progress", "body": "Maintenance has begun.",
         "created_at": "2026-06-05T01:00:00Z"},
    )

    events, _ = diff(new, state)
    assert len(events) == 1
    assert events[0].kind == "maintenance"
    assert events[0].action == "update"


# --- Компоненты ---------------------------------------------------------------

def test_component_status_change_emits_event():
    snapshot = load_snapshot()
    state = seed_state(snapshot)

    new = copy.deepcopy(snapshot)
    new.components[0]["status"] = "major_outage"  # comp_api: operational -> major_outage

    events, _ = diff(new, state)
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "component"
    assert ev.old_status == "operational"
    assert ev.new_status == "major_outage"


# --- Форматтер ----------------------------------------------------------------

def test_format_incident_escapes_html():
    snapshot = load_snapshot()
    event = Event(kind="incident", action="new", obj=snapshot.incidents[0])
    text = format_event(event, UTC)

    assert "Elevated API error rates" in text
    assert "🔗" in text
    # тело содержит <looking> — должно быть экранировано
    assert "&lt;looking&gt;" in text
    assert "<looking>" not in text


def test_format_component():
    event = Event(
        kind="component",
        action="changed",
        obj={"name": "API"},
        old_status="operational",
        new_status="major_outage",
    )
    text = format_event(event, UTC)
    assert "API" in text
    assert "Operational" in text
    assert "Major outage" in text


def test_format_overall_lists_active():
    snapshot = load_snapshot()
    text = format_overall(snapshot, UTC)
    assert "Partially Degraded Service" in text
    assert "Elevated API error rates" in text
    assert "Database upgrade" in text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
