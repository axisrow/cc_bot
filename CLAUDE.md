# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## What this is

Telegram-бот на **aiogram 3.x** для `status.claude.com`. Источник уведомлений — RSS history feed
`https://status.claude.com/history.rss`. JSON API Statuspage (`/api/v2/...`) нельзя убирать: он
используется для enrichment уведомлений (impact/status/иконка/shortlink) и для команды `/test`.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # впишите BOT_TOKEN, при желании CHAT_ID

python main.py
pytest -v
pytest tests/test_differ.py::test_poller_edits_non_resolved_update

docker build -t cc-status-bot .
docker run -d --restart unless-stopped --env-file .env -v "$(pwd)/data:/app/data" \
  --name cc_status_bot cc-status-bot
```

Нет линтера/форматтера в конфиге — стиль поддерживается вручную (`from __future__ import annotations`,
типизация, короткие русские докстринги/комментарии там, где они реально помогают).

## Architecture

`main.py` поднимает два concurrent asyncio-потока на общей `aiohttp.ClientSession`:
1. `dp.start_polling` — Telegram-команды (`/start`, `/test`) из `app/handlers.py`.
2. `run_poller` — фоновый RSS poller из `app/poller.py`.

Основной конвейер уведомлений:

`StatusClient.fetch_rss()` → `diff()` → `StatusClient.fetch()` для JSON enrichment → `format_event()` → `send_message`/`edit_message_text` → `save_state()`.

- **`status_client.py`** — парсит RSS (`RssItem`) и умеет тянуть JSON snapshot для enrichment и `/test`.
- **`differ.py`** — чистая RSS-логика без сети и Telegram. Возвращает действия `send`, `edit`, `send_resolved`.
- **`formatter.py`** — текст берёт из RSS, impact/status/icon/shortlink берёт из JSON incident по id из RSS URL.
- **`poller.py`** — non-resolved RSS updates редактируют сохранённый `message_id`; `Resolved` всегда шлёт новое зелёное сообщение.
- **`state.py`** — атомарно хранит `data/state.json`.

## State invariants

Текущий контракт state: `rss_initialized: true` и `rss_items[guid]` с `pub_date`,
`message_id`, `resolved_message_id`. Старые ключи `incidents`, `maintenances`, `components`
могут оставаться в файле как legacy, но не должны создавать Telegram-события.

Первый RSS-запуск засевает ленту молча. Это важно при миграции со старого JSON-state: наличие
`initialized: true` без `rss_initialized` не должно разослать всю RSS-историю.

## Testing notes

Тесты в `tests/test_differ.py` офлайн проверяют RSS parsing, first-run seed, send/edit/resolved
actions, JSON enrichment и poller calls. При изменении RSS state shape или Telegram behavior
обновляйте эти тесты в первую очередь.
