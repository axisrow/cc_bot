"""Офлайн-тесты отслеживания релизов Claude Code (без Telegram и сети)."""

from __future__ import annotations

from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.changelog_client import Release, parse_top_release
from app.formatter import format_release
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


class FailingSend(Exception):
    """Эмуляция провала Telegram-отправки (например, TelegramBadRequest)."""


class FakeBot:
    def __init__(self, fail_send: bool = False) -> None:
        self.sent: list[tuple[int, str]] = []
        self.fail_send = fail_send

    async def send_message(self, chat_id: int, text: str, message_thread_id=None):
        if self.fail_send:
            raise FailingSend("message is too long")
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


def test_parse_top_release_extracts_top_version():
    release = parse_top_release(_CHANGELOG_SAMPLE)
    assert release is not None
    assert release.version == "2.1.216"


def test_parse_top_release_no_header_returns_none():
    assert parse_top_release("Обычный текст без заголовков.\nВторая строка.") is None


def test_parse_top_release_empty_header_returns_none():
    # заголовок есть, но версия пустая → None
    assert parse_top_release("# Changelog\n\n##  \n\n## 2.1.216\n") is None


# --- poll_changelog_once ---


@pytest.mark.asyncio
async def test_poll_changelog_first_run_seeds_silently(monkeypatch):
    """Первый запуск: сохранённой версии нет → записываем, но ничего не шлём."""
    monkeypatch.setattr("app.poller.read_cc_version", lambda: "")
    written: list[str] = []
    monkeypatch.setattr("app.poller.write_cc_version", lambda v: written.append(v))

    bot = FakeBot()
    client = FakeChangelogClient(Release("2.1.216"))
    await poll_changelog_once(bot, client, _config())

    assert bot.sent == []
    assert written == ["2.1.216"]


@pytest.mark.asyncio
async def test_poll_changelog_new_version_sends_and_checkpoints(monkeypatch):
    """Новый релиз: сообщение уходит, checkpoint пишется ПОСЛЕ успешного send."""
    monkeypatch.setattr("app.poller.read_cc_version", lambda: "2.1.215")
    events: list[str] = []

    def _write(v):
        events.append(f"write:{v}")

    async def _fake_send(bot_arg, chat_id, text, thread_id=None):
        events.append(f"send:{chat_id}")
        return 101

    monkeypatch.setattr("app.poller.write_cc_version", _write)
    monkeypatch.setattr("app.poller._send", _fake_send)

    bot = FakeBot()
    client = FakeChangelogClient(Release("2.1.216"))
    await poll_changelog_once(bot, client, _config())

    # Порядок критичен: send ДО write. Если write первым — провал отправки
    # пометит релиз доставленным (регрессия Codex-фишинга).
    assert events == ["send:1", "write:2.1.216"]


@pytest.mark.asyncio
async def test_poll_changelog_failed_send_leaves_version_uncheckpointed(monkeypatch):
    """Регрессия: провал _send НЕ должен продвигать checkpoint версии.

    Иначе отклонённый Telegram-релиз (oversized / bad-request) навсегда
    теряется — версия записана как доставленная, но в чат не ушла.
    """
    monkeypatch.setattr("app.poller.read_cc_version", lambda: "2.1.215")
    written: list[str] = []
    monkeypatch.setattr("app.poller.write_cc_version", lambda v: written.append(v))

    bot = FakeBot(fail_send=True)
    client = FakeChangelogClient(Release("2.1.216"))
    with pytest.raises(FailingSend):
        await poll_changelog_once(bot, client, _config())

    assert bot.sent == []
    assert written == []  # версия не записана → следующий цикл повторит


@pytest.mark.asyncio
async def test_poll_changelog_same_version_noop(monkeypatch):
    """Сохранённая версия совпадает с top → ничего не делаем: ни send, ни write."""
    written: list[str] = []
    monkeypatch.setattr("app.poller.read_cc_version", lambda: "2.1.216")
    monkeypatch.setattr("app.poller.write_cc_version", lambda v: written.append(v))

    bot = FakeBot()
    client = FakeChangelogClient(Release("2.1.216"))
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
    client = FakeChangelogClient(Release("2.1.216"))
    await poll_changelog_once(bot, client, _config())

    assert len(bot.sent) == 1
    assert state_saves == []  # общий state.json changelog-poller не трогает


@pytest.mark.asyncio
async def test_poll_changelog_no_chat_id_checkpoints_without_sending(monkeypatch):
    """CHAT_ID не задан → новый релиз не отправляется, но версия фиксируется.

    Иначе при позднем включении CHAT_ID бот выплюнет все пропущенные релизы
    скопом. Считаем «замеченным», доставка не требуется.
    """
    monkeypatch.setattr("app.poller.read_cc_version", lambda: "2.1.215")
    written: list[str] = []
    monkeypatch.setattr("app.poller.write_cc_version", lambda v: written.append(v))

    bot = FakeBot()
    client = FakeChangelogClient(Release("2.1.216"))
    await poll_changelog_once(bot, client, _config(chat_id=None))

    assert bot.sent == []
    assert written == ["2.1.216"]


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


def test_format_release_is_compact_under_telegram_limit():
    """Регрессия oversized: сообщение о релизе не должно превышать лимит Telegram.

    Живой релиз Claude Code содержит десятки строк changelog'а (~5KB), что
    превышает лимит sendMessage (4096) и приводит к rejection. Формат держит
    только версию + ссылку, поэтому длина ограничена и не зависит от содержания.
    """
    msg = format_release(Release("2.1.216"))
    assert len(msg) < 4096
    assert "2.1.216" in msg
    assert "CHANGELOG.md" in msg or "raw.githubusercontent" in msg
