"""Офлайн-тесты отслеживания релизов Claude Code (без Telegram и сети)."""

from __future__ import annotations

from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.changelog_client import Release, parse_top_release
from app.poller import poll_changelog_once

UTC = ZoneInfo("UTC")

_CHANGELOG_SAMPLE = """\
# Changelog

## 2.1.216

- Added `sandbox.filesystem.disabled` setting
- Fixed a slowdown in long sessions

## 2.1.215

- Fixed auto mode denying commands
"""


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, message_thread_id=None):
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=100 + len(self.sent))


class FakeChangelogClient:
    def __init__(self, release: Release | None) -> None:
        self._release = release

    async def fetch_top_release(self) -> Release | None:
        return self._release


def _config(chat_id: int | None = 1) -> SimpleNamespace:
    return SimpleNamespace(
        chat_id=chat_id, message_thread_id=None, timezone=UTC
    )


# --- Парсер (чистая функция) ---


def test_parse_top_release_extracts_version_and_notes():
    release = parse_top_release(_CHANGELOG_SAMPLE)
    assert release is not None
    assert release.version == "2.1.216"
    assert "sandbox.filesystem.disabled" in release.notes_md
    assert "Fixed a slowdown" in release.notes_md
    # notes верхнего блока, без следующего релиза
    assert "auto mode" not in release.notes_md


def test_parse_top_release_no_header_returns_none():
    assert parse_top_release("Обычный текст без заголовков.\nВторая строка.") is None


def test_parse_top_release_empty_notes():
    release = parse_top_release("# Changelog\n\n## 2.1.217\n\n## 2.1.216\n")
    assert release is not None
    assert release.version == "2.1.217"
    assert release.notes_md == ""


# --- poll_changelog_once ---


@pytest.mark.asyncio
async def test_poll_changelog_first_run_seeds_silently(monkeypatch):
    """Первый запуск: сохранённой версии нет → записываем, но ничего не шлём."""
    monkeypatch.setattr("app.poller.read_cc_version", lambda: "")
    written: list[str] = []
    monkeypatch.setattr("app.poller.write_cc_version", lambda v: written.append(v))

    bot = FakeBot()
    client = FakeChangelogClient(Release("2.1.216", "- Fix"))
    await poll_changelog_once(bot, client, _config())

    assert bot.sent == []
    assert written == ["2.1.216"]


@pytest.mark.asyncio
async def test_poll_changelog_new_version_sends_message(monkeypatch):
    """Сохранена старая версия, CHANGELOG отдаёт новую → уходим сообщение."""
    monkeypatch.setattr("app.poller.read_cc_version", lambda: "2.1.215")
    monkeypatch.setattr("app.poller.write_cc_version", lambda v: None)

    bot = FakeBot()
    client = FakeChangelogClient(Release("2.1.216", "- Fix"))
    await poll_changelog_once(bot, client, _config())

    assert len(bot.sent) == 1
    assert "2.1.216" in bot.sent[0][1]


@pytest.mark.asyncio
async def test_poll_changelog_same_version_noop(monkeypatch):
    """Сохранённая версия совпадает с top → ничего не делаем: ни send, ни write."""
    written: list[str] = []
    monkeypatch.setattr("app.poller.read_cc_version", lambda: "2.1.216")
    monkeypatch.setattr("app.poller.write_cc_version", lambda v: written.append(v))

    bot = FakeBot()
    client = FakeChangelogClient(Release("2.1.216", "- Fix"))
    await poll_changelog_once(bot, client, _config())

    assert bot.sent == []
    assert written == []


@pytest.mark.asyncio
async def test_poll_changelog_does_not_touch_state_json(monkeypatch):
    """Версия в отдельном файле: changelog-poller не должен звать save_state."""
    monkeypatch.setattr("app.poller.read_cc_version", lambda: "2.1.215")
    state_saves: list = []
    monkeypatch.setattr("app.poller.save_state", lambda *a, **k: state_saves.append(a))
    monkeypatch.setattr("app.poller.write_cc_version", lambda v: None)

    bot = FakeBot()
    client = FakeChangelogClient(Release("2.1.216", "- Fix"))
    await poll_changelog_once(bot, client, _config())

    assert len(bot.sent) == 1
    assert state_saves == []  # общий state.json changelog-poller не трогает


@pytest.mark.asyncio
async def test_poll_changelog_no_chat_id_logs_only(monkeypatch):
    """CHAT_ID не задан → новый релиз логируется, но не отправляется."""
    monkeypatch.setattr("app.poller.read_cc_version", lambda: "2.1.215")
    monkeypatch.setattr("app.poller.write_cc_version", lambda v: None)

    bot = FakeBot()
    client = FakeChangelogClient(Release("2.1.216", "- Fix"))
    await poll_changelog_once(bot, client, _config(chat_id=None))

    assert bot.sent == []


@pytest.mark.asyncio
async def test_poll_changelog_unparseable_skips(monkeypatch):
    """CHANGELOG не распарсен (None) → скип, без записи версии."""
    written: list[str] = []
    monkeypatch.setattr("app.poller.read_cc_version", lambda: "2.1.215")
    monkeypatch.setattr("app.poller.write_cc_version", lambda v: written.append(v))

    bot = FakeBot()
    client = FakeChangelogClient(None)
    await poll_changelog_once(bot, client, _config())

    assert bot.sent == []
    assert written == []
